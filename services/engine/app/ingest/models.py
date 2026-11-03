"""Shapes of a parsed statement. Money is integer cents; times are Africa/Nairobi (+03:00)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum


class Kind(StrEnum):
    P2P_OUT = "p2p_out"  # Customer Transfer to - <masked> <name>
    POCHI_OUT = "pochi_out"  # Customer Payment to Small Business to - <masked> <name>
    P2P_IN = "p2p_in"  # Funds received from - <masked> <name>
    TILL = "till"  # Merchant Payment (Online) to <till> - <name>
    PAYBILL = "paybill"  # Pay Bill (Online) to <number> - <name> Acc. <account>
    B2C_IN = "b2c_in"  # Business Payment from <shortcode> - <organisation> via ...
    CHARGE = "charge"  # Customer Transfer of Funds Charge / Pay Bill Charge
    AIRTIME = "airtime"  # Airtime Purchase
    BUNDLE = "bundle"  # Customer Bundle Purchase ...
    OTHER = "other"  # anything not recognised; shown to the coach as-is


@dataclass(frozen=True)
class Counterparty:
    type: str  # "person" | "till" | "paybill" | "business" | "none"
    masked_prefix: str | None = None  # national 4-digit prefix, e.g. "0712"
    masked_suffix: str | None = None  # last 3 digits, e.g. "789"
    name: str | None = None  # as printed in the statement
    number: str | None = None  # till, paybill or shortcode
    account: str | None = None  # paybill account reference

    @property
    def mask_key(self) -> str | None:
        """prefix4|suffix3, the value roster matching keys on (docs/research section 5)."""
        if self.masked_prefix and self.masked_suffix:
            return f"{self.masked_prefix}|{self.masked_suffix}"
        return None


@dataclass
class Row:
    tx: str
    ts: datetime
    details: str  # the statement's own wording, line breaks collapsed
    status: str
    paid_in_cents: int
    withdrawn_cents: int  # always >= 0 (the statement prints withdrawals as negatives)
    balance_cents: int
    kind: Kind = Kind.OTHER
    counterparty: Counterparty = field(default_factory=lambda: Counterparty("none"))
    fee_cents: int = 0  # charge rows in the same second, attached to this row
    fee_txs: list[str] = field(default_factory=list)
    fee_of: str | None = None  # on a charge row: the tx it belongs to

    @property
    def direction(self) -> str:
        return "in" if self.paid_in_cents > 0 else "out"

    @property
    def amount_cents(self) -> int:
        return self.paid_in_cents or self.withdrawn_cents


@dataclass(frozen=True)
class Check:
    passed: bool
    weight_bp: int
    detail: str


@dataclass
class Integrity:
    score_bp: int  # 0..10000; no floats in anything that may be signed (CRYPTO_SPEC section 1)
    checks: dict[str, Check]


@dataclass
class ParsedStatement:
    source_sha256: str
    pages: int
    period_from: date | None
    period_to: date | None
    rows: list[Row]  # newest first, as printed; charge rows included (fee_of set)
    summary: dict[str, tuple[int, int]]  # label -> (paid_in_cents, paid_out_cents)
    verification_code: str | None
    integrity: Integrity
