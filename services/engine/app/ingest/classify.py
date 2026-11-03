"""Classify a statement row from its Details text (docs/research/mpesa-format.md section 4)."""

from __future__ import annotations

import re

from app.ingest.models import Counterparty, Kind

# Counterparty numbers are always masked: 254712***789 (international) or 0712***789 (local).
MASKED = r"(?P<pre>\d{4,6})\*+(?P<suf>\d{3})"

_PATTERNS: list[tuple[Kind, str, re.Pattern[str]]] = [
    (Kind.CHARGE, "none", re.compile(r"^.*\bCharge$", re.I)),
    (
        Kind.POCHI_OUT,
        "person",
        re.compile(rf"^Customer Payment to Small Business to\s*-\s*{MASKED}\s*(?P<name>.*)$", re.I),
    ),
    (
        Kind.P2P_OUT,
        "person",
        re.compile(rf"^Customer Transfer to\s*-\s*{MASKED}\s*(?P<name>.*)$", re.I),
    ),
    (
        Kind.P2P_IN,
        "person",
        re.compile(rf"^Funds received from\s*-\s*{MASKED}\s*(?P<name>.*)$", re.I),
    ),
    (
        Kind.TILL,
        "till",
        re.compile(
            r"^Merchant Payment(?: Online)? to\s*(?P<num>\d{5,7})\s*-\s*(?P<name>.*)$", re.I
        ),
    ),
    (
        Kind.PAYBILL,
        "paybill",
        re.compile(
            r"^Pay Bill(?: Online)? to\s*(?P<num>\d{5,7})\s*-\s*(?P<name>.*?)"
            r"(?:\s*Acc\.\s*(?P<acct>.*))?$",
            re.I,
        ),
    ),
    (
        Kind.B2C_IN,
        "business",
        re.compile(
            r"^Business Payment from\s*(?P<num>\d+)\s*-\s*(?P<name>.*?)(?:\s+via\s.*)?$", re.I
        ),
    ),
    (Kind.AIRTIME, "none", re.compile(r"^Airtime Purchase\b", re.I)),
    (Kind.BUNDLE, "none", re.compile(r"^Customer Bundle Purchase\b", re.I)),
]


def collapse(text: str | None) -> str:
    """Join the cell's line breaks and squeeze whitespace."""
    return " ".join((text or "").split())


def national_prefix(prefix: str) -> str | None:
    """'254712' or '0712' -> '0712'; anything else -> None."""
    if len(prefix) == 6 and prefix.startswith("254"):
        return "0" + prefix[3:]
    if len(prefix) == 4 and prefix.startswith("0"):
        return prefix
    return None


def classify(details: str) -> tuple[Kind, Counterparty]:
    text = collapse(details)
    for kind, cp_type, pattern in _PATTERNS:
        m = pattern.match(text)
        if not m:
            continue
        groups = m.groupdict()
        name = (groups.get("name") or "").strip(" -") or None
        prefix = national_prefix(groups["pre"]) if groups.get("pre") else None
        return kind, Counterparty(
            type=cp_type,
            masked_prefix=prefix,
            masked_suffix=groups.get("suf") if prefix else None,
            name=name,
            number=groups.get("num"),
            account=(groups.get("acct") or "").strip() or None,
        )
    return Kind.OTHER, Counterparty("none")


def name_tokens(name: str | None) -> tuple[str, ...]:
    """Case- and punctuation-insensitive name tokens: 'Jane  WANJIKU' -> ('jane', 'wanjiku')."""
    return tuple(t for t in re.sub(r"[^\w\s]", " ", (name or "").casefold()).split() if t)
