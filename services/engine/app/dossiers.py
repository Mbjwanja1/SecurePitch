"""Build a draft dossier's ledger rows from a parsed statement and the coach's tags.

The statement is the source of truth: amounts, times, receipt numbers and counterparties come
from the re-parsed PDF, and the tags only choose which rows are club rows and their category.
Untagged rows are personal and never leave the engine. Names never leave it either: a matched
player is stored as their player code, anyone else as a keyed hash of their masked number.
"""

from __future__ import annotations

import secrets
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from app.ingest.models import Kind, Row
from app.roster.keys import mask_key
from app.roster.match import Batch, Match, MatchStatus

CATEGORIES = {"transport", "allowance", "meals", "kit", "ground_hire", "income", "other"}


@dataclass(frozen=True)
class Tag:
    tx: str
    category: str
    fixture_code: str | None = None


class TagError(ValueError):
    """Problems with the submitted tags; each names the receipt number, never statement data."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("; ".join(problems))
        self.problems = problems


def _counterparty(row: Row, match: Match | None, club_key: bytes) -> tuple[str, str]:
    cp = row.counterparty
    if (
        match
        and match.player_code
        and match.status in (MatchStatus.VERIFIED, MatchStatus.NUMBER_ONLY)
    ):
        return "player", match.player_code
    if cp.type in ("till", "paybill") and cp.number:
        return cp.type, cp.number  # business numbers are public; paybill account refs are not kept
    if cp.type == "business" and cp.number:
        return "paybill", cp.number  # the organisation's shortcode
    if cp.mask_key and cp.masked_prefix and cp.masked_suffix:
        return "person", "hmac:" + mask_key(club_key, cp.masked_prefix, cp.masked_suffix)
    return "person", "none"


def _branch(row: Row) -> str:
    if row.direction == "in":
        return "I"  # club income
    return "A" if row.counterparty.type in ("till", "paybill") else "B"  # merchant / squad


def build_items(
    rows: Sequence[Row],
    tags: Iterable[Tag],
    matches: dict[str, Match],
    batches: Sequence[Batch],
    fixture_codes: set[str],
    club_key: bytes,
) -> list[dict[str, Any]]:
    by_tx = {r.tx: r for r in rows}
    batch_fixture = {tx: b.fixture_code for b in batches if b.fixture_code for tx in b.txs}
    problems: list[str] = []
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tag in tags:
        row = by_tx.get(tag.tx)
        if row is None:
            problems.append(f"{tag.tx}: not in this statement")
            continue
        if tag.tx in seen:
            problems.append(f"{tag.tx}: tagged twice")
            continue
        seen.add(tag.tx)
        if row.kind is Kind.CHARGE and row.fee_of:
            problems.append(f"{tag.tx}: a fee, already counted with {row.fee_of}")
            continue
        if tag.category not in CATEGORIES:
            problems.append(f"{tag.tx}: unknown category {tag.category!r}")
            continue
        if (row.direction == "in") != (tag.category == "income"):
            problems.append(
                f"{tag.tx}: money {'in' if row.direction == 'in' else 'out'} can't be "
                f"tagged {tag.category!r}"
            )
            continue
        fixture = tag.fixture_code or batch_fixture.get(row.tx)
        if fixture is not None and fixture not in fixture_codes:
            problems.append(f"{tag.tx}: unknown fixture {fixture!r}")
            continue
        cp_type, cp_ref = _counterparty(row, matches.get(row.tx), club_key)
        items.append(
            {
                "tx": row.tx,
                "ts": row.ts.isoformat(),
                "amt_cents": row.amount_cents,
                "fee_cents": row.fee_cents,
                "dir": row.direction,
                "branch": _branch(row),
                "category": tag.category,
                "cp_type": cp_type,
                "cp_ref": cp_ref,
                "fixture_code": fixture,
                "salt": secrets.token_urlsafe(
                    16
                ),  # CRYPTO_SPEC section 4: stops guessing small leaves
            }
        )
    if problems:
        raise TagError(problems)
    if not items:
        raise TagError(["tag at least one club transaction"])
    return items
