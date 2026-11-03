"""Integrity score for a statement (docs/research/mpesa-format.md sections 1 and 3).

Each check has a weight in basis points; the score is the sum of the weights of the checks that
pass (0..10000). Details hold counts only, never statement contents.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from itertools import permutations

from app.ingest.models import Check, Integrity, Row

WEIGHTS = {
    "balance_chain": 4000,  # every balance = previous + paid in - withdrawn
    "summary_match": 3000,  # the statement's own totals equal the sum of its rows
    "never_resaved": 2000,  # one %%EOF and no /Prev: not edited and saved incrementally
    "no_annotations_or_forms": 500,
    "producer_baseline": 500,  # genuine statements are produced by OpenPDF
}
MAX_GROUP_PERMUTATION = 6  # same-second groups seen so far have at most 2 rows


@dataclass(frozen=True)
class PdfSignals:
    eof_markers: int
    has_prev_trailer: bool
    annotations: int
    has_form: bool
    producer: str
    fonts: tuple[str, ...]


def chain_breaks(rows_newest_first: Sequence[Row]) -> tuple[int, int]:
    """(naive, reordered) breaks. Rows in the same second (a transfer and its charge) appear
    in either order, so the reordered count tries every order within each such group."""
    seq = list(reversed(rows_newest_first))
    amount = [r.paid_in_cents - r.withdrawn_cents for r in seq]
    balance = [r.balance_cents for r in seq]

    def breaks(order: Sequence[int]) -> int:
        return sum(
            balance[b] != balance[a] + amount[b] for a, b in zip(order, order[1:], strict=False)
        )

    groups: list[list[int]] = []
    for i, row in enumerate(seq):
        if groups and seq[groups[-1][0]].ts == row.ts:
            groups[-1].append(i)
        else:
            groups.append([i])
    order: list[int] = []
    for group in groups:
        best = group
        if len(group) <= MAX_GROUP_PERMUTATION:
            anchor = order[-1:]  # the first group only has to agree with itself
            for candidate in permutations(group):
                if breaks([*anchor, *candidate]) == 0:
                    best = list(candidate)
                    break
        order.extend(best)
    return breaks(range(len(seq))), breaks(order)


def score(
    rows: Sequence[Row],
    summary: dict[str, tuple[int, int]],
    signals: PdfSignals,
) -> Integrity:
    checks: dict[str, Check] = {}

    naive, reordered = chain_breaks(rows)
    checks["balance_chain"] = Check(
        reordered == 0,
        WEIGHTS["balance_chain"],
        f"{reordered} break(s) in {max(len(rows) - 1, 0)} links "
        f"({naive} before reordering same-second rows)",
    )

    total = summary.get("TOTAL")
    if total is None:
        checks["summary_match"] = Check(False, WEIGHTS["summary_match"], "no summary table found")
    else:
        paid_in = sum(r.paid_in_cents for r in rows)
        paid_out = sum(r.withdrawn_cents for r in rows)
        ok = total == (paid_in, paid_out)
        checks["summary_match"] = Check(
            ok,
            WEIGHTS["summary_match"],
            "summary totals equal the sum of the rows"
            if ok
            else "summary totals differ from the sum of the rows",
        )

    resaved = signals.eof_markers != 1 or signals.has_prev_trailer
    checks["never_resaved"] = Check(
        not resaved,
        WEIGHTS["never_resaved"],
        f"{signals.eof_markers} %%EOF marker(s), incremental-update trailer: "
        f"{'yes' if signals.has_prev_trailer else 'no'}",
    )

    clean = signals.annotations == 0 and not signals.has_form
    checks["no_annotations_or_forms"] = Check(
        clean,
        WEIGHTS["no_annotations_or_forms"],
        f"{signals.annotations} annotation(s), form fields: {'yes' if signals.has_form else 'no'}",
    )

    genuine_producer = signals.producer.startswith("OpenPDF")
    checks["producer_baseline"] = Check(
        genuine_producer,
        WEIGHTS["producer_baseline"],
        "produced by OpenPDF, like genuine statements"
        if genuine_producer
        else "not produced by OpenPDF (genuine statements are)",
    )

    return Integrity(
        score_bp=sum(c.weight_bp for c in checks.values() if c.passed),
        checks=checks,
    )
