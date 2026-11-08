"""Sealing (CRYPTO_SPEC section 5): approve with two software passkeys, seal with a local key, then
verify the result using only what's in the sealed payload, as the sponsor's verifier will."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi.testclient import TestClient

from app.approvals import payload
from app.approvals.seal import approval_payload_of
from app.config import parse_retired_keys
from app.crypto.signer import LocalSigner, payload_digest, public_jwk, verify_digest
from app.dossier import render
from app.main import create_app
from app.supabase import SupabaseError
from tests.test_approvals import (
    CAPTAIN,
    DOSSIER,
    KEY,
    MANAGER,
    OUTSIDER,
    TREASURER,
    ApprovalDB,
    options,
    post,
    register,
    verify,
)

FAKE_PDF = b"%PDF-fake sealed dossier"


def b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class SealDB(ApprovalDB):
    """Adds what sealing reads and writes to the approvals fake."""

    def __init__(self) -> None:
        super().__init__()
        self.sealed: dict | None = None
        self.pdf_path: str | None = None
        self.pdf_sha256: str | None = None
        self.files: dict[str, bytes] = {}

    def approve_dossier(self, p):
        result = super().approve_dossier(p)
        self.approvals[-1] |= {
            "authenticator_data": p["p_authenticator_data"],
            "client_data_json": p["p_client_data_json"],
            "signature": p["p_signature"],
            "created_at": datetime.now(UTC).isoformat(),
        }
        return result

    def seal_snapshot(self, dossier_id):
        # One RPC in the real database; the base call here is that RPC's first half.
        return ApprovalDB.approval_snapshot(self, dossier_id) | {
            "signatures": [
                a | {"public_key": self.creds[a["cred_id"]]["public_key"]} for a in self.approvals
            ]
        }

    def seal_dossier(self, p):
        assert self.status == "approved"
        assert p["p_payload"]["merkle_root"] == p["p_merkle_root"]
        self.sealed, self.status = p, "sealed"
        return {"status": "sealed"}

    def sealed_record(self, dossier_id):
        return {
            "id": dossier_id,
            "club_id": self.content["dossier"]["club_id"],
            "status": self.status,
            "payload": self.sealed and self.sealed["p_payload"],
            "pdf_path": self.pdf_path,
            "pdf_sha256": self.pdf_sha256,
        }

    def upload_pdf(self, path, pdf):
        self.files[path] = pdf

    def download_pdf(self, path):
        return self.files[path]

    def attach_dossier_pdf(self, p):
        if self.pdf_sha256:
            raise SupabaseError("this dossier already has its PDF", 409, "23505")
        self.pdf_path, self.pdf_sha256 = p["p_pdf_path"], p["p_pdf_sha256"]
        return {"status": "sealed"}


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    # Real rendering is tested in test_dossier_pdf.py and needs Pango; sealing doesn't.
    monkeypatch.setattr(render, "render_pdf", lambda context: FAKE_PDF)
    app = create_app()
    app.state.supabase = SealDB()
    app.state.signer = LocalSigner.generate("local-test")
    return TestClient(app), app.state.supabase, app


def approve(client, *, manager=None, treasurer=None):
    manager = manager or register(client, MANAGER)
    treasurer = treasurer or register(client, TREASURER)
    assert (
        verify(
            client, MANAGER, manager.sign(options(client, MANAGER).json()["options"])
        ).status_code
        == 200
    )
    return verify(client, TREASURER, treasurer.sign(options(client, TREASURER).json()["options"]))


def test_the_treasurers_signature_seals_the_dossier(engine) -> None:
    client, db, app = engine
    r = approve(client)
    assert r.status_code == 200 and r.json()["status"] == "sealed", r.text
    sealed = db.sealed["p_payload"]
    assert db.sealed["p_kid"] == sealed["kid"] == "local-test"
    assert sealed["sealed_at"].endswith("+03:00")
    assert [a["role"] for a in sealed["approvals"]] == ["manager", "treasurer"]


def test_a_sealed_payload_verifies_on_its_own(engine) -> None:
    """Everything a sponsor's verifier does, using only the payload and the published key."""
    client, db, app = engine
    approve(client)
    sealed, signature = db.sealed["p_payload"], b64d(db.sealed["p_signature"])

    # 1. The platform seal, against the published public key.
    published = client.get("/v1/keys", headers={"X-Internal-Key": KEY}).json()["keys"][0]
    assert published == public_jwk("local-test", app.state.signer.public_key_der())
    assert verify_digest(app.state.signer.public_key_der(), payload_digest(sealed), signature)

    # 2. Both passkey signatures, over the challenge rebuilt from the payload.
    c = payload.challenge(approval_payload_of(sealed))
    for a in sealed["approvals"]:
        client_data = json.loads(b64d(a["clientDataJSON"]))
        assert client_data["type"] == "webauthn.get"
        assert b64d(client_data["challenge"]) == c
        auth_data = b64d(a["authenticatorData"])
        assert auth_data[:32] == hashlib.sha256(b"localhost").digest()
        assert auth_data[32] & 0x04, "user verified"
        jwk = a["pubkey"]
        key = ec.EllipticCurvePublicNumbers(
            int.from_bytes(b64d(jwk["x"]), "big"),
            int.from_bytes(b64d(jwk["y"]), "big"),
            ec.SECP256R1(),
        ).public_key()
        key.verify(
            b64d(a["signature"]),
            auth_data + hashlib.sha256(b64d(a["clientDataJSON"])).digest(),
            ec.ECDSA(hashes.SHA256()),
        )


