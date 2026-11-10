"""Parse an M-Pesa statement PDF entirely in memory.

    parse_statement(pdf_bytes, password) -> ParsedStatement

Never writes to disk and never logs contents. Errors carry a code and a generic message, never
statement data, because they may be shown to the user or end up in logs.
"""

from __future__ import annotations

import hashlib
import io
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

import pdfplumber
import pikepdf

from app.ingest.classify import classify, collapse
from app.ingest.integrity import PdfSignals, score
from app.ingest.models import Kind, ParsedStatement, Row

EAT = timezone(timedelta(hours=3), "EAT")  # Kenya has no daylight saving
TX_RE = re.compile(r"^[A-Z0-9]{10}$")
PERIOD_RE = re.compile(r"Statement Period\s*:\s*(\d{1,2} \w{3} \d{4})\s*-\s*(\d{1,2} \w{3} \d{4})")
DETAIL_COLUMNS = 7
# A genuine three-month statement of 582 rows is 17 pages. Parsing cost grows with pages, and a
# few KB of PDF can hold thousands of them, so the limit is on pages, not only on bytes.
MAX_PAGES = 200


class StatementError(Exception):
    """Raised with a stable code and a message that is safe to show or log."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _cents(cell: str | None, *, row: int, column: str, signed: bool = False) -> int:
    """'1,234.50' -> 123450. Amounts are unsigned (withdrawals are printed negative);
    balances keep their sign, since an overdrawn balance would be negative."""
    # Text extraction can leave spaces (even non-breaking ones) inside numbers: "- 250.00".
    text = re.sub(r"[\s,]", "", cell or "")
    if not text:
        return 0
    try:
        value = int(Decimal(text) * 100)
        return value if signed else abs(value)
    except InvalidOperation:
        raise StatementError(
            "unreadable_row", f"Row {row}: the {column} column isn't a number"
        ) from None


def _is_detail_header(row: list[str | None]) -> bool:
    return (row[0] or "").strip().lower().startswith("receipt")


def _pdf_signals(raw: bytes, doc: pikepdf.Pdf) -> PdfSignals:
    info = doc.docinfo if doc.docinfo is not None else {}
    fonts: set[str] = set()
    annotations = 0
    for page in doc.pages:
        # Malformed files can hold null or non-dictionary objects anywhere: check before walking.
        annots = page.get("/Annots")
        annotations += len(annots) if isinstance(annots, pikepdf.Array) else 0
        resources = page.get("/Resources")
        font_dict = resources.get("/Font") if isinstance(resources, pikepdf.Dictionary) else None
        if not isinstance(font_dict, pikepdf.Dictionary):
            continue
        for font in font_dict.values():
            base = font.get("/BaseFont", "?") if isinstance(font, pikepdf.Dictionary) else "?"
            fonts.add(re.sub(r"^/[A-Z]{6}\+", "/", str(base)))
    return PdfSignals(
        eof_markers=raw.count(b"%%EOF"),
        has_prev_trailer=b"/Prev" in raw,
        annotations=annotations,
        has_form="/AcroForm" in doc.Root,
        producer=str(info.get("/Producer", "")),
        fonts=tuple(sorted(fonts)),
    )


def _has_active_content(doc: pikepdf.Pdf) -> bool:
    """Scripts, attachments or an action that runs on opening. A statement never has these."""
    names = doc.Root.get("/Names")
    in_names = isinstance(names, pikepdf.Dictionary) and (
        "/JavaScript" in names or "/EmbeddedFiles" in names
    )
    return in_names or "/OpenAction" in doc.Root or "/AA" in doc.Root


def _period(text: str) -> tuple[date | None, date | None]:
    m = PERIOD_RE.search(text or "")
    if not m:
        return None, None
    try:
        return tuple(datetime.strptime(d, "%d %b %Y").date() for d in m.groups())  # type: ignore[return-value]
    except ValueError:
        return None, None


def _attach_charges(rows: list[Row]) -> None:
    """Give each charge row's fee to the outgoing transaction in the same second."""
    by_second: dict[datetime, list[Row]] = {}
    for r in rows:
        by_second.setdefault(r.ts, []).append(r)
    for r in rows:
        if r.kind is not Kind.CHARGE:
            continue
        parents = [p for p in by_second[r.ts] if p.kind is not Kind.CHARGE and p.withdrawn_cents]
        if parents:
            # Two transfers in one second each get their own fee: prefer one without a fee yet.
            parent = ([p for p in parents if not p.fee_txs] or parents)[0]
            parent.fee_cents += r.withdrawn_cents
            parent.fee_txs.append(r.tx)
            r.fee_of = parent.tx


