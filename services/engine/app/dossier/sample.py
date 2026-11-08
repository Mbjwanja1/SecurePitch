"""A synthetic sealed dossier for previews, tests and the CI smoke test. No real data."""

from __future__ import annotations

from typing import Any

from app.approvals import payload

DOSSIER_ID = "5a3c1f0e-8b2d-4e6f-9a1b-2c3d4e5f6a7b"
CLUB_ID = "0f1e2d3c-4b5a-4968-8776-655443322110"


def _item(tx, ts, amt, cat, branch, cp, fee=0, fixture=None, receipt=None) -> dict[str, Any]:
    return {
        "tx": tx,
        "ts": ts,
        "amt_cents": amt,
        "fee_cents": fee,
        "dir": "in" if cat == "income" else "out",
        "branch": branch,
        "category": cat,
        "cp_type": cp[0],
        "cp_ref": cp[1],
        "fixture_code": fixture,
        "salt": f"c2FsdC1zYW1wbGUt{tx}",
        "receipt_sha256": receipt,
    }


def snapshot(club_name: str = "Synthetic Lionesses FC", players: bool = True) -> dict[str, Any]:
    """An approval_snapshot() result, as the database returns it. With players=False, every
    squad payment went to someone not on the roster (the empty states of pages 3 and 4)."""
    items = [
        _item(
            "SJA1SPONS1",
            "2026-10-02T09:00:00+03:00",
            5_000_000,
            "income",
            "I",
            ("paybill", "400200"),
        ),
        _item(
            "SJB2KITS01",
            "2026-10-04T11:20:00+03:00",
            1_200_000,
            "kit",
            "A",
            ("till", "5123456"),
            fee=0,
            receipt="ab" * 32,
        ),
        _item(
            "SJC3HIRE01",
            "2026-10-09T16:05:00+03:00",
            350_000,
            "ground_hire",
            "A",
            ("paybill", "222111"),
            fee=5_300,
        ),
    ]
    for n, (day, fixture) in enumerate([("10", "MD1"), ("17", "MD2"), ("24", "MD3")]):
        for p in range(1, 7):
            items.append(
                _item(
                    f"SK{n}P{p:02d}FARE",  # ten characters, like a real M-Pesa code
                    f"2026-10-{day}T07:{10 + p:02d}:00+03:00",
                    50_000,
                    "transport",
                    "B",
                    ("player", f"P{p:02d}") if players else ("person", f"hmac:{n}{p}"),
                    fee=700,
                    fixture=fixture,
                )
            )
    items.append(
        _item(
            "SL9OTHER01",
            "2026-10-24T18:00:00+03:00",
            80_000,
            "meals",
            "B",
            ("person", "hmac:x"),
            fee=0,
        )
    )
    return {
        "dossier": {
            "id": DOSSIER_ID,
            "club_id": CLUB_ID,
            "club_name": club_name,
            "period_from": "2026-10-01",
            "period_to": "2026-10-31",
            "source_sha256": "cd" * 32,
            "rows_total": 64,
            "integrity": {"score_bp": 9500, "checks": {"fonts": {"passed": True}}},
        },
        "items": items,
        "planned_spends": [
            {
                "supplier": "Synthetic Sports Ltd",
                "till": "5123456",
                "amt_cents": 1_500_000,
                "purpose": "Match balls",
            },
            {
                "supplier": "Synthetic Coaches",
                "till": "300400",
                "amt_cents": 800_000,
                "purpose": "Away-day bus",
            },
        ],
    }


def sealed_payload(snap: dict[str, Any], kid: str = "local-sample") -> dict[str, Any]:
    """The sealed payload for that snapshot. The approvals are left empty: rendering never
    reads them, and a sample has no real passkeys."""
    approval, _ = payload.build(snap)
    return {**approval, "kid": kid, "approvals": [], "sealed_at": "2026-11-01T14:05:00+03:00"}
