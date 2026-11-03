"""Roster keys, matching and club endpoints. Synthetic data only; Supabase is faked in memory."""

from __future__ import annotations

import base64
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ingest.parse import parse_statement
from app.main import create_app
from app.roster.keys import (
    InvalidPhone,
    club_key,
    mask_key,
    masked_parts,
    normalise_phone,
    pepper_from_env,
    phone_key,
)
from app.roster.match import MatchStatus, Player, find_batches, match_rows
from tests.fakes.statement import PASSWORD, build_statement, lionesses_month

KEY = "test-key-that-is-long-enough-for-the-engine-1234"
PEPPER_B64 = base64.b64encode(bytes(range(32))).decode()
CLUB = "10000000-0000-4000-8000-000000000001"
OTHER_CLUB = "10000000-0000-4000-8000-000000000002"
MANAGER = "00000000-0000-4000-8000-00000000000a"
TREASURER = "00000000-0000-4000-8000-00000000000b"
CAPTAIN = "00000000-0000-4000-8000-00000000000c"
OUTSIDER = "00000000-0000-4000-8000-00000000000d"

# The synthetic statement's 18 players are masked as 0700***000 .. 0700***017. Real-format
# numbers are built here from parts, so this file contains no literal phone numbers.
PLAYER_NAMES = [
    "MERCY ATIENO",
    "Faith Wambui",
    "JOY NJERI",
    "Brenda Chebet",
    "SHARON OTIENO",
    "Lucy Muthoni",
    "DIANA KERUBO",
    "Ann Wairimu",
    "VIVIAN ACHIENG",
    "Esther Nyambura",
    "PURITY JEPKOECH",
    "Ruth Mumbua",
    "IVY ODHIAMBO",
    "Linda Wanjiru",
    "CYNTHIA MORAA",
    "Maureen Auma",
    "NANCY WAIRIMU",
    "Agnes Nduta",
]


def phone(middle: str, suffix: int) -> str:
    return "07" + "00" + middle + f"{suffix:03d}"


def roster_players(**overrides) -> list[dict]:
    players = [
        {
            "full_name": n.title(),
            "phone": phone("555", i),
            "consent_by": "player",
            "consent_at": "2026-09-01T10:00:00+03:00",
        }
        for i, n in enumerate(PLAYER_NAMES)
    ]
    for i, name in overrides.items():
        players[int(i[1:])]["full_name"] = name
    return players


# ---- keys ---------------------------------------------------------------------------------


# A sample number assembled from parts, so this file holds no literal phone number.
SAMPLE = "7" + "12" + "345" + "678"
FORMATS = [
    "0" + SAMPLE[:3] + " " + SAMPLE[3:6] + " " + SAMPLE[6:],
    "0" + SAMPLE[:3] + "-" + SAMPLE[3:6] + "-" + SAMPLE[6:],
    "254" + SAMPLE,
    "+254 " + SAMPLE[:3] + " " + SAMPLE[3:6] + " " + SAMPLE[6:],
    SAMPLE,
]


@pytest.mark.parametrize("raw", FORMATS)
def test_phone_formats_normalise_to_e164(raw: str) -> None:
    assert normalise_phone(raw) == "+254" + SAMPLE


@pytest.mark.parametrize("raw", ["", "12345", "0812345678", "+255712345678", "07123456789"])
def test_non_kenyan_mobiles_are_rejected(raw: str) -> None:
    with pytest.raises(InvalidPhone):
        normalise_phone(raw)


def test_masked_parts_match_what_statements_show() -> None:
    assert masked_parts("+254" + SAMPLE) == ("0712", "678")


def test_keys_differ_per_club_and_per_purpose() -> None:
    pepper = pepper_from_env(PEPPER_B64)
    a, b = club_key(pepper, CLUB), club_key(pepper, OTHER_CLUB)
    e164 = normalise_phone(phone("555", 1))
    assert phone_key(a, e164) != phone_key(b, e164)  # can't be compared across clubs
    assert phone_key(a, e164) != mask_key(a, *masked_parts(e164))  # domain-separated
    assert len(phone_key(a, e164)) == 64


def test_pepper_must_be_32_bytes() -> None:
    with pytest.raises(ValueError):
        pepper_from_env(base64.b64encode(b"short").decode())


