"""Synthetic M-Pesa-style statements for tests (layout: docs/research/mpesa-format.md).

Every page says SYNTHETIC TEST STATEMENT and the producer is this generator, not OpenPDF, so a
generated file can't pass for a genuine one (it scores 9500, losing the producer check). All
names, numbers and amounts are invented. Test-only: needs reportlab (a dev dependency).
"""

from __future__ import annotations

import io
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import pikepdf
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

PASSWORD = "123456"  # noqa: S105 - synthetic statements only
PRODUCER = "SecurePitch synthetic statement generator"
DISCLAIMER = "SYNTHETIC TEST STATEMENT - not issued by Safaricom"


@dataclass(frozen=True)
class Tx:
    tx: str
    ts: datetime
    details: str  # may contain "\n", like real cells
    paid_in: int = 0  # cents
    withdrawn: int = 0  # cents, positive; printed negative
    summary_type: str = "OTHERS"
    balance: int | None = None  # filled in by with_balances()


def money(cents: int) -> str:
    return f"{cents / 100:,.2f}"


def with_balances(txs_oldest_first: list[Tx], opening: int) -> list[Tx]:
    out, balance = [], opening
    for t in txs_oldest_first:
        balance += t.paid_in - t.withdrawn
        out.append(replace(t, balance=balance))
    return out


def lionesses_month() -> list[Tx]:
    """A month of coach transactions, oldest first, covering every pattern and edge case."""
    d = datetime(2026, 10, 17, 6, 30, 0)
    txs = [
        # The very first second holds a transfer and its charge (the first-group edge case).
        Tx(
            "SJA0000001",
            d - timedelta(days=5),
            "Customer Transfer to - 254711***101\nGRACE AKINYI",
            withdrawn=50000,
            summary_type="SEND MONEY",
        ),
        Tx(
            "SJA0000002",
            d - timedelta(days=5),
            "Customer Transfer of Funds\nCharge",
            withdrawn=1300,
        ),
        Tx(
            "SJA0000003",
            d,
            "Funds received from - 254722***202\nWell Wisher",
            paid_in=400000,
            summary_type="RECEIVED MONEY",
        ),
    ]
    # Matchday bus fare: 18 x KES 250, each with a KES 7 charge in the same second, listed in
    # alternating order, with both masked-number forms and mixed-case names.
    names = [
        "MERCY ATIENO",
        "Faith Wambui",
        "JOY NJERI",
        "Brenda Chebet",
        "SHARON OTIENO",
        "Lucy Muthoni",
        "DIANA KERUBO",
        "Ann Wairimu",
        "VIVIAN ACHIENG",
        "Esther Nyambura",
        "PURITY JEPKOECH",
        "Ruth Mumbua",
        "IVY ODHIAMBO",
        "Linda Wanjiru",
        "CYNTHIA MORAA",
        "Maureen Auma",
        "NANCY WAIRIMU",
        "Agnes Nduta",
    ]
    for i, name in enumerate(names):
        ts = d.replace(hour=7, minute=15, second=i)
        masked = f"254700***{i:03d}" if i % 2 else f"0700***{i:03d}"
        transfer = Tx(
            f"SJB{i:07d}",
            ts,
            f"Customer Transfer to - {masked}\n{name}",
            withdrawn=25000,
            summary_type="SEND MONEY",
        )
        charge = Tx(f"SJC{i:07d}", ts, "Customer Transfer of Funds\nCharge", withdrawn=700)
        txs += [transfer, charge]
    noon = d.replace(hour=11, minute=30)
    txs += [
        Tx(
            "SJD0000001",
            noon,
            "Merchant Payment to 5123456 -\nMAMA MBOGA KIOSK",
            withdrawn=180000,
            summary_type="LIPA NA M-PESA (BUY GOODS)",
        ),
        Tx(
            "SJD0000002",
            noon + timedelta(hours=1),
            "Customer Payment to Small\nBusiness to - 254733***303\nPeter Kamau",
            withdrawn=50000,
            summary_type="SEND MONEY",
        ),
        Tx(
            "SJD0000003",
            noon + timedelta(hours=2),
            "Pay Bill Online to 888880 -\nKPLC PREPAID Acc.\nSYN0000001",
            withdrawn=100000,
            summary_type="LIPA NA M-PESA (PAYBILL)",
        ),
        Tx("SJD0000004", noon + timedelta(hours=2), "Pay Bill Charge", withdrawn=500),
        Tx("SJD0000005", noon + timedelta(hours=3), "Airtime Purchase", withdrawn=10000),
        Tx(
            "SJD0000006",
            noon + timedelta(hours=4),
            "Customer Bundle Purchase to\n100000SYNTHETIC "
            "POSTPAID\nBUNDLE by - 254744***404\nSYNTHETIC USER",
            withdrawn=5000,
        ),
        Tx(
            "SJD0000007",
            noon + timedelta(hours=5),
            "Business Payment from 300300 -\nSYNTHETIC "
            "Bulk Account via SYN\nOriginal conversation ID is\n100000000001.",
            paid_in=320000,
        ),
        Tx(
            "SJD0000008",
            noon + timedelta(hours=6),
            "Customer Transfer to - 0755***505\nSynthetic Captain",
            withdrawn=300000,
            summary_type="SEND MONEY",
        ),
    ]
    txs = with_balances(txs, opening=500000)
    # Balances were computed transfer-then-charge. Like real statements, print some same-second
    # pairs the other way round: the very first pair, and every other matchday pair.
    for first, second in [(0, 1), *((3 + 2 * i, 4 + 2 * i) for i in range(0, len(names), 2))]:
        txs[first], txs[second] = txs[second], txs[first]
    return txs


