"""Draft dossiers: building rows from a statement + tags, and POST /v1/clubs/{club}/dossiers."""

from __future__ import annotations

import base64
import dataclasses
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.dossiers import Tag, TagError, build_items
from app.ingest.parse import parse_statement
from app.main import create_app
from app.roster.keys import club_key, pepper_from_env
from app.roster.match import find_batches, match_rows
from app.supabase import SupabaseError
from tests.fakes.statement import PASSWORD, build_statement, lionesses_month
from tests.test_matching import (
    CLUB,
    KEY,
    MANAGER,
    PEPPER_B64,
    TREASURER,
    FakeSupabase,
    players_for,
    post_roster,
    roster_players,
)

FIXTURE = "MD4-2026-10-17"


@pytest.fixture(scope="module")
def setup():
    parsed = parse_statement(build_statement(lionesses_month()), PASSWORD)
    players, key = players_for(CLUB, roster_players())
    matches = match_rows(parsed.rows, players, key)
    batches = find_batches(parsed.rows, matches, {date(2026, 10, 17): FIXTURE})
    return parsed, matches, batches, key


def fares(parsed):
    return [r for r in parsed.rows if r.amount_cents == 25000]


def build(setup, tags):
    parsed, matches, batches, key = setup
    return build_items(parsed.rows, tags, matches, batches, {FIXTURE}, key)


# ---- building rows ------------------------------------------------------------------------


def test_matchday_fares_become_squad_rows_with_player_codes_and_fees(setup) -> None:
    parsed = setup[0]
    items = build(setup, [Tag(r.tx, "transport") for r in fares(parsed)])
    assert len(items) == 18
    assert {(i["branch"], i["cp_type"], i["amt_cents"], i["fee_cents"]) for i in items} == {
        ("B", "player", 25000, 700)
    }
    assert sorted(i["cp_ref"] for i in items) == [f"P{n:02d}" for n in range(1, 19)]
    assert {i["fixture_code"] for i in items} == {FIXTURE}  # filled in from the batch


def test_merchant_and_income_rows(setup) -> None:
    items = {
        i["tx"]: i for i in build(setup, [Tag("SJD0000001", "meals"), Tag("SJA0000003", "income")])
    }
    till, gift = items["SJD0000001"], items["SJA0000003"]
    assert (till["branch"], till["cp_type"], till["cp_ref"]) == ("A", "till", "5123456")
    assert (gift["branch"], gift["dir"], gift["category"]) == ("I", "in", "income")
    assert gift["cp_ref"].startswith("hmac:") and len(gift["cp_ref"]) == 5 + 64


def test_rows_never_carry_names(setup) -> None:
    parsed = setup[0]
    tagged = [
        Tag(r.tx, "income" if r.direction == "in" else "other") for r in parsed.rows if not r.fee_of
    ]
    blob = json.dumps(build(setup, tagged))
    for r in parsed.rows:
        if r.counterparty.name:
            assert r.counterparty.name not in blob
    assert "***" not in blob  # no masked numbers either


def test_each_row_gets_its_own_salt(setup) -> None:
    items = build(setup, [Tag(r.tx, "transport") for r in fares(setup[0])])
    assert len({i["salt"] for i in items}) == len(items)
    assert all(len(i["salt"]) >= 16 for i in items)


@pytest.mark.parametrize(
    ("tags", "problem"),
    [
        ([Tag("SZZ9999999", "transport")], "not in this statement"),
        ([Tag("SJD0000001", "meals"), Tag("SJD0000001", "kit")], "tagged twice"),
        ([Tag("SJC0000000", "transport")], "a fee, already counted"),
        ([Tag("SJD0000001", "groceries")], "unknown category"),
        ([Tag("SJD0000001", "income")], "money out can't be tagged 'income'"),
        ([Tag("SJA0000003", "transport")], "money in can't be tagged 'transport'"),
        ([Tag("SJD0000001", "meals", "MD9-NOPE")], "unknown fixture"),
        ([], "tag at least one club transaction"),
    ],
)
def test_bad_tags_are_explained_by_receipt_number(setup, tags, problem) -> None:
    with pytest.raises(TagError) as err:
        build(setup, tags)
    assert any(problem in p for p in err.value.problems)


def test_rows_without_an_amount_are_refused_before_the_database(setup) -> None:
    parsed, matches, batches, key = setup
    rows = [
        dataclasses.replace(r, paid_in_cents=0, withdrawn_cents=0) if r.tx == "SJD0000001" else r
        for r in parsed.rows
    ]
    with pytest.raises(TagError) as err:
        build_items(rows, [Tag("SJD0000001", "meals")], matches, batches, {FIXTURE}, key)
    assert err.value.problems == ["SJD0000001: no amount on this row"]