# ---- matching -----------------------------------------------------------------------------


@pytest.fixture(scope="module")
def parsed():
    return parse_statement(build_statement(lionesses_month()), PASSWORD)


def players_for(club: str, entries: list[dict]) -> tuple[list[Player], bytes]:
    key = club_key(pepper_from_env(PEPPER_B64), club)
    out = []
    for i, e in enumerate(entries, start=1):
        e164 = normalise_phone(e["phone"])
        out.append(Player(f"P{i:02d}", e["full_name"], mask_key(key, *masked_parts(e164))))
    return out, key


def test_all_eighteen_fares_are_verified(parsed) -> None:
    players, key = players_for(CLUB, roster_players())
    matches = match_rows(parsed.rows, players, key)
    verified = [m for m in matches.values() if m.status is MatchStatus.VERIFIED]
    assert len(verified) == 18
    assert {m.player_code for m in verified} == {f"P{i:02d}" for i in range(1, 19)}


def test_parent_registered_line_is_number_only(parsed) -> None:
    players, key = players_for(CLUB, roster_players(p03="Brenda Chebet's mother"))
    players[3] = Player("P04", "Rose Mama", players[3].mask_key)  # line registered to a parent
    matches = match_rows(parsed.rows, players, key)
    by_code = {m.player_code: m.status for m in matches.values() if m.player_code}
    assert by_code["P04"] is MatchStatus.NUMBER_ONLY


def test_shared_masked_number_is_ambiguous_unless_the_name_decides(parsed) -> None:
    entries = roster_players()
    # A second player whose number differs only in the hidden middle digits of player 5's.
    entries.append({**entries[5], "full_name": "Somebody Else", "phone": phone("999", 5)})
    players, key = players_for(CLUB, entries)
    m = match_rows(parsed.rows, players, key)
    lucy = next(t for t, x in m.items() if x.player_code == "P06")
    assert m[lucy].status is MatchStatus.VERIFIED  # the statement's name picks Lucy
    players[5] = Player("P06", "Grace Owino", players[5].mask_key)  # no shared name token
    m = match_rows(parsed.rows, players, key)
    assert m[lucy].status is MatchStatus.AMBIGUOUS


def test_people_not_on_the_roster_are_unmatched(parsed) -> None:
    players, key = players_for(CLUB, roster_players())
    matches = match_rows(parsed.rows, players, key)
    assert matches["SJD0000008"].status is MatchStatus.UNMATCHED  # Synthetic Captain
    assert "SJD0000005" not in matches  # airtime has no counterparty


def test_keys_from_another_club_never_match(parsed) -> None:
    players, _ = players_for(CLUB, roster_players())
    other_key = club_key(pepper_from_env(PEPPER_B64), OTHER_CLUB)
    matches = match_rows(parsed.rows, players, other_key)
    assert all(m.status is MatchStatus.UNMATCHED for m in matches.values())


def test_matchday_batch_is_found_and_linked_to_the_fixture(parsed) -> None:
    players, key = players_for(CLUB, roster_players())
    matches = match_rows(parsed.rows, players, key)
    batches = find_batches(parsed.rows, matches, {date(2026, 10, 17): "MD4-2026-10-17"})
    assert len(batches) == 1
    b = batches[0]
    assert (b.day, b.amount_cents, b.size, b.verified, b.fixture_code) == (
        date(2026, 10, 17),
        25000,
        18,
        18,
        "MD4-2026-10-17",
    )


# ---- endpoints ----------------------------------------------------------------------------


class FakeSupabase:
    def __init__(self) -> None:
        self.roles = {
            (CLUB, MANAGER): "manager",
            (CLUB, TREASURER): "treasurer",
            (CLUB, CAPTAIN): "captain",
            (OTHER_CLUB, OUTSIDER): "manager",
        }
        self.roster_rows: list[dict] = []
        self.fixture_rows = [
            {"fixture_code": "MD4-2026-10-17", "match_date": "2026-10-17", "club_id": CLUB}
        ]

    def role_of(self, club_id, user_id):
        return self.roles.get((club_id, user_id))

    def roster(self, club_id):
        return [r for r in self.roster_rows if r["club_id"] == club_id]

    def fixtures(self, club_id):
        return [f for f in self.fixture_rows if f["club_id"] == club_id]

    def upsert_roster(self, rows):
        for row in rows:
            self.roster_rows = [
                r
                for r in self.roster_rows
                if (r["club_id"], r["phone_key"]) != (row["club_id"], row["phone_key"])
            ]
            self.roster_rows.append(row)


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    monkeypatch.setenv("ROSTER_PEPPER", PEPPER_B64)
    app = create_app()
    app.state.supabase = FakeSupabase()
    return TestClient(app), app.state.supabase


