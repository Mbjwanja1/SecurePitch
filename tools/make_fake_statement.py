"""Write a synthetic M-Pesa-style statement PDF for manual testing (e.g. the upload screen).

    uv run --project services/engine python tools/make_fake_statement.py
    uv run --project services/engine python tools/make_fake_statement.py --variant tampered-amount

Writes to fixtures/synthetic/ (the only place the hooks allow PDFs). The password is 123456.
The PDF is marked SYNTHETIC TEST STATEMENT on every page and is never produced by OpenPDF, so it
scores 9500, not 10000. The layout comes from services/engine/tests/fakes/statement.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "engine"))

from tests.fakes.statement import (  # noqa: E402
    PASSWORD,
    build_statement,
    lionesses_month,
    removed_row,
    summary_of,
    tampered_amount,
)

VARIANTS = {
    "genuine-layout": lambda txs: build_statement(txs),
    "tampered-amount": lambda txs: build_statement(tampered_amount(txs), summary=summary_of(txs)),
    "removed-row": lambda txs: build_statement(removed_row(txs), summary=summary_of(txs)),
    "no-repeated-headers": lambda txs: build_statement(txs, repeat_header=False),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--variant", choices=VARIANTS, default="genuine-layout")
    args = parser.parse_args()
    out = ROOT / "fixtures" / "synthetic" / f"statement_{args.variant}.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(VARIANTS[args.variant](lionesses_month()))
    print(f"wrote {out.relative_to(ROOT)} (password {PASSWORD})")


if __name__ == "__main__":
    main()
