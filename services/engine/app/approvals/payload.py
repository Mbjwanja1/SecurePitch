"""The approval payload: what the manager and treasurer sign with their passkeys.

CRYPTO_SPEC section 6. Built only from approval_snapshot() (the database), never from the
browser. The challenge is SHA-256 of its canonical JSON; sealing later adds "kid", "approvals"
and "sealed_at", so anyone can rebuild the challenge from a sealed payload.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from app.crypto.canonical import canonicalize, sha256
from app.crypto.merkle import leaf_hash, merkle_root, sort_leaf_objects
from app.ingest.parse import EAT

PAYLOAD_VERSION = 1


def _eat(ts: str) -> str:
    """Any ISO timestamp -> Kenyan time with seconds, e.g. '2026-10-17T07:15:00+03:00'."""
    return datetime.fromisoformat(ts).astimezone(EAT).isoformat(timespec="seconds")


def leaf_object(item: dict[str, Any]) -> dict[str, Any]:
    """One disclosed club row (CRYPTO_SPEC section 4)."""
    return {
        "v": PAYLOAD_VERSION,
        "branch": item["branch"],
        "tx": item["tx"],
        "ts": _eat(item["ts"]),
        "amt": item["amt_cents"],
        "fee": item["fee_cents"],
        "dir": item["dir"],
        "cp": {"type": item["cp_type"], "ref": item["cp_ref"]},
        "cat": item["category"],
        "fixture": item["fixture_code"],
        # Attestations and player corroboration aren't built yet (ADR 0003): stated, not omitted.
        "ev": {"receipt_sha256": item.get("receipt_sha256"), "attest": [], "corroborated": False},
        "salt": item["salt"],
    }


def build(snapshot: dict[str, Any]) -> tuple[dict[str, Any], dict[str, str]]:
    """Return (approval payload, {tx: leaf hash hex}) for an approval_snapshot() result."""
    d = snapshot["dossier"]
    leaves = sort_leaf_objects([leaf_object(i) for i in snapshot["items"]])
    if not leaves:
        raise ValueError("a dossier needs at least one ledger row")
    hashes = [leaf_hash(obj) for obj in leaves]

    totals: dict[str, int] = defaultdict(int)
    for i in snapshot["items"]:
        totals[i["category"]] += i["amt_cents"] + (i["fee_cents"] if i["dir"] == "out" else 0)
    integrity = d.get("integrity") or {}

    payload = {
        "v": PAYLOAD_VERSION,
        "dossier_id": d["id"],
        "club": {"id": d["club_id"], "name": d["club_name"]},
        "period": {"from": d["period_from"], "to": d["period_to"]},
        "source_sha256": d["source_sha256"],
        "rows_total": d["rows_total"],
        "rows_disclosed": len(leaves),
        "merkle_root": merkle_root(hashes).hex(),
        "totals_cents": dict(sorted(totals.items())),
        "integrity": {
            "score_bp": integrity.get("score_bp", 0),
            "checks": {k: bool(c.get("passed")) for k, c in integrity.get("checks", {}).items()},
        },
        "planned_spends": [
            {
                "supplier": p["supplier"],
                "till": p["till"],
                "amt": p["amt_cents"],
                "purpose": p["purpose"],
            }
            # CRYPTO_SPEC section 6 order, by code point: never the database's text collation.
            for p in sorted(
                snapshot["planned_spends"],
                key=lambda p: (p["till"], p["amt_cents"], p["supplier"], p["purpose"]),
            )
        ],
    }
    return payload, {obj["tx"]: h.hex() for obj, h in zip(leaves, hashes, strict=True)}


def challenge(payload: dict[str, Any]) -> bytes:
    """c = SHA-256(canonical(approval payload)): the WebAuthn challenge both approvers sign."""
    return sha256(canonicalize(payload))
