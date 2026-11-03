"""Minimal Supabase client for the engine, over HTTPS only (ADR 0002).

The secret key runs as service_role and bypasses row-level security, so every method here takes
the club it's scoped to, and endpoints check the acting user's role in that club first
(ADR 0002 rules 5-7).
"""

from __future__ import annotations

from typing import Any

import httpx

# Postgres error codes raised on purpose by our own database functions. Their messages are
# written to be shown to users ("this statement is already in a submitted dossier").
OUR_FUNCTION_ERRORS = {"42501", "23505", "23514", "P0001"}


class SupabaseError(RuntimeError):
    def __init__(self, message: str, status: int = 0, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


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
            # Never the request body. Only messages from our own functions are passed on.
            data = (
                r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            )
            code = data.get("code") if isinstance(data, dict) else None
            message = data.get("message") if code in OUR_FUNCTION_ERRORS else None
            raise SupabaseError(
                message or f"Couldn't {what}: HTTP {r.status_code} {code or ''}".strip(),
                status=r.status_code,
                code=code,
            )
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

    def create_draft_dossier(self, params: dict[str, Any]) -> dict[str, Any]:
        """One transaction in Postgres: replace any earlier draft of this statement, insert the
        dossier and its rows, write the audit entry (supabase/migrations/…_draft_dossiers.sql)."""
        r = self._ok(
            self.http.post("/rpc/create_draft_dossier", json=params), "create the draft dossier"
        )
        return r.json()