def test_changing_anything_breaks_the_seal(engine) -> None:
    client, db, app = engine
    approve(client)
    sealed = json.loads(json.dumps(db.sealed["p_payload"]))
    sealed["totals_cents"]["transport"] += 100
    assert not verify_digest(
        app.state.signer.public_key_der(), payload_digest(sealed), b64d(db.sealed["p_signature"])
    )


def approved_but_unsealed(client, db, app):
    signer, app.state.signer = app.state.signer, None
    r = approve(client)
    app.state.signer = signer
    return r


def test_without_a_signing_key_the_approval_stands_and_sealing_can_be_retried(engine) -> None:
    client, db, app = engine
    r = approved_but_unsealed(client, db, app)
    assert r.json()["status"] == "approved" and "isn't configured" in r.json()["seal_error"]
    assert db.sealed is None
    r = post(client, f"/v1/dossiers/{DOSSIER}/seal", {}, TREASURER)
    assert r.status_code == 200 and r.json()["status"] == "sealed" and db.status == "sealed"


def test_a_stored_passkey_signature_that_no_longer_verifies_is_never_sealed(engine) -> None:
    client, db, app = engine
    approved_but_unsealed(client, db, app)
    sig = bytearray(b64d(db.approvals[1]["signature"]))
    sig[-1] ^= 1
    db.approvals[1]["signature"] = base64.urlsafe_b64encode(bytes(sig)).decode().rstrip("=")
    r = post(client, f"/v1/dossiers/{DOSSIER}/seal", {}, MANAGER)
    assert (
        r.status_code == 422
        and "treasurer's passkey signature doesn't verify" in r.json()["detail"]["message"]
    )
    assert db.sealed is None


def test_rows_changed_after_signing_are_never_sealed(engine) -> None:
    client, db, app = engine
    approved_but_unsealed(client, db, app)
    db.content["items"][0]["amt_cents"] += 1  # something bypassed the freeze
    r = post(client, f"/v1/dossiers/{DOSSIER}/seal", {}, MANAGER)
    assert r.status_code == 422 and "different version" in r.json()["detail"]["message"]


@pytest.mark.parametrize(("actor", "status"), [(CAPTAIN, 403), (OUTSIDER, 404)])
def test_only_approvers_can_retry_sealing(engine, actor, status) -> None:
    client, db, app = engine
    approved_but_unsealed(client, db, app)
    assert post(client, f"/v1/dossiers/{DOSSIER}/seal", {}, actor).status_code == status


def test_drafts_cant_be_sealed(engine) -> None:
    client, _, _ = engine
    assert post(client, f"/v1/dossiers/{DOSSIER}/seal", {}, MANAGER).status_code == 409


def test_keys_endpoint_needs_the_internal_key_and_is_empty_without_a_signer(engine) -> None:
    client, _, app = engine
    assert client.get("/v1/keys").status_code == 401
    app.state.signer = None
    assert client.get("/v1/keys", headers={"X-Internal-Key": KEY}).json() == {"keys": []}


def test_sealed_vector_verifies_and_rebuilds_the_approval_challenge() -> None:
    vectors = json.loads(
        (Path(__file__).resolve().parents[3] / "spec" / "test-vectors.json").read_text("utf-8")
    )
    s = vectors["sealed"]
    spki = b64d(vectors["signature"]["public_key_spki"])
    assert verify_digest(spki, payload_digest(s["payload"]), b64d(s["signature_der"]))
    assert approval_payload_of(s["payload"]) == vectors["approval"]["payload"]


def test_retrying_a_seal_reads_the_dossier_once(engine, monkeypatch) -> None:
    client, db, app = engine
    approved_but_unsealed(client, db, app)
    calls: list[str] = []
    for name in ("approval_snapshot", "seal_snapshot"):
        original = getattr(db, name)
        monkeypatch.setattr(db, name, lambda d, _n=name, _o=original: (calls.append(_n), _o(d))[1])
    r = post(client, f"/v1/dossiers/{DOSSIER}/seal", {}, MANAGER)
    assert r.status_code == 200 and calls == ["seal_snapshot"]


RETIRED = {
    "kid": "local-2025",
    "kty": "EC",
    "crv": "P-256",
    "alg": "ES256",
    "x": "lBrrd5OhO4FnMb-IpR3vLlzIbrAPSSChTY0rZ5crRao",
    "y": "DIPcJLcKDNsqxPd3D7W7CuKlXaECulw-sErvxip27_Y",
}


def test_retired_keys_stay_published_after_the_current_key(monkeypatch) -> None:
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    stale_current = RETIRED | {"kid": "local-test"}
    monkeypatch.setenv("RETIRED_PUBLIC_KEYS", json.dumps([RETIRED, stale_current]))
    app = create_app()
    app.state.signer = LocalSigner.generate("local-test")
    keys = TestClient(app).get("/v1/keys", headers={"X-Internal-Key": KEY}).json()["keys"]
    current = public_jwk("local-test", app.state.signer.public_key_der())
    assert keys == [current, RETIRED]  # the live key wins over a retired entry with its kid


@pytest.mark.parametrize(
    "value",
    [
        '{"kid": "x"}',
        json.dumps([RETIRED | {"crv": "P-384"}]),
        json.dumps([RETIRED | {"x": "short"}]),
        json.dumps([{k: v for k, v in RETIRED.items() if k != "kid"}]),
        json.dumps([RETIRED, RETIRED]),
        "not json",
    ],
)
def test_a_malformed_retired_key_stops_the_engine_starting(value) -> None:
    with pytest.raises(ValueError):
        parse_retired_keys(value)