def test_a_transfer_that_shares_its_receipt_with_its_charge_can_be_tagged() -> None:
    # Real statements print the transfer and its charge under one receipt number, in either order.
    for reverse in (False, True):
        month = lionesses_month()
        parents = {t.ts: t.tx for t in month if "Charge" not in t.details}
        shared = [
            dataclasses.replace(t, tx=parents[t.ts]) if "Charge" in t.details else t for t in month
        ]
        parsed = parse_statement(build_statement(shared), PASSWORD)
        rows = list(reversed(parsed.rows)) if reverse else parsed.rows
        fare = next(r for r in rows if r.amount_cents == 25000 and r.kind.value != "charge")
        items = build_items(rows, [Tag(fare.tx, "transport")], {}, [], set(), b"k" * 32)
        assert (items[0]["amt_cents"], items[0]["fee_cents"]) == (25000, 700)


# ---- endpoint -----------------------------------------------------------------------------


class DraftSupabase(FakeSupabase):
    def __init__(self) -> None:
        super().__init__()
        self.created: list[dict] = []
        self.fail_with: str | None = None

    def create_draft_dossier(self, params):
        if self.fail_with:
            raise SupabaseError(
                "this statement is already in a submitted dossier", 409, self.fail_with
            )
        self.created.append(params)
        return {"dossier_id": "20000000-0000-4000-8000-000000000099", "replaced_draft": False}


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    monkeypatch.setenv("ROSTER_PEPPER", PEPPER_B64)
    app = create_app()
    app.state.supabase = DraftSupabase()
    client = TestClient(app)
    post_roster(client, MANAGER, roster_players())
    return client, app.state.supabase


@pytest.fixture(scope="module")
def pdf_b64():
    return base64.b64encode(build_statement(lionesses_month())).decode()


def post_draft(client, body, actor=MANAGER, password=PASSWORD):
    return client.post(
        f"/v1/clubs/{CLUB}/dossiers",
        json={"acknowledged_checks": ["producer_baseline"], **body},
        headers={"X-Internal-Key": KEY, "X-Actor-Id": actor, "X-Statement-Password": password},
    )


def fare_tags(setup):
    return [{"tx": r.tx, "category": "transport"} for r in fares(setup[0])]


def test_manager_saves_a_draft_built_from_the_statement(engine, pdf_b64, setup) -> None:
    client, db = engine
    tags = [*fare_tags(setup), {"tx": "SJD0000001", "category": "meals"}]
    r = post_draft(client, {"statement_pdf": pdf_b64, "tags": tags})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["items"] == 19 and data["integrity_score_bp"] == 9500
    assert data["spent_cents"] == 18 * (25000 + 700) + 180000
    params = db.created[0]
    assert params["p_actor"] == MANAGER and params["p_club"] == CLUB
    assert params["p_rows_total"] == 47 and len(params["p_source_sha256"]) == 64
    assert (params["p_period_from"], params["p_period_to"]) == ("2026-10-01", "2026-10-31")
    assert "SJD0000005" not in {i["tx"] for i in params["p_items"]}  # untagged airtime: personal


def test_amounts_cannot_be_sent_by_the_browser(engine, pdf_b64) -> None:
    client, db = engine
    tags = [{"tx": "SJD0000001", "category": "meals", "amt_cents": 1}]
    assert post_draft(client, {"statement_pdf": pdf_b64, "tags": tags}).status_code == 422
    assert db.created == []


def test_bad_tags_return_the_problems(engine, pdf_b64) -> None:
    client, _ = engine
    r = post_draft(
        client, {"statement_pdf": pdf_b64, "tags": [{"tx": "SZZ9999999", "category": "kit"}]}
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "bad_tags"


def test_only_the_manager_saves_drafts(engine, pdf_b64, setup) -> None:
    client, db = engine
    r = post_draft(client, {"statement_pdf": pdf_b64, "tags": fare_tags(setup)}, actor=TREASURER)
    assert r.status_code == 403 and db.created == []


def test_wrong_password_and_bad_base64(engine, pdf_b64, setup) -> None:
    client, _ = engine
    tags = fare_tags(setup)
    wrong = "000000"  # noqa: S105 - deliberately wrong synthetic password
    assert (
        post_draft(client, {"statement_pdf": pdf_b64, "tags": tags}, password=wrong).status_code
        == 422
    )
    assert post_draft(client, {"statement_pdf": "not base64!", "tags": tags}).status_code == 400


def test_database_refusals_keep_their_meaning(engine, pdf_b64, setup) -> None:
    client, db = engine
    db.fail_with = "23505"  # create_draft_dossier: statement already in a submitted dossier
    r = post_draft(client, {"statement_pdf": pdf_b64, "tags": fare_tags(setup)})
    assert r.status_code == 409
    assert "already in a submitted dossier" in r.json()["detail"]["message"]


def test_pepper_from_env_matches_the_test_setup() -> None:
    assert club_key(pepper_from_env(PEPPER_B64), CLUB) == players_for(CLUB, [])[1]