def summary_of(txs: list[Tx]) -> dict[str, tuple[int, int]]:
    labels = [
        "SEND MONEY",
        "RECEIVED MONEY",
        "AGENT DEPOSIT",
        "AGENT WITHDRAWAL",
        "LIPA NA M-PESA (PAYBILL)",
        "LIPA NA M-PESA (BUY GOODS)",
        "OTHERS",
    ]
    out = {label: (0, 0) for label in labels}
    for t in txs:
        p_in, p_out = out[t.summary_type]
        out[t.summary_type] = (p_in + t.paid_in, p_out + t.withdrawn)
    out["TOTAL"] = (sum(t.paid_in for t in txs), sum(t.withdrawn for t in txs))
    return out


def build_statement(
    txs_oldest_first: list[Tx],
    *,
    password: str = PASSWORD,
    rows_per_page: int = 12,
    repeat_header: bool = True,
    summary: dict[str, tuple[int, int]] | None = None,
    producer: str = PRODUCER,
) -> bytes:
    """Render an encrypted (RC4-128, like genuine files) statement PDF, newest row first."""
    styles = getSampleStyleSheet()
    grid = TableStyle(
        [
            ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]
    )
    summary = summary or summary_of(txs_oldest_first)
    story = [
        Paragraph(DISCLAIMER, styles["Title"]),
        Paragraph("M-PESA STATEMENT", styles["Heading2"]),
        Paragraph("Customer Name: SYNTHETIC TEST ACCOUNT", styles["Normal"]),
        Paragraph("Statement Period: 01 Oct 2026 - 31 Oct 2026", styles["Normal"]),
        Paragraph("Request Date: 01 Nov 2026", styles["Normal"]),
        Paragraph("SUMMARY", styles["Heading3"]),
        Table(
            [["TRANSACTION TYPE", "PAID IN", "PAID OUT"]]
            + [[f"{k}:", money(v[0]), money(v[1])] for k, v in summary.items()],
            style=grid,
        ),
        Spacer(1, 12),
        Paragraph("DETAILED STATEMENT", styles["Heading3"]),
    ]
    header = [
        "Receipt No.",
        "Completion Time",
        "Details",
        "Transaction Status",
        "Paid In",
        "Withdrawn",
        "Balance",
    ]
    rows = [
        [
            t.tx,
            t.ts.strftime("%Y-%m-%d %H:%M:%S"),
            t.details,
            "Completed",
            money(t.paid_in) if t.paid_in else "",
            f"-{money(t.withdrawn)}" if t.withdrawn else "",
            money(t.balance or 0),
        ]
        for t in reversed(txs_oldest_first)
    ]
    for start in range(0, len(rows), rows_per_page):
        chunk = rows[start : start + rows_per_page]
        if repeat_header or start == 0:
            chunk = [header, *chunk]
        story += [
            Table(chunk, style=grid, repeatRows=0),
            Spacer(1, 6),
            Table(
                [
                    [
                        "Statement Verification Code",
                        "To verify the validity of this statement dial *334#",
                    ],
                    ["", ""],
                    ["SYN1CODE", ""],
                ],
                style=grid,
            ),
        ]
        story.append(PageBreak())
    story.pop()  # no blank page at the end

    plain = io.BytesIO()
    SimpleDocTemplate(plain, pagesize=landscape(A4), title=DISCLAIMER).build(story)
    out = io.BytesIO()
    with pikepdf.open(io.BytesIO(plain.getvalue())) as pdf:
        pdf.docinfo["/Producer"] = producer
        pdf.docinfo["/Creator"] = "SecurePitch tests"
        pdf.save(
            out,
            encryption=pikepdf.Encryption(
                user=password, owner=password + "-owner", R=3, aes=False, metadata=False
            ),
        )
    return out.getvalue()


# --- tampered variants (each simulates a specific edit to a genuine-looking statement) ---


def tampered_amount(txs: list[Tx]) -> list[Tx]:
    """One withdrawal edited down from KES 250 to KES 25 without fixing the balances."""
    out = list(txs)
    i = next(i for i, t in enumerate(out) if t.withdrawn == 25000)
    out[i] = replace(out[i], withdrawn=2500)
    return out


def removed_row(txs: list[Tx]) -> list[Tx]:
    """A row deleted from the middle, balances left as printed."""
    out = list(txs)
    del out[len(out) // 2]
    return out
