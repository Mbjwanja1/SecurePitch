"""Club-scoped endpoints: roster import, and statement parsing with roster matching.

The web app's route handler sends X-Actor-Id: the signed-in user's ID from their session, never
from the request body (ADR 0002 rule 7). The engine checks that user's role in the club before
doing anything (rule 5), because its secret key bypasses row-level security.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from app.ingest.parse import StatementError, parse_statement
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
from app.supabase import Supabase

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
    if request.headers.get("content-type", "").split(";")[0].strip().lower() != "application/pdf":
        raise HTTPException(415, "Send the PDF as application/pdf")
    body = await request.body()
    if not body:
        raise HTTPException(400, "The request body is empty")
    try:
        parsed = await run_in_threadpool(parse_statement, body, x_statement_password)
    except StatementError as exc:
        raise HTTPException(
            _ERROR_STATUS.get(exc.code, 422), {"code": exc.code, "message": exc.message}
        ) from None
    finally:
        del body

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
    batches = find_batches(parsed.rows, matches, fixtures)

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