def post_roster(client, actor, players, club=CLUB):
    return client.post(
        f"/v1/clubs/{club}/roster",
        json={"players": players},
        headers={"X-Internal-Key": KEY, "X-Actor-Id": actor},
    )


def test_manager_imports_roster_without_storing_numbers(engine) -> None:
    client, db = engine
    players = roster_players()
    players.append({**players[0], "full_name": "Bad Number", "phone": "12345"})
    r = post_roster(client, MANAGER, players)
    assert r.status_code == 200
    assert r.json() == {
        "added": 18,
        "updated": 0,
        "rejected": [{"row": 19, "reason": r.json()["rejected"][0]["reason"]}],
    }
    assert "12345" not in r.text  # the bad number isn't echoed back
    assert [row["player_code"] for row in db.roster_rows] == [f"P{i:02d}" for i in range(1, 19)]
    stored = " ".join(str(v) for row in db.roster_rows for v in row.values())
    for p in roster_players():
        assert normalise_phone(p["phone"])[4:] not in stored  # no raw numbers in any column


def test_reimport_keeps_player_codes(engine) -> None:
    client, db = engine
    post_roster(client, MANAGER, roster_players())
    r = post_roster(client, TREASURER, roster_players()[::-1])
    assert r.json()["updated"] == 18 and r.json()["added"] == 0
    assert sorted(row["player_code"] for row in db.roster_rows) == [
        f"P{i:02d}" for i in range(1, 19)
    ]


def test_duplicate_numbers_in_one_upload_are_rejected(engine) -> None:
    client, _ = engine
    players = roster_players()[:2]
    players.append({**players[0], "full_name": "Twin"})
    assert post_roster(client, MANAGER, players).json()["rejected"][0]["row"] == 3


@pytest.mark.parametrize(
    ("actor", "club", "status"),
    [
        (CAPTAIN, CLUB, 403),  # captains can't see or change player data
        (OUTSIDER, CLUB, 403),  # manager of another club
        (MANAGER, OTHER_CLUB, 403),  # right person, wrong club
        ("not-a-uuid", CLUB, 400),
        ("", CLUB, 400),
    ],
)
def test_roster_import_requires_an_official_of_that_club(engine, actor, club, status) -> None:
    client, db = engine
    assert post_roster(client, actor, roster_players(), club).status_code == status
    assert db.roster_rows == []


def test_club_parse_returns_matches_and_batches(engine) -> None:
    client, _ = engine
    post_roster(client, MANAGER, roster_players())
    r = client.post(
        f"/v1/clubs/{CLUB}/statements/parse",
        content=build_statement(lionesses_month()),
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": MANAGER,
            "X-Statement-Password": PASSWORD,
            "Content-Type": "application/pdf",
        },
    )
    assert r.status_code == 200
    data = r.json()
    fares = [t for t in data["transactions"] if t["amount_cents"] == 25000]
    assert {t["match"]["status"] for t in fares} == {"verified"}
    assert data["roster_size"] == 18
    assert data["batches"] == [
        {
            "day": "2026-10-17",
            "amount_cents": 25000,
            "size": 18,
            "verified": 18,
            "fixture_code": "MD4-2026-10-17",
            "txs": data["batches"][0]["txs"],
        }
    ]


def test_only_the_manager_uploads_statements(engine) -> None:
    client, _ = engine
    r = client.post(
        f"/v1/clubs/{CLUB}/statements/parse",
        content=b"%PDF-1.4",
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": TREASURER,
            "X-Statement-Password": PASSWORD,
            "Content-Type": "application/pdf",
        },
    )
    assert r.status_code == 403


def test_endpoints_refuse_when_database_settings_are_missing(monkeypatch) -> None:
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    client = TestClient(create_app())
    assert post_roster(client, MANAGER, roster_players()).status_code == 503
