"""Limits on statement uploads, so one account can't tie up the engine or guess a PDF password.

Every upload is parsed in memory, which is the most expensive thing the engine does, and a
wrong password is an answer an attacker could use: statement passwords are short, and often a
national ID number. So there are two limits:

- uploads per user and per club, which cap the work;
- wrong passwords per user, which is much tighter and cap the guessing.

Counts live in this process. The engine is one process in a read-only container, so that's
all of them, and there's nothing to write to disk. A restart clears the counts, which is fine
for limits measured in minutes. Callers check roles first, so only club members are counted
and someone outside a club can't use up a manager's allowance.
"""

from __future__ import annotations

import math
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

UPLOADS_PER_USER = (12, 10 * 60)  # a full upload is two parses: reading it, then saving the draft
UPLOADS_PER_CLUB = (30, 60 * 60)
WRONG_PASSWORDS_PER_USER = (5, 15 * 60)

_SWEEP_ABOVE = 1000  # keys, before stale ones are cleared out


@dataclass(frozen=True)
class Refusal:
    reason: str
    retry_after: int  # seconds

    @property
    def message(self) -> str:
        minutes = math.ceil(self.retry_after / 60)
        wait = "a minute" if minutes <= 1 else f"{minutes} minutes"
        return f"{self.reason} Try again in about {wait}."


class UploadLimiter:
    def __init__(self, now: Callable[[], float] = time.monotonic) -> None:
        self._now = now
        self._hits: dict[str, deque[float]] = {}

    def _wait(self, key: str, limit: int, window: int) -> int:
        """Seconds until `key` is under its limit; 0 if it already is."""
        hits = self._hits.get(key)
        if hits is None:
            return 0
        cutoff = self._now() - window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if len(hits) < limit:
            return 0
        return max(1, math.ceil(hits[-limit] + window - self._now()))

    def _record(self, key: str) -> None:
        if len(self._hits) > _SWEEP_ABOVE:
            self._sweep()
        self._hits.setdefault(key, deque()).append(self._now())

    def _sweep(self) -> None:
        longest = max(UPLOADS_PER_USER[1], UPLOADS_PER_CLUB[1], WRONG_PASSWORDS_PER_USER[1])
        cutoff = self._now() - longest
        self._hits = {k: v for k, v in self._hits.items() if v and v[-1] > cutoff}

    def admit(self, user: str, club: str) -> Refusal | None:
        """Count an upload, or say why it's refused. Call before reading or parsing the PDF."""
        # No awaits in here, so requests arriving together are each counted before the next.
        wait = self._wait(f"wrong:{user}", *WRONG_PASSWORDS_PER_USER)
        if wait:
            return Refusal("Too many wrong statement passwords.", wait)
        wait = max(
            self._wait(f"user:{user}", *UPLOADS_PER_USER),
            self._wait(f"club:{club}", *UPLOADS_PER_CLUB),
        )
        if wait:
            return Refusal("Too many statement uploads.", wait)
        self._record(f"user:{user}")
        self._record(f"club:{club}")
        return None

    def wrong_password(self, user: str) -> None:
        self._record(f"wrong:{user}")
