"""Match statement transfers to roster players, and find matchday batches.

A row's masked number (prefix4|suffix3) is turned into the club's mask_key and looked up in the
roster; the name printed on the statement then confirms it. M-Pesa names are the line's
registered owner, which for young players is often a parent, so a number match without a name
match is reported separately ("number_only") for the coach and captain to confirm.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum

from app.ingest.classify import name_tokens
from app.ingest.models import Kind, Row
from app.roster.keys import mask_key

PERSON_OUT = {Kind.P2P_OUT, Kind.POCHI_OUT}
BATCH_MIN_PAYMENTS = 5  # e.g. 18 x KES 250 bus fare on a matchday


class MatchStatus(StrEnum):
    VERIFIED = "verified"  # masked number and name both match one player
    NUMBER_ONLY = "number_only"  # number matches one player, name doesn't (e.g. parent's line)
    AMBIGUOUS = "ambiguous"  # several players share the masked number; name doesn't decide
    UNMATCHED = "unmatched"  # no player with that masked number


@dataclass(frozen=True)
class Player:
    player_code: str
    full_name: str
    mask_key: str | None


@dataclass(frozen=True)
class Match:
    status: MatchStatus
    player_code: str | None = None


@dataclass
class Batch:
    day: date
    amount_cents: int
    txs: list[str] = field(default_factory=list)
    verified: int = 0
    fixture_code: str | None = None

    @property
    def size(self) -> int:
        return len(self.txs)


def match_rows(rows: Iterable[Row], players: Sequence[Player], club_key: bytes) -> dict[str, Match]:
    """Match every person-to-person row with a masked number. Returns {tx: Match}."""
    by_mask: dict[str, list[Player]] = defaultdict(list)
    for p in players:
        if p.mask_key:
            by_mask[p.mask_key].append(p)

    matches: dict[str, Match] = {}
    for row in rows:
        cp = row.counterparty
        if cp.type != "person" or not cp.masked_prefix or not cp.masked_suffix:
            continue
        candidates = by_mask.get(mask_key(club_key, cp.masked_prefix, cp.masked_suffix), [])
        if not candidates:
            matches[row.tx] = Match(MatchStatus.UNMATCHED)
            continue
        statement_name = set(name_tokens(cp.name))
        named = [p for p in candidates if statement_name & set(name_tokens(p.full_name))]
        if len(named) == 1:
            matches[row.tx] = Match(MatchStatus.VERIFIED, named[0].player_code)
        elif len(candidates) == 1:
            matches[row.tx] = Match(MatchStatus.NUMBER_ONLY, candidates[0].player_code)
        else:
            matches[row.tx] = Match(MatchStatus.AMBIGUOUS)
    return matches


def find_batches(
    rows: Iterable[Row],
    matches: dict[str, Match],
    fixtures: dict[date, str],
) -> list[Batch]:
    """Same-amount payments to roster players on one day, e.g. matchday bus fare."""
    groups: dict[tuple[date, int], Batch] = {}
    for row in rows:
        m = matches.get(row.tx)
        if row.kind not in PERSON_OUT or m is None or m.status is MatchStatus.UNMATCHED:
            continue
        day = row.ts.date()
        batch = groups.setdefault((day, row.withdrawn_cents), Batch(day, row.withdrawn_cents))
        batch.txs.append(row.tx)
        batch.verified += m.status is MatchStatus.VERIFIED
    batches = [b for b in groups.values() if b.size >= BATCH_MIN_PAYMENTS]
    for b in batches:
        b.fixture_code = fixtures.get(b.day)
    return sorted(batches, key=lambda b: (b.day, b.amount_cents))
