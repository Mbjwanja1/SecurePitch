"""Statement upload limits: the limiter itself, then both upload endpoints."""

from __future__ import annotations

import base64

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.ratelimit import (
    UPLOADS_PER_CLUB,
    UPLOADS_PER_USER,
    WRONG_PASSWORDS_PER_USER,
    UploadLimiter,
)
from tests.fakes.statement import PASSWORD, build_statement, lionesses_month
from tests.test_dossiers import DraftSupabase
from tests.test_matching import CLUB, KEY, MANAGER, PEPPER_B64, TREASURER

USER_LIMIT, USER_WINDOW = UPLOADS_PER_USER
CLUB_LIMIT, CLUB_WINDOW = UPLOADS_PER_CLUB
WRONG_LIMIT, WRONG_WINDOW = WRONG_PASSWORDS_PER_USER
WRONG_GUESS = "not-it"


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def limiter(clock):
    return UploadLimiter(now=clock)


# The limiter ------------------------------------------------------------------------------------


def test_uploads_are_allowed_up_to_the_limit(limiter) -> None:
    assert all(limiter.admit("u", "c") is None for _ in range(USER_LIMIT))
    refusal = limiter.admit("u", "c")
    assert refusal is not None and "Too many statement uploads" in refusal.message


def test_the_window_slides(limiter, clock) -> None:
    for _ in range(USER_LIMIT):
        limiter.admit("u", "c")
    refusal = limiter.admit("u", "c")
    assert refusal.retry_after == USER_WINDOW
    clock.t += USER_WINDOW - 1
    assert limiter.admit("u", "c") is not None  # one second too early
    clock.t += 1
    assert limiter.admit("u", "c") is None


def test_a_refused_upload_doesnt_extend_the_wait(limiter, clock) -> None:
    for _ in range(USER_LIMIT):
        limiter.admit("u", "c")
    for _ in range(50):
        limiter.admit("u", "c")
    clock.t += USER_WINDOW
    assert limiter.admit("u", "c") is None


def test_users_dont_share_an_allowance(limiter) -> None:
    for _ in range(USER_LIMIT):
        limiter.admit("u1", "c")
    assert limiter.admit("u1", "c") is not None
    assert limiter.admit("u2", "c") is None


def test_the_club_has_its_own_limit_across_its_users(limiter) -> None:
    for i in range(CLUB_LIMIT):
        assert limiter.admit(f"user-{i}", "c") is None
    refusal = limiter.admit("someone-new", "c")
    assert refusal is not None and refusal.retry_after == CLUB_WINDOW
    assert limiter.admit("someone-new", "another-club") is None


def test_wrong_passwords_lock_sooner_and_say_why(limiter, clock) -> None:
    for _ in range(WRONG_LIMIT):
        assert limiter.admit("u", "c") is None
        limiter.wrong_password("u")
    refusal = limiter.admit("u", "c")
    assert "wrong statement passwords" in refusal.message
    clock.t += WRONG_WINDOW
    assert limiter.admit("u", "c") is None


def test_a_wrong_password_lock_applies_across_clubs(limiter) -> None:
    for _ in range(WRONG_LIMIT):
        limiter.wrong_password("u")
    assert limiter.admit("u", "club-a") is not None
    assert limiter.admit("u", "club-b") is not None


def test_refused_uploads_arent_counted_against_the_club(limiter) -> None:
    for _ in range(WRONG_LIMIT):
        limiter.wrong_password("locked")
    for _ in range(CLUB_LIMIT * 2):
        limiter.admit("locked", "c")
    assert limiter.admit("other", "c") is None


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (30, "about a minute"),
        (60, "about a minute"),
        (61, "about 2 minutes"),
        (600, "about 10 minutes"),
    ],
)
def test_the_wait_is_in_plain_words(limiter, clock, seconds, text) -> None:
    for _ in range(USER_LIMIT):
        limiter.admit("u", "c")
    clock.t += USER_WINDOW - seconds
    assert text in limiter.admit("u", "c").message


