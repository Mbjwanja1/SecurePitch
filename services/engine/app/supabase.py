"""Minimal Supabase client for the engine, over HTTPS only (ADR 0002).

The secret key runs as service_role and bypasses row-level security, so every method here takes
the club it's scoped to, and endpoints check the acting user's role in that club first
(ADR 0002 rules 5-7).
"""

from __future__ import annotations

from typing import Any

import httpx


class SupabaseError(RuntimeError):
    pass


class Supabase:
    def __init__(self, url: str, key: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http = httpx.Client(
            base_url=url.rstrip("/") + "/rest/v1",
            # sb_secret_ keys need only apikey; legacy JWT keys also need Authorization.
            headers={"apikey": key, "Authorization": f"Bearer {key}"},
            timeout=20,
            transport=transport,
        )

    def _ok(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.is_error:
            # Status and Postgres error code only: never the request body.
            code = (
                r.json().get("code")
                if r.headers.get("content-type", "").startswith("application/json")
                else None
            )
            raise SupabaseError(f"Couldn't {what}: HTTP {r.status_code} {code or ''}".strip())
        return r

    def role_of(self, club_id: str, user_id: str) -> str | None:
        r = self._ok(
            self.http.get(
                "/club_members",
                params={"select": "role", "club_id": f"eq.{club_id}", "user_id": f"eq.{user_id}"},
            ),
            "check club membership",
        )
        rows = r.json()
        return rows[0]["role"] if rows else None

    def roster(self, club_id: str) -> list[dict[str, Any]]:
        r = self._ok(
            self.http.get(
                "/roster_entries",
                params={
                    "select": "player_code,full_name,phone_key,mask_key,active",
                    "club_id": f"eq.{club_id}",
                },
            ),
            "load the roster",
        )
        return r.json()

    def fixtures(self, club_id: str) -> list[dict[str, Any]]:
        r = self._ok(
            self.http.get(
                "/fixtures",
                params={"select": "fixture_code,match_date", "club_id": f"eq.{club_id}"},
            ),
            "load fixtures",
        )
        return r.json()

    def upsert_roster(self, rows: list[dict[str, Any]]) -> None:
        self._ok(
            self.http.post(
                "/roster_entries",
                params={"on_conflict": "club_id,phone_key"},
                json=rows,
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            ),
            "save the roster",
        )
