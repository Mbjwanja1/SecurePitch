"""Roster phone keys (docs/CRYPTO_SPEC.md section 8).

Raw phone numbers are never stored. Each club gets its own HMAC key derived from ROSTER_PEPPER,
so the same number gives different keys in different clubs, and a database leak without the
pepper can't be brute-forced back to numbers (Kenya's mobile space is only ~10^9).

    club_key  = HMAC-SHA256(pepper, "securepitch/roster/v1/club/" || club_id)
    phone_key = HMAC-SHA256(club_key, "phone:" || E.164 number)       e.g. "+2547XXXXXXXX"
    mask_key  = HMAC-SHA256(club_key, "mask:" || prefix4 || "|" || suffix3)  e.g. "0712|678"

Statements only ever show the masked form (docs/research/mpesa-format.md section 5), so
mask_key is what matching uses; phone_key de-duplicates the roster.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re

_KENYAN_MOBILE = re.compile(r"^(?:\+?254|0)?([17]\d{8})$")


class InvalidPhone(ValueError):
    pass


def pepper_from_env(value: str) -> bytes:
    pepper = base64.b64decode(value, validate=True)
    if len(pepper) != 32:
        raise ValueError("ROSTER_PEPPER must be 32 bytes, base64-encoded")
    return pepper


def club_key(pepper: bytes, club_id: str) -> bytes:
    return hmac.new(
        pepper, f"securepitch/roster/v1/club/{club_id}".encode(), hashlib.sha256
    ).digest()


def normalise_phone(raw: str) -> str:
    """Accept 07XX XXX XXX, 07XX-XXX-XXX, 2547XXXXXXXX or +254 7XX XXX XXX; return +2547XXXXXXXX."""
    digits = re.sub(r"[\s\-().]", "", raw or "")
    m = _KENYAN_MOBILE.match(digits)
    if not m:
        raise InvalidPhone("not a Kenyan mobile number (07…, 01…, 2547… or +2547…)")
    return "+254" + m.group(1)


def masked_parts(e164: str) -> tuple[str, str]:
    """+2547AABBBCCC -> ("07AA", "CCC"): what a statement shows as 07AA***CCC."""
    national = "0" + e164.removeprefix("+254")
    return national[:4], national[-3:]


def phone_key(key: bytes, e164: str) -> str:
    return hmac.new(key, f"phone:{e164}".encode(), hashlib.sha256).hexdigest()


def mask_key(key: bytes, prefix4: str, suffix3: str) -> str:
    return hmac.new(key, f"mask:{prefix4}|{suffix3}".encode(), hashlib.sha256).hexdigest()