def test_old_keys_dont_pile_up(limiter, clock) -> None:
    for i in range(1200):
        limiter.admit(f"u{i}", f"c{i}")
    clock.t += CLUB_WINDOW + 1
    limiter.admit("fresh", "fresh")
    limiter.admit("fresh2", "fresh2")
    assert len(limiter._hits) < 10


# The endpoints ----------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def pdf():
    return build_statement(lionesses_month())


@pytest.fixture
def engine(monkeypatch, limiter):
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    monkeypatch.setenv("ROSTER_PEPPER", PEPPER_B64)
    app = create_app()
    app.state.supabase = DraftSupabase()
    app.state.upload_limiter = limiter
    return TestClient(app), limiter


def parse(client, pdf, actor=MANAGER, password=PASSWORD):
    return client.post(
        f"/v1/clubs/{CLUB}/statements/parse",
        content=pdf,
        headers={
            "X-Internal-Key": KEY,
            "X-Actor-Id": actor,
            "X-Statement-Password": password,
            "Content-Type": "application/pdf",
        },
    )


def draft(client, pdf, actor=MANAGER, password=PASSWORD):
    return client.post(
        f"/v1/clubs/{CLUB}/dossiers",
        json={
            "statement_pdf": base64.b64encode(pdf).decode(),
            "tags": [{"tx": "SJB0000000", "category": "transport"}],
        },
        headers={"X-Internal-Key": KEY, "X-Actor-Id": actor, "X-Statement-Password": password},
    )


def use_up(limiter, user=MANAGER, club=CLUB) -> None:
    for _ in range(USER_LIMIT):
        limiter.admit(user, club)


def test_parse_is_refused_with_429_and_retry_after(engine, pdf) -> None:
    client, limiter = engine
    use_up(limiter)
    r = parse(client, pdf)
    assert r.status_code == 429
    assert r.json()["detail"]["code"] == "rate_limited"
    assert "Try again in about 10 minutes" in r.json()["detail"]["message"]
    assert r.headers["retry-after"] == str(USER_WINDOW)


def test_saving_a_draft_is_limited_too(engine, pdf) -> None:
    client, limiter = engine
    use_up(limiter)
    assert draft(client, pdf).status_code == 429


def test_a_refused_upload_is_never_parsed(engine, monkeypatch) -> None:
    client, limiter = engine
    use_up(limiter)

    def must_not_run(*args):
        raise AssertionError("parsed a refused upload")

    monkeypatch.setattr("app.routers.clubs.parse_statement", must_not_run)
    assert parse(client, b"%PDF-1.4").status_code == 429


def test_a_good_upload_counts_once(engine, pdf) -> None:
    client, limiter = engine
    assert parse(client, pdf).status_code == 200
    assert len(limiter._hits[f"user:{MANAGER}"]) == 1
    assert f"wrong:{MANAGER}" not in limiter._hits


def test_wrong_passwords_lock_the_user(engine, pdf) -> None:
    client, _ = engine
    for _ in range(WRONG_LIMIT):
        r = parse(client, pdf, password=WRONG_GUESS)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "wrong_password"
    r = parse(client, pdf)  # even the right password has to wait
    assert r.status_code == 429 and "wrong statement passwords" in r.json()["detail"]["message"]


def test_a_wrong_password_on_save_counts(engine, pdf) -> None:
    client, limiter = engine
    assert draft(client, pdf, password=WRONG_GUESS).status_code == 422
    assert len(limiter._hits[f"wrong:{MANAGER}"]) == 1


def test_a_corrupt_file_isnt_counted_as_a_wrong_password(engine) -> None:
    client, limiter = engine
    r = parse(client, b"this is not a pdf")
    assert r.status_code != 200
    assert f"wrong:{MANAGER}" not in limiter._hits


def test_people_without_the_role_use_up_nothing(engine, pdf) -> None:
    client, limiter = engine
    assert parse(client, pdf, actor=TREASURER).status_code == 403
    assert limiter._hits == {}