def _check_rows(rows: list[Row], period_from: date | None, period_to: date | None) -> None:
    """Refuse row patterns a genuine statement can't have. Messages carry no statement data."""
    # A transfer and its charge do share a receipt number; two transactions never should.
    transactions = [r.tx for r in rows if r.kind is not Kind.CHARGE]
    if len(transactions) != len(set(transactions)):
        raise StatementError(
            "duplicate_receipt", "The same receipt number appears on two different transactions."
        )
    if period_from and period_to and any(not period_from <= r.ts.date() <= period_to for r in rows):
        raise StatementError(
            "rows_outside_period", "Some transactions fall outside the statement's own period."
        )


def parse_statement(pdf: bytes, password: str) -> ParsedStatement:
    if not pdf.startswith(b"%PDF-"):
        raise StatementError("not_a_pdf", "That file isn't a PDF.")
    try:
        with pikepdf.open(io.BytesIO(pdf), password=password) as doc:
            pages = len(doc.pages)
            if pages > MAX_PAGES:
                raise StatementError(
                    "too_many_pages", f"Statements are limited to {MAX_PAGES} pages."
                )
            if _has_active_content(doc):
                raise StatementError(
                    "active_content",
                    "That PDF contains scripts or attachments, so it can't be used.",
                )
            signals = _pdf_signals(pdf, doc)
    except pikepdf.PasswordError:
        raise StatementError("wrong_password", "The statement password is wrong.") from None
    except (pikepdf.PdfError, ValueError, TypeError, AttributeError, KeyError, IndexError):
        raise StatementError("unreadable_pdf", "The PDF couldn't be read.") from None
    if pages == 0:
        raise StatementError("unreadable_pdf", "The PDF has no pages.")

    try:
        return _parse_content(pdf, password, signals, pages)
    except StatementError:
        raise
    except Exception:  # noqa: BLE001 - pdfminer raises many types on malformed input
        raise StatementError("unreadable_pdf", "The PDF couldn't be read.") from None


def _parse_content(pdf: bytes, password: str, signals: PdfSignals, pages: int) -> ParsedStatement:
    rows: list[Row] = []
    summary: dict[str, tuple[int, int]] = {}
    verification_code: str | None = None
    with pdfplumber.open(io.BytesIO(pdf), password=password) as doc:
        first_text = doc.pages[0].extract_text() or ""
        if "M-PESA STATEMENT" not in first_text.upper():
            raise StatementError(
                "not_a_statement", "That PDF doesn't look like an M-Pesa statement."
            )
        period_from, period_to = _period(first_text)
        for page in doc.pages:
            for table in page.extract_tables():
                if not table or not table[0]:
                    continue
                first_cell = (table[0][0] or "").strip()
                if first_cell.upper().startswith("TRANSACTION TYPE"):
                    for label, paid_in, paid_out in (r[:3] for r in table[1:] if len(r) >= 3):
                        key = collapse(label).rstrip(":").upper()
                        summary[key] = (
                            _cents(paid_in, row=0, column="summary paid-in"),
                            _cents(paid_out, row=0, column="summary paid-out"),
                        )
                elif first_cell.lower().startswith("statement verification code"):
                    # The code sits below the header, after an empty spacer row.
                    codes = [collapse(r[0]) for r in table[1:] if r and collapse(r[0])]
                    if codes and verification_code is None:
                        verification_code = codes[0]
                elif len(table[0]) == DETAIL_COLUMNS and (
                    _is_detail_header(table[0]) or TX_RE.match(first_cell)
                ):
                    # A table continued from the previous page may arrive without its header.
                    body = table[1:] if _is_detail_header(table[0]) else table
                    for cells in body:
                        if not any(cells):
                            continue
                        n = len(rows) + 1
                        tx = collapse(cells[0])
                        if not TX_RE.match(tx):
                            raise StatementError(
                                "unreadable_row", f"Row {n}: unexpected receipt number format"
                            )
                        try:
                            ts = datetime.strptime(collapse(cells[1]), "%Y-%m-%d %H:%M:%S").replace(
                                tzinfo=EAT
                            )
                        except ValueError:
                            raise StatementError(
                                "unreadable_row", f"Row {n}: unexpected time format"
                            ) from None
                        details = collapse(cells[2])
                        kind, counterparty = classify(details)
                        rows.append(
                            Row(
                                tx=tx,
                                ts=ts,
                                details=details,
                                status=collapse(cells[3]),
                                paid_in_cents=_cents(cells[4], row=n, column="Paid In"),
                                withdrawn_cents=_cents(cells[5], row=n, column="Withdrawn"),
                                balance_cents=_cents(
                                    cells[6], row=n, column="Balance", signed=True
                                ),
                                kind=kind,
                                counterparty=counterparty,
                            )
                        )
    if not rows:
        raise StatementError("no_transactions", "No transactions were found in the statement.")

    _check_rows(rows, period_from, period_to)
    _attach_charges(rows)
    return ParsedStatement(
        source_sha256=hashlib.sha256(pdf).hexdigest(),
        pages=pages,
        period_from=period_from,
        period_to=period_to,
        rows=rows,
        summary=summary,
        verification_code=verification_code,
        integrity=score(rows, summary, signals),
    )
