# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.27", "python-dotenv>=1.0"]
# ///
"""Create a SecurePitch account and add it to a club.

    uv run tools/onboard_member.py --club "Nairobi City Inspectorate Lionesses" \\
        --email coach@example.com --name "Coach Eugene" --role manager

Creates the club if no club has that exact name. Creates the account already confirmed (no
email is sent: we have no email provider yet) and adds the membership. The password is typed
at a hidden prompt, or generated with --generate-password and shown once. Share it privately
(in person or by phone), never in a group chat.

Uses SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY from services/engine/.env. Admin tool only.
"""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import sys

import httpx
from dotenv import load_dotenv

MIN_PASSWORD_LENGTH = 12
ROLES = ("manager", "treasurer", "captain")


class Supabase:
    def __init__(self, url: str, key: str) -> None:
        self.http = httpx.Client(base_url=url.rstrip("/"), headers={"apikey": key}, timeout=20)

    def _check(self, r: httpx.Response, what: str) -> httpx.Response:
        if r.is_error:
            sys.exit(f"Couldn't {what}: HTTP {r.status_code} {r.text[:300]}")
        return r

    def find_or_create_club(self, name: str) -> tuple[str, bool]:
        r = self._check(
            self.http.get("/rest/v1/clubs", params={"select": "id", "name": f"eq.{name}"}),
            "look up the club",
        )
        rows = r.json()
        if len(rows) > 1:
            sys.exit(f"More than one club is named {name!r}; resolve it in the Supabase dashboard.")
        if rows:
            return rows[0]["id"], False
        r = self._check(
            self.http.post(
                "/rest/v1/clubs",
                json={"name": name},
                headers={"Prefer": "return=representation"},
            ),
            "create the club",
        )
        return r.json()[0]["id"], True

    def find_user(self, email: str) -> str | None:
        page = 1
        while True:
            r = self._check(
                self.http.get("/auth/v1/admin/users", params={"page": page, "per_page": 200}),
                "list accounts",
            )
            users = r.json().get("users", [])
            for user in users:
                if (user.get("email") or "").lower() == email.lower():
                    return user["id"]
            if len(users) < 200:
                return None
            page += 1

    def create_user(self, email: str, password: str, name: str) -> str:
        r = self._check(
            self.http.post(
                "/auth/v1/admin/users",
                json={
                    "email": email,
                    "password": password,
                    "email_confirm": True,  # no email provider yet; the admin vouches for it
                    "user_metadata": {"display_name": name},
                },
            ),
            "create the account",
        )
        return r.json()["id"]

    def add_member(self, club_id: str, user_id: str, role: str, name: str) -> None:
        self._check(
            self.http.post(
                "/rest/v1/club_members",
                params={"on_conflict": "club_id,user_id"},
                json={"club_id": club_id, "user_id": user_id, "role": role, "display_name": name},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            ),
            "add the membership",
        )


def read_password(generate: bool) -> tuple[str, bool]:
    if generate:
        return secrets.token_urlsafe(12), True  # 16 characters
    first = getpass.getpass(f"New account password (at least {MIN_PASSWORD_LENGTH} characters): ")
    if len(first) < MIN_PASSWORD_LENGTH:
        sys.exit(f"Password too short: use at least {MIN_PASSWORD_LENGTH} characters.")
    if getpass.getpass("Type it again: ") != first:
        sys.exit("The passwords didn't match.")
    return first, False


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--club", required=True, help="club name (created if it doesn't exist)")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True, help="name shown to other club members")
    parser.add_argument("--role", required=True, choices=ROLES)
    parser.add_argument(
        "--generate-password",
        action="store_true",
        help="generate a strong password and print it once",
    )
    parser.add_argument("--env-file", default="services/engine/.env")
    args = parser.parse_args()

    load_dotenv(args.env_file)
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        sys.exit(f"SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set in {args.env_file}.")
    db = Supabase(url, key)

    club_id, club_created = db.find_or_create_club(args.club)
    user_id = db.find_user(args.email)
    password, generated = (None, False)
    if user_id is None:
        password, generated = read_password(args.generate_password)
        user_id = db.create_user(args.email, password, args.name)
    db.add_member(club_id, user_id, args.role, args.name)

    print(f"club:    {args.club} ({'created' if club_created else 'existing'})")
    print(f"account: {args.email} ({'created' if password else 'existing; password unchanged'})")
    print(f"role:    {args.role}")
    if generated:
        print(f"password (shown once; share it privately): {password}")


if __name__ == "__main__":
    main()
