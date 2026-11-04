"""Passkey registration and passkey-signed approvals (ADR 0003). The database is faked; its
checks mirror approve_dossier() (the real one is tested in supabase/tests/rls_test.sql)."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.approvals import payload
from app.crypto.canonical import canonicalize, sha256
from app.crypto.merkle import leaf_hash
from app.main import create_app
from app.supabase import SupabaseError
from tests.fakes.authenticator import UP, SoftPasskey, challenge_of

KEY = "test-key-that-is-long-enough-for-the-engine-1234"
CLUB = "10000000-0000-4000-8000-000000000001"
DOSSIER = "20000000-0000-4000-8000-000000000001"
MANAGER = "00000000-0000-4000-8000-00000000000a"
TREASURER = "00000000-0000-4000-8000-00000000000b"
CAPTAIN = "00000000-0000-4000-8000-00000000000c"
OUTSIDER = "00000000-0000-4000-8000-00000000000d"


def item(tx, ts, amt, fee=0, dir_="out", category="transport", cp=("player", "P01")):
    return {
        "tx": tx, "ts": ts, "amt_cents": amt, "fee_cents": fee, "dir": dir_,
        "branch": "I" if dir_ == "in" else ("A" if cp[0] == "till" else "B"),
        "category": category, "cp_type": cp[0], "cp_ref": cp[1],
        "fixture_code": "MD4-2026-10-17" if category == "transport" else None,
        "salt": f"salt-for-{tx.lower()}", "receipt_sha256": None,
    }  # fmt: skip


def content() -> dict:
    return {
        "dossier": {
            "id": DOSSIER, "club_id": CLUB, "club_name": "Synthetic FC",
            "period_from": "2026-10-01", "period_to": "2026-10-31",
            "source_sha256": "ab" * 32, "rows_total": 47,
            "integrity": {"score_bp": 9500, "checks": {
                "balance_chain": {"passed": True, "weight_bp": 4000, "detail": "47 rows"},
                "producer_baseline": {"passed": False, "weight_bp": 500, "detail": "not OpenPDF"}}},
        },
        "items": [
            item("SJB0000001", "2026-10-17T04:15:00+00:00", 25000, 700),
            item("SJB0000002", "2026-10-17T04:15:00+00:00", 25000, 700, cp=("player", "P02")),
            item("SJD0000001", "2026-10-17T08:30:00+00:00", 180000, category="meals",
                 cp=("till", "5123456")),
            item("SJA0000003", "2026-10-03T09:00:00+00:00", 400000, dir_="in",
                 category="income", cp=("person", "hmac:" + "cd" * 32)),
        ],
        "planned_spends": [],
    }  # fmt: skip


# ---- the payload ------------------------------------------------------------------------------


def test_leaves_use_kenyan_time_and_carry_the_fee() -> None:
    leaf = payload.leaf_object(content()["items"][0])
    assert leaf["ts"] == "2026-10-17T07:15:00+03:00"
    assert (leaf["amt"], leaf["fee"], leaf["cp"]) == (25000, 700, {"type": "player", "ref": "P01"})
    assert leaf["ev"] == {"receipt_sha256": None, "attest": [], "corroborated": False}


def test_payload_is_the_same_whatever_order_rows_arrive_in() -> None:
    a, hashes = payload.build(content())
    shuffled = content()
    shuffled["items"].reverse()
    assert payload.build(shuffled)[0] == a
    assert payload.challenge(a) == sha256(canonicalize(a))
    assert hashes["SJB0000001"] == leaf_hash(payload.leaf_object(content()["items"][0])).hex()


def test_payload_contents() -> None:
    a, _ = payload.build(content())
    assert (a["rows_total"], a["rows_disclosed"]) == (47, 4)
    assert a["totals_cents"] == {"income": 400000, "meals": 180000, "transport": 2 * 25700}
    assert a["integrity"] == {
        "score_bp": 9500,
        "checks": {"balance_chain": True, "producer_baseline": False},
    }
    assert a["club"] == {"id": CLUB, "name": "Synthetic FC"}


@pytest.mark.parametrize(
    "change",
    [
        lambda c: c["items"][0].update(amt_cents=25001),
        lambda c: c["items"][2].update(category="kit"),
        lambda c: c["items"].pop(),
        lambda c: c["dossier"].update(rows_total=48),
        lambda c: c["dossier"].update(source_sha256="ef" * 32),
        lambda c: c["planned_spends"].append(
            {"supplier": "Kit shop", "till": "5123456", "amt_cents": 100, "purpose": "Kit"}
        ),
    ],
)
def test_any_change_changes_the_challenge(change) -> None:
    changed = content()
    change(changed)
    assert payload.challenge(payload.build(changed)[0]) != payload.challenge(
        payload.build(content())[0]
    )


# ---- fake database ------------------------------------------------------------------------------


class ApprovalDB:
    def __init__(self) -> None:
        self.roles = {
            (CLUB, MANAGER): "manager",
            (CLUB, TREASURER): "treasurer",
            (CLUB, CAPTAIN): "captain",
        }
        self.content = content()
        self.status = "draft"
        self.creds: dict[str, dict] = {}
        self.approvals: list[dict] = []
        self.leaf_hashes: dict | None = None

    def _fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.content, sort_keys=True).encode()).hexdigest()

    def role_of(self, club_id, user_id):
        return self.roles.get((club_id, user_id))

    def approval_snapshot(self, dossier_id):
        if dossier_id != DOSSIER:
            raise SupabaseError("dossier not found", 400, "P0002")
        manager = next((a["challenge"] for a in self.approvals if a["role"] == "manager"), None)
        return {
            **copy.deepcopy(self.content),
            "status": self.status,
            "fingerprint": self._fingerprint(),
            "manager_challenge": manager,
            "approvals": [],
        }

    def passkeys(self, user_id):
        return [
            {"id": k, "public_key": v["public_key"], "sign_count": v["sign_count"]}
            for k, v in self.creds.items()
            if v["user_id"] == user_id
        ]

    def add_passkey(self, p):
        if p["p_cred_id"] in self.creds:
            raise SupabaseError("this passkey is already registered", 409, "23505")
        self.creds[p["p_cred_id"]] = {
            "user_id": p["p_actor"],
            "public_key": p["p_public_key"],
            "sign_count": p["p_sign_count"],
        }

    def approve_dossier(self, p):
        cred = self.creds.get(p["p_cred_id"])
        if cred is None or cred["user_id"] != p["p_actor"]:
            raise SupabaseError("that passkey isn't registered to you", 400, "42501")
        if p["p_fingerprint"] != self._fingerprint():
            raise SupabaseError("the dossier changed while you were signing", 400, "40001")
        role = self.roles[(CLUB, p["p_actor"])]
        if self.status == "draft":
            assert set(p["p_leaf_hashes"]) == {i["tx"] for i in self.content["items"]}
            self.leaf_hashes, self.status = p["p_leaf_hashes"], "submitted"
        else:
            assert p["p_challenge"] == self.approvals[0]["challenge"]
            self.status = "approved"
        cred["sign_count"] = p["p_sign_count"]
        self.approvals.append(
            {"role": role, "challenge": p["p_challenge"], "cred_id": p["p_cred_id"]}
        )
        return {"dossier_id": DOSSIER, "status": self.status, "role": role}


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    app = create_app()
    app.state.supabase = ApprovalDB()
    return TestClient(app), app.state.supabase


def post(client, path, body, actor):
    return client.post(path, json=body, headers={"X-Internal-Key": KEY, "X-Actor-Id": actor})


def register(client, actor, passkey=None, **kw) -> SoftPasskey:
    passkey = passkey or SoftPasskey()
    r = post(client, "/v1/passkeys/register/options", {"user_name": "coach@example.test"}, actor)
    assert r.status_code == 200, r.text
    credential = passkey.register(r.json()["options"], **kw)
    r = post(
        client,
        "/v1/passkeys/register/verify",
        {"state": r.json()["state"], "credential": credential},
        actor,
    )
    assert r.status_code == 200, r.text
    return passkey


def options(client, actor):
    return post(client, f"/v1/dossiers/{DOSSIER}/approval/options", {}, actor)


def verify(client, actor, credential):
    return post(
        client, f"/v1/dossiers/{DOSSIER}/approval/verify", {"credential": credential}, actor
    )


# ---- registration -----------------------------------------------------------------------------


def test_registering_a_passkey(engine) -> None:
    client, db = engine
    passkey = register(client, MANAGER)
    assert db.creds[passkey.id]["user_id"] == MANAGER


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        (
            lambda o, s, c, pk: (s, pk.register(o, origin="https://evil.example")),
            "couldn't be verified",
        ),
        (
            lambda o, s, c, pk: (s, pk.register(o, flags=UP | 0x40)),
            "couldn't be verified",
        ),  # no user verification
        (lambda o, s, c, pk: (s.replace(".", ".x"), c), "isn't valid"),
        (lambda o, s, c, pk: ("garbage", c), "isn't valid"),
    ],
)
def test_bad_registrations_are_refused(engine, tamper, message) -> None:
    client, db = engine
    pk = SoftPasskey()
    r = post(client, "/v1/passkeys/register/options", {"user_name": "coach@example.test"}, MANAGER)
    o, s = r.json()["options"], r.json()["state"]
    state, credential = tamper(o, s, pk.register(o), pk)
    r = post(
        client, "/v1/passkeys/register/verify", {"state": state, "credential": credential}, MANAGER
    )
    assert r.status_code == 422 and message in r.json()["detail"]["message"]
    assert db.creds == {}


def test_registration_state_is_bound_to_the_user_and_expires(engine, monkeypatch) -> None:
    client, _ = engine
    pk = SoftPasskey()
    r = post(client, "/v1/passkeys/register/options", {"user_name": "coach@example.test"}, MANAGER)
    body = {"state": r.json()["state"], "credential": pk.register(r.json()["options"])}
    assert post(client, "/v1/passkeys/register/verify", body, TREASURER).status_code == 422
    monkeypatch.setattr("app.approvals.passkeys.time.time", lambda: 10**10)
    r = post(client, "/v1/passkeys/register/verify", body, MANAGER)
    assert r.status_code == 422 and "expired" in r.json()["detail"]["message"]


# ---- approvals --------------------------------------------------------------------------------


def test_manager_submits_and_treasurer_approves_the_same_challenge(engine) -> None:
    client, db = engine
    manager, treasurer = register(client, MANAGER), register(client, TREASURER)

    r = options(client, MANAGER)
    assert r.status_code == 200
    summary = r.json()["summary"]
    expected = payload.challenge(payload.build(content())[0])
    assert challenge_of(r.json()["options"]) == expected and summary["challenge"] == expected.hex()
    assert (summary["signing_as"], summary["rows_total"], summary["rows_disclosed"]) == (
        "manager",
        47,
        4,
    )
    assert r.json()["options"]["userVerification"] == "required"

    r = verify(client, MANAGER, manager.sign(r.json()["options"]))
    assert r.status_code == 200 and r.json()["status"] == "submitted", r.text
    assert len(db.leaf_hashes) == 4

    r = options(client, TREASURER)
    assert r.json()["summary"]["signing_as"] == "treasurer"
    r = verify(client, TREASURER, treasurer.sign(r.json()["options"]))
    assert r.status_code == 200 and r.json()["status"] == "approved", r.text
    assert db.approvals[0]["challenge"] == db.approvals[1]["challenge"] == expected.hex()


@pytest.mark.parametrize(("actor", "status"), [(TREASURER, 403), (CAPTAIN, 403), (OUTSIDER, 404)])
def test_only_the_manager_can_submit(engine, actor, status) -> None:
    client, _ = engine
    register(client, actor)
    assert options(client, actor).status_code == status


def test_signing_needs_a_passkey(engine) -> None:
    client, _ = engine
    r = options(client, MANAGER)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "no_passkey"


@pytest.mark.parametrize(
    "tamper",
    [
        lambda pk, o: pk.sign(o, challenge=b"\x00" * 32),  # signs something else
        lambda pk, o: pk.sign(o, origin="https://evil.example"),  # phished from another site
        lambda pk, o: pk.sign(o, flags=UP),  # no fingerprint, face or PIN
    ],
)
def test_assertions_that_dont_sign_this_dossier_are_refused(engine, tamper) -> None:
    client, db = engine
    pk = register(client, MANAGER)
    r = verify(client, MANAGER, tamper(pk, options(client, MANAGER).json()["options"]))
    assert r.status_code == 422 and db.status == "draft" and db.approvals == []


def test_a_change_after_the_options_call_invalidates_the_signature(engine) -> None:
    client, db = engine
    pk = register(client, MANAGER)
    o = options(client, MANAGER).json()["options"]
    db.content["items"][0]["amt_cents"] = 2500  # the ledger changes before the signature arrives
    r = verify(client, MANAGER, pk.sign(o))
    assert r.status_code == 422 and db.status == "draft"


def test_someone_elses_passkey_is_refused(engine) -> None:
    client, db = engine
    register(client, MANAGER)
    theirs = register(client, TREASURER)
    r = verify(client, MANAGER, theirs.sign(options(client, MANAGER).json()["options"]))
    assert r.status_code == 403 and db.status == "draft"


def test_a_cloned_passkey_counter_is_refused(engine) -> None:
    client, db = engine
    pk = register(client, MANAGER)
    o = options(client, MANAGER).json()["options"]
    pk.counter = 5
    db.creds[pk.id]["sign_count"] = 9  # the real authenticator has already signed 9 times
    r = verify(client, MANAGER, pk.sign(o))
    assert r.status_code == 422 and db.status == "draft"


def test_database_refusals_keep_their_meaning(engine, monkeypatch) -> None:
    client, db = engine
    pk = register(client, MANAGER)
    o = options(client, MANAGER).json()["options"]

    def changed(_):
        raise SupabaseError("the dossier changed while you were signing", 400, "40001")

    monkeypatch.setattr(db, "approve_dossier", changed)
    r = verify(client, MANAGER, pk.sign(o))
    assert r.status_code == 409 and "changed" in r.json()["detail"]["message"]


def test_approved_dossiers_are_not_signable(engine) -> None:
    client, db = engine
    register(client, MANAGER)
    db.status = "approved"
    assert options(client, MANAGER).status_code == 409


def test_payload_matches_the_published_vector() -> None:
    vectors = json.loads(
        (Path(__file__).resolve().parents[3] / "spec" / "test-vectors.json").read_text("utf-8")
    )["approval"]
    built, _ = payload.build(vectors["snapshot"])
    assert built == vectors["payload"]
    assert payload.challenge(built).hex() == vectors["challenge"]
