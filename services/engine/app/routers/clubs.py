"""Club-scoped endpoints: roster import, and statement parsing with roster matching.

The web app's route handler sends X-Actor-Id: the signed-in user's ID from their session, never
from the request body (ADR 0002 rule 7). The engine checks that user's role in the club before
doing anything (rule 5), because its secret key bypasses row-level security.
"""

from __future__ import annotations

import base64
import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, ConfigDict, Field

from app.config import MAX_STATEMENT_BYTES
from app.dossiers import Tag, TagError, build_items
from app.ingest.integrity import failed_checks
from app.ingest.models import ParsedStatement
from app.ingest.parse import StatementError, parse_statement
from app.ratelimit import UploadLimiter
from app.roster.keys import (
    InvalidPhone,
    club_key,
    mask_key,
    masked_parts,
    normalise_phone,
    pepper_from_env,
    phone_key,
)
from app.roster.match import Player, find_batches, match_rows
from app.routers.statements import _ERROR_STATUS, _statement_json
from app.security import require_internal_key
from app.supabase import Supabase, SupabaseError

router = APIRouter(prefix="/v1/clubs/{club_id}", dependencies=[Depends(require_internal_key)])

UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
OFFICIALS = {"manager", "treasurer"}


class PlayerIn(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    phone: str = Field(max_length=32)
    fkf_id: str | None = Field(default=None, max_length=40)
    is_minor: bool = False
    consent_by: str = Field(min_length=2, max_length=120)  # the player, or a parent for minors
    consent_at: datetime


class RosterIn(BaseModel):
    players: list[PlayerIn] = Field(min_length=1, max_length=200)


def _deps(request: Request) -> tuple[Supabase, bytes]:
    s = request.app.state.settings
    db: Supabase | None = getattr(request.app.state, "supabase", None)
    if db is None or not s.roster_pepper:
        raise HTTPException(
            503, {"code": "not_configured", "message": "Engine database settings are missing"}
        )
    try:
        pepper = pepper_from_env(s.roster_pepper)
    except ValueError:  # includes binascii.Error; never echo the setting itself
        raise HTTPException(
            503, {"code": "not_configured", "message": "ROSTER_PEPPER isn't 32 bytes of base64"}
        ) from None
    return db, pepper


async def _require_role(db: Supabase, club_id: str, actor: str, allowed: set[str]) -> str:
    if not UUID_RE.match(club_id) or not UUID_RE.match(actor or ""):
        raise HTTPException(400, {"code": "bad_id", "message": "Club and actor IDs must be UUIDs"})
    role = await run_in_threadpool(db.role_of, club_id, actor)
    if role not in allowed:
        raise HTTPException(
            403, {"code": "forbidden", "message": "You don't have the right role in this club"}
        )
    return role


def _admit_upload(request: Request, club_id: str, actor: str) -> UploadLimiter:
    """Count this upload or refuse it. After the role check, and before any parsing."""
    limiter: UploadLimiter | None = getattr(request.app.state, "upload_limiter", None)
    if limiter is None:  # fail closed: a missing limiter must never mean "no limit"
        raise HTTPException(
            503, {"code": "not_configured", "message": "Uploads aren't available right now"}
        )
    refusal = limiter.admit(actor, club_id)
    if refusal is not None:
        raise HTTPException(
            429,
            {"code": "rate_limited", "message": refusal.message},
            headers={"Retry-After": str(refusal.retry_after)},
        )
    return limiter


@router.post("/roster")
async def import_roster(
    club_id: str, body: RosterIn, request: Request, x_actor_id: str = Header(default="")
) -> dict[str, Any]:
    db, pepper = _deps(request)
    await _require_role(db, club_id, x_actor_id, OFFICIALS)
    key = club_key(pepper, club_id)

    existing = {
        r["phone_key"]: r["player_code"] for r in await run_in_threadpool(db.roster, club_id)
    }
    used = {int(code[1:]) for code in existing.values()}
    next_code = max(used, default=0) + 1

    rows, rejected, seen = [], [], set()
    for i, p in enumerate(body.players, start=1):
        try:
            e164 = normalise_phone(p.phone)
        except InvalidPhone as exc:
            rejected.append({"row": i, "reason": str(exc)})  # never echo the number itself
            continue
        pk = phone_key(key, e164)
        if pk in seen:
            rejected.append({"row": i, "reason": "same phone number as an earlier row"})
            continue
        seen.add(pk)
        code = existing.get(pk)
        if code is None:
            code, next_code = f"P{next_code:02d}", next_code + 1
        rows.append(
            {
                "club_id": club_id,
                "player_code": code,
                "full_name": p.full_name.strip(),
                "fkf_id": (p.fkf_id or "").strip() or None,
                "phone_key": pk,
                "mask_key": mask_key(key, *masked_parts(e164)),
                "is_minor": p.is_minor,
                "consent_by": p.consent_by.strip(),
                "consent_at": p.consent_at.isoformat(),
                "active": True,
            }
        )
    if rows:
        await run_in_threadpool(db.upsert_roster, rows)
    return {
        "added": sum(r["phone_key"] not in existing for r in rows),
        "updated": sum(r["phone_key"] in existing for r in rows),
        "rejected": rejected,
    }


@router.post("/statements/parse")
async def parse_for_club(
    club_id: str,
    request: Request,
    x_actor_id: str = Header(default=""),
    x_statement_password: str = Header(default=""),
) -> dict[str, Any]:
    db, pepper = _deps(request)
    await _require_role(db, club_id, x_actor_id, {"manager"})
    limiter = _admit_upload(request, club_id, x_actor_id)
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
        raise HTTPException(415, "Send the PDF as application/pdf")
    body = await request.body()
    if not body:
        raise HTTPException(400, "The request body is empty")
    if len(body) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": "Statements are limited to 5 MB"})
    try:
        parsed, players, fixtures, matches, batches = await _parse_and_match(
            db, pepper, club_id, body, x_statement_password, limiter, x_actor_id
        )
    finally:
        del body

    result = _statement_json(parsed)
    for t in result["transactions"]:
        m = matches.get(t["tx"])
        t["match"] = {"status": m.status.value, "player_code": m.player_code} if m else None
    result["roster_size"] = len(players)
    result["batches"] = [
        {
            "day": b.day.isoformat(),
            "amount_cents": b.amount_cents,
            "size": b.size,
            "verified": b.verified,
            "fixture_code": b.fixture_code,
            "txs": b.txs,
        }
        for b in batches
    ]
    return result


_BLOCKING_REASON = {
    "balance_chain": "its balances don't add up row by row",
    "summary_match": "its totals don't match its own summary",
}


def _refuse_if_numbers_fail(parsed: ParsedStatement) -> None:
    """Stop here, for the preview and the save alike, before any row reaches the browser."""
    blocking, _ = failed_checks(parsed.integrity)
    if blocking:
        reasons = " and ".join(_BLOCKING_REASON[name] for name in blocking)
        raise HTTPException(
            422,
            {
                "code": "integrity_failed",
                "message": f"This statement can't be used because {reasons}. "
                "Download a fresh copy from M-Pesa and upload that.",
            },
        )


async def _parse_and_match(
    db: Supabase,
    pepper: bytes,
    club_id: str,
    pdf: bytes,
    password: str,
    limiter: UploadLimiter,
    actor: str,
):
    """Parse the statement, load the club's roster and fixtures, match and find batches."""
    try:
        parsed = await run_in_threadpool(parse_statement, pdf, password)
    except StatementError as exc:
        if exc.code == "wrong_password":
            limiter.wrong_password(actor)
        raise HTTPException(
            _ERROR_STATUS.get(exc.code, 422), {"code": exc.code, "message": exc.message}
        ) from None
    _refuse_if_numbers_fail(parsed)
    players = [
        Player(r["player_code"], r["full_name"], r.get("mask_key"))
        for r in await run_in_threadpool(db.roster, club_id)
        if r.get("active", True)
    ]
    fixtures: dict[date, str] = {
        date.fromisoformat(f["match_date"]): f["fixture_code"]
        for f in await run_in_threadpool(db.fixtures, club_id)
    }
    matches = match_rows(parsed.rows, players, club_key(pepper, club_id))
    return parsed, players, fixtures, matches, find_batches(parsed.rows, matches, fixtures)


class TagIn(BaseModel):
    # Only the choice of rows and categories comes from the browser; extra fields such as an
    # amount are refused rather than silently ignored.
    model_config = ConfigDict(extra="forbid")

    tx: str = Field(pattern=r"^[A-Z0-9]{10}$")
    category: str
    fixture_code: str | None = Field(default=None, max_length=40)


class DraftIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement_pdf: str = Field(description="the statement PDF, base64-encoded")
    tags: list[TagIn] = Field(min_length=1, max_length=2000)
    acknowledged_checks: list[str] = Field(default_factory=list, max_length=10)


_DB_ERROR_STATUS = {"42501": 403, "23505": 409, "23514": 422, "P0001": 422}


@router.post("/dossiers")
async def create_draft(
    club_id: str,
    body: DraftIn,
    request: Request,
    x_actor_id: str = Header(default=""),
    x_statement_password: str = Header(default=""),
) -> dict[str, Any]:
    """Create (or replace) the draft dossier for a statement from the coach's tags.

    The PDF is sent again and re-parsed, so every stored amount and date comes from the
    statement, not from the browser (ADR 0002). Untagged rows are personal and never stored.
    """
    db, pepper = _deps(request)
    await _require_role(db, club_id, x_actor_id, {"manager"})
    limiter = _admit_upload(request, club_id, x_actor_id)
    try:
        pdf = base64.b64decode(body.statement_pdf, validate=True)
    except ValueError:
        raise HTTPException(
            400, {"code": "bad_pdf", "message": "statement_pdf isn't base64"}
        ) from None
    if len(pdf) > MAX_STATEMENT_BYTES:
        raise HTTPException(413, {"code": "too_large", "message": "Statements are limited to 5 MB"})

    try:
        parsed, _, fixtures, matches, batches = await _parse_and_match(
            db, pepper, club_id, pdf, x_statement_password, limiter, x_actor_id
        )
    finally:
        del pdf
    # Checked against the re-parsed statement, so the browser can't acknowledge less than failed.
    _, warnings = failed_checks(parsed.integrity)
    if set(warnings) - set(body.acknowledged_checks):
        raise HTTPException(
            422,
            {
                "code": "needs_acknowledgement",
                "message": "Confirm the statement warnings before saving.",
            },
        )
    try:
        items = build_items(
            parsed.rows,
            [Tag(t.tx, t.category, t.fixture_code) for t in body.tags],
            matches,
            batches,
            set(fixtures.values()),
            club_key(pepper, club_id),
        )
    except TagError as exc:
        raise HTTPException(422, {"code": "bad_tags", "problems": exc.problems}) from None

    integrity = {
        "score_bp": parsed.integrity.score_bp,
        "checks": {
            name: {"passed": c.passed, "weight_bp": c.weight_bp, "detail": c.detail}
            for name, c in parsed.integrity.checks.items()
        },
        "acknowledged": warnings,  # confirmed by the manager on saving; outside the signed payload
    }
    params = {
        "p_club": club_id,
        "p_actor": x_actor_id,
        "p_period_from": parsed.period_from.isoformat() if parsed.period_from else None,
        "p_period_to": parsed.period_to.isoformat() if parsed.period_to else None,
        "p_source_sha256": parsed.source_sha256,
        "p_rows_total": len(parsed.rows),
        "p_integrity": integrity,
        "p_items": items,
    }
    if params["p_period_from"] is None or params["p_period_to"] is None:
        raise HTTPException(
            422, {"code": "no_period", "message": "The statement period wasn't found"}
        )
    try:
        created = await run_in_threadpool(db.create_draft_dossier, params)
    except SupabaseError as exc:
        status = _DB_ERROR_STATUS.get(exc.code or "", 502)
        raise HTTPException(status, {"code": "database", "message": str(exc)}) from None
    return {
        **created,
        "items": len(items),
        "income_cents": sum(i["amt_cents"] for i in items if i["dir"] == "in"),
        "spent_cents": sum(i["amt_cents"] + i["fee_cents"] for i in items if i["dir"] == "out"),
        "integrity_score_bp": parsed.integrity.score_bp,
    }
