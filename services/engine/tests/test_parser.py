"""Statement parser tests. Synthetic statements only, plus one optional local-only test that runs
against a real statement in fixtures/private/ when present (never in CI) and asserts counts only."""

from __future__ import annotations

import builtins
import io
import tempfile
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pikepdf
import pytest
from fastapi.testclient import TestClient
from reportlab.pdfgen import canvas

from app.dossiers import Tag, build_items
from app.ingest.classify import classify, name_tokens
from app.ingest.integrity import WEIGHTS, PdfSignals, score
from app.ingest.models import Kind
from app.ingest.parse import StatementError, parse_statement
from app.main import create_app
from tests.fakes.statement import (
    PASSWORD,
    Tx,
    build_statement,
    lionesses_month,
    removed_row,
    summary_of,
    tampered_amount,
    with_balances,
)

KEY = "test-key-that-is-long-enough-for-the-engine-1234"


def _code(pdf: bytes, password: str = PASSWORD) -> str:
    with pytest.raises(StatementError) as err:
        parse_statement(pdf, password)
    return err.value.code


def test_too_many_pages_is_refused_before_parsing(month, monkeypatch) -> None:
    monkeypatch.setattr("app.ingest.parse.MAX_PAGES", 1)
    assert _code(build_statement(month)) == "too_many_pages"


@pytest.mark.parametrize(
    "plant",
    [
        lambda doc: setattr(doc.Root, "OpenAction", pikepdf.Dictionary(S=pikepdf.Name.JavaScript)),
        lambda doc: setattr(doc.Root, "AA", pikepdf.Dictionary()),
        lambda doc: setattr(doc.Root, "Names", pikepdf.Dictionary(JavaScript=pikepdf.Dictionary())),
        lambda doc: setattr(
            doc.Root, "Names", pikepdf.Dictionary(EmbeddedFiles=pikepdf.Dictionary())
        ),
        # Page-level actions: one on the last page, where a first-page-only check would miss it.
        lambda doc: setattr(doc.pages[-1].obj, "AA", pikepdf.Dictionary(O=_js())),
        lambda doc: _annotate(doc, A=_js()),
        lambda doc: _annotate(doc, A=pikepdf.Dictionary(S=pikepdf.Name.Launch)),
        lambda doc: _annotate(doc, AA=pikepdf.Dictionary(E=_js())),
        lambda doc: _annotate(doc, Subtype=pikepdf.Name.FileAttachment),
    ],
)
def test_scripts_and_attachments_are_refused(month, plant) -> None:
    with pikepdf.open(io.BytesIO(build_statement(month)), password=PASSWORD) as doc:
        plant(doc)
        out = io.BytesIO()
        doc.save(out)
    assert _code(out.getvalue()) == "active_content"


def _js() -> pikepdf.Dictionary:
    return pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)"))


def _annotate(doc: pikepdf.Pdf, **fields) -> None:
    annot = pikepdf.Dictionary(
        Type=pikepdf.Name.Annot, Subtype=pikepdf.Name.Link, Rect=[0, 0, 10, 10]
    )
    for key, value in fields.items():
        annot[f"/{key}"] = value
    doc.pages[-1].obj.Annots = doc.make_indirect(pikepdf.Array([doc.make_indirect(annot)]))


def test_a_plain_link_is_a_warning_not_a_refusal(month) -> None:
    with pikepdf.open(io.BytesIO(build_statement(month)), password=PASSWORD) as doc:
        _annotate(
            doc, A=pikepdf.Dictionary(S=pikepdf.Name.URI, URI=pikepdf.String("https://x.test"))
        )
        out = io.BytesIO()
        doc.save(out)
    parsed = parse_statement(out.getvalue(), PASSWORD)
    assert not parsed.integrity.checks["no_annotations_or_forms"].passed


def test_two_transactions_with_one_receipt_are_refused(month) -> None:
    copy = next(t for t in month if t.paid_in)
    twice = with_balances([*month, replace(copy, ts=month[-1].ts)], _opening(month))
    assert _code(build_statement(twice)) == "duplicate_receipt"


def test_rows_outside_the_statement_period_are_refused(month) -> None:
    moved = with_balances(
        [*month, Tx("SJZ0000001", datetime(2026, 11, 2, 9), "Airtime Purchase", withdrawn=100)],
        _opening(month),
    )
    assert _code(build_statement(moved)) == "rows_outside_period"


def _opening(month) -> int:
    return month[0].balance - month[0].paid_in + month[0].withdrawn


@pytest.fixture(scope="module")
def month():
    return lionesses_month()


@pytest.fixture(scope="module")
def parsed(month):
    return parse_statement(build_statement(month), PASSWORD)


# ---- classification -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("details", "kind", "cp_type"),
    [
        ("Customer Transfer to - 254712***789 JANE WANJIKU", Kind.P2P_OUT, "person"),
        ("Customer Transfer to - 0712***789 Jane Wanjiku", Kind.P2P_OUT, "person"),
        (
            "Customer Payment to Small Business to - 254733***303 Peter Kamau",
            Kind.POCHI_OUT,
            "person",
        ),
        ("Funds received from - 254722***202 Well Wisher", Kind.P2P_IN, "person"),
        ("Merchant Payment to 5123456 - MAMA MBOGA KIOSK", Kind.TILL, "till"),
        ("Merchant Payment Online to 5123456 - SHOP", Kind.TILL, "till"),
        ("Pay Bill Online to 888880 - KPLC PREPAID Acc. SYN0000001", Kind.PAYBILL, "paybill"),
        ("Pay Bill to 400200 - BANK PAYBILL Acc. 123456", Kind.PAYBILL, "paybill"),
        (
            "Business Payment from 300300 - SYNTHETIC Bulk Account via SYN Original",
            Kind.B2C_IN,
            "business",
        ),
        ("Customer Transfer of Funds Charge", Kind.CHARGE, "none"),
        ("Pay Bill Charge", Kind.CHARGE, "none"),
        ("Airtime Purchase", Kind.AIRTIME, "none"),
        ("Customer Bundle Purchase to 100000SYN POSTPAID by - 254744***404 X", Kind.BUNDLE, "none"),
        ("Something Safaricom adds next year", Kind.OTHER, "none"),
    ],
)
def test_classify(details: str, kind: Kind, cp_type: str) -> None:
    got_kind, cp = classify(details)
    assert (got_kind, cp.type) == (kind, cp_type)


def test_both_mask_formats_give_the_same_key() -> None:
    _, international = classify("Customer Transfer to - 254712***789 JANE WANJIKU")
    _, local = classify("Customer Transfer to - 0712***789 Jane Wanjiku")
    assert international.mask_key == local.mask_key == "0712|789"
    assert name_tokens(international.name) == name_tokens(local.name) == ("jane", "wanjiku")


def test_paybill_account_and_numbers() -> None:
    _, cp = classify("Pay Bill Online to 888880 - KPLC PREPAID Acc. SYN0000001")
    assert (cp.number, cp.name, cp.account) == ("888880", "KPLC PREPAID", "SYN0000001")


# ---- parsing a synthetic statement --------------------------------------------------------


def test_every_row_is_read_newest_first(month, parsed) -> None:
    assert len(parsed.rows) == len(month)
    assert [r.tx for r in parsed.rows] == [t.tx for t in reversed(month)]
    assert parsed.pages > 1  # the detail table really spans pages


def test_amounts_times_and_header_fields(month, parsed) -> None:
    by_tx = {r.tx: r for r in parsed.rows}
    for t in month:
        r = by_tx[t.tx]
        assert (r.paid_in_cents, r.withdrawn_cents, r.balance_cents) == (
            t.paid_in,
            t.withdrawn,
            t.balance,
        )
        assert r.ts.utcoffset() == timedelta(hours=3)
        assert r.ts.replace(tzinfo=None) == t.ts
    assert (parsed.period_from.isoformat(), parsed.period_to.isoformat()) == (
        "2026-10-01",
        "2026-10-31",
    )
    assert parsed.verification_code == "SYN1CODE"


def test_charges_attach_to_their_transfer_in_either_order(parsed) -> None:
    charges = [r for r in parsed.rows if r.kind is Kind.CHARGE]
    assert charges and all(c.fee_of for c in charges)
    first = next(r for r in parsed.rows if r.tx == "SJA0000001")  # printed after its charge
    assert (first.fee_cents, first.fee_txs) == (1300, ["SJA0000002"])
    fare = [r for r in parsed.rows if r.kind is Kind.P2P_OUT and r.amount_cents == 25000]
    assert len(fare) == 18 and all(r.fee_cents == 700 for r in fare)


def test_tables_without_repeated_headers_lose_no_rows(month) -> None:
    p = parse_statement(build_statement(month, repeat_header=False), PASSWORD)
    assert len(p.rows) == len(month)


# ---- integrity ----------------------------------------------------------------------------


def test_weights_add_up_to_10000() -> None:
    assert sum(WEIGHTS.values()) == 10000


def test_synthetic_statement_fails_only_the_producer_check(parsed) -> None:
    failed = [k for k, c in parsed.integrity.checks.items() if not c.passed]
    assert failed == ["producer_baseline"]
    assert parsed.integrity.score_bp == 10000 - WEIGHTS["producer_baseline"]
    assert "before reordering" in parsed.integrity.checks["balance_chain"].detail
    assert not parsed.integrity.checks["balance_chain"].detail.startswith(
        "0 break(s) in 46 links (0"
    )


@pytest.mark.parametrize("tamper", [tampered_amount, removed_row])
def test_edited_statements_break_the_chain_and_the_summary(month, tamper) -> None:
    # The statement's printed summary stays as Safaricom issued it; only the rows were edited.
    p = parse_statement(build_statement(tamper(month), summary=summary_of(month)), PASSWORD)
    assert not p.integrity.checks["balance_chain"].passed
    assert not p.integrity.checks["summary_match"].passed


def test_an_edited_summary_is_caught_on_its_own(month) -> None:
    summary = summary_of(month)
    summary["TOTAL"] = (summary["TOTAL"][0] + 100000, summary["TOTAL"][1])
    p = parse_statement(build_statement(month, summary=summary), PASSWORD)
    assert p.integrity.checks["balance_chain"].passed
    assert not p.integrity.checks["summary_match"].passed


def test_resaved_and_annotated_files_lose_points(parsed) -> None:
    resaved = PdfSignals(
        eof_markers=2,
        has_prev_trailer=True,
        annotations=1,
        has_form=True,
        producer="OpenPDF 1.3",
        fonts=(),
    )
    result = score(parsed.rows, parsed.summary, resaved)
    assert not result.checks["never_resaved"].passed
    assert not result.checks["no_annotations_or_forms"].passed
    assert result.checks["producer_baseline"].passed


def test_check_details_never_contain_statement_contents(parsed) -> None:
    text = " ".join(c.detail for c in parsed.integrity.checks.values())
    for r in parsed.rows:
        assert r.tx not in text
        if r.counterparty.name:
            assert r.counterparty.name not in text


# ---- errors -------------------------------------------------------------------------------


def test_wrong_password(month) -> None:
    with pytest.raises(StatementError) as err:
        parse_statement(build_statement(month), "000000")
    assert err.value.code == "wrong_password"


def test_not_a_pdf() -> None:
    with pytest.raises(StatementError) as err:
        parse_statement(b"hello", "")
    assert err.value.code == "not_a_pdf"


def test_a_pdf_that_is_not_a_statement() -> None:
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 720, "Minutes of the committee meeting")
    c.save()
    with pytest.raises(StatementError) as err:
        parse_statement(buf.getvalue(), "")
    assert err.value.code == "not_a_statement"


# ---- memory only --------------------------------------------------------------------------


def test_parsing_never_writes_to_disk(month, monkeypatch) -> None:
    pdf = build_statement(month)
    real_open = builtins.open

    def read_only_open(file, mode="r", *args, **kwargs):
        if any(flag in mode for flag in "wax+"):
            raise AssertionError(f"parser tried to write a file ({mode!r})")
        return real_open(file, mode, *args, **kwargs)

    def no_temp(*args, **kwargs):
        raise AssertionError("parser tried to create a temporary file")

    monkeypatch.setattr(builtins, "open", read_only_open)
    for name in (
        "TemporaryFile",
        "NamedTemporaryFile",
        "SpooledTemporaryFile",
        "mkstemp",
        "mkdtemp",
    ):
        monkeypatch.setattr(tempfile, name, no_temp)
    assert len(parse_statement(pdf, PASSWORD).rows) == len(month)


# ---- HTTP endpoint ------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setenv("ENGINE_INTERNAL_KEY", KEY)
    return TestClient(create_app())


def _post(client, body: bytes, *, password=PASSWORD, key=KEY, ctype="application/pdf"):
    return client.post(
        "/v1/statements/parse",
        content=body,
        headers={"X-Internal-Key": key, "X-Statement-Password": password, "Content-Type": ctype},
    )


def test_endpoint_returns_transactions_and_integrity(client, month) -> None:
    r = _post(client, build_statement(month))
    assert r.status_code == 200
    data = r.json()
    assert data["rows_total"] == len(month)
    assert data["integrity"]["score_bp"] == 9500
    kinds = {t["kind"] for t in data["transactions"]}
    assert "charge" not in kinds  # all charges were folded into their transactions
    fare = [t for t in data["transactions"] if t["amount_cents"] == 25000]
    assert len(fare) == 18 and all(t["fee_cents"] == 700 for t in fare)
    assert all(t["counterparty"]["mask_key"] for t in fare)


def test_endpoint_rejects_wrong_password_with_a_code(client, month) -> None:
    r = _post(client, build_statement(month), password="000000")  # noqa: S106 - deliberately wrong
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "wrong_password"


def test_endpoint_requires_pdf_content_type(client, month) -> None:
    assert _post(client, build_statement(month), ctype="multipart/form-data").status_code == 415


def test_endpoint_requires_the_internal_key(client, month) -> None:
    assert _post(client, build_statement(month), key="wrong").status_code == 401


# ---- optional: a real statement (local only, never in CI) ---------------------------------

PRIVATE = Path(__file__).resolve().parents[3] / "fixtures" / "private"


def _real_statement() -> tuple[bytes, str] | None:
    pdfs = sorted(PRIVATE.glob("*.pdf"))
    env = PRIVATE / "statements.env"
    if not pdfs or not env.exists():
        return None
    entries = dict(
        line.split("=", 1) for line in env.read_text(encoding="utf-8").splitlines() if "=" in line
    )
    password = entries.get(pdfs[0].name) or (
        next(iter(entries.values())) if len(entries) == 1 else None
    )
    return (pdfs[0].read_bytes(), password.strip()) if password else None


@pytest.mark.skipif(_real_statement() is None, reason="no real statement in fixtures/private/")
def test_real_statement_parses_with_a_clean_integrity_score() -> None:
    pdf, password = _real_statement()  # type: ignore[misc]
    p = parse_statement(pdf, password)
    assert p.rows
    assert sum(r.kind is Kind.OTHER for r in p.rows) == 0
    assert p.integrity.checks["balance_chain"].passed
    assert p.integrity.checks["summary_match"].passed
    assert p.integrity.checks["never_resaved"].passed
    assert all(r.fee_of for r in p.rows if r.kind is Kind.CHARGE)
    tags = [
        Tag(r.tx, "income" if r.direction == "in" else "other")
        for r in p.rows
        if r.kind is not Kind.CHARGE and r.amount_cents > 0
    ]
    assert len(build_items(p.rows, tags, {}, [], set(), b"k" * 32)) == len(tags)


# ---- PR review regressions ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("details", "kind"),
    [
        ("Merchant Payment to 5123456 - FAST CHARGE", Kind.TILL),  # name ends in "Charge"
        ("Merchant Payment Online to 5123456 - IN CHARGE SALON", Kind.TILL),
        ("Pay Bill Online to 888880 - SUPER CHARGE Acc. 1", Kind.PAYBILL),
        ("Merchant Payment to 81234567 - NEW TILL", Kind.TILL),  # 8-digit till
        ("Pay Bill Online to 40012345 - X Acc. 1", Kind.PAYBILL),  # 8-digit paybill
        ("Customer Transfer of Funds Charge", Kind.CHARGE),
        ("Pay Bill Charge", Kind.CHARGE),
    ],
)
def test_classification_review_cases(details: str, kind: Kind) -> None:
    assert classify(details)[0] is kind


@pytest.mark.parametrize(
    ("cell", "cents"),
    [("- 250.00", 25000), ("-\xa0250.00", 25000), ("1 250.00", 125000), (" 1,250.00 ", 125000)],
)
def test_amounts_tolerate_spaces(cell: str, cents: int) -> None:
    from app.ingest.parse import _cents

    assert _cents(cell, row=1, column="Withdrawn") == cents


def test_period_tolerates_space_before_colon() -> None:
    from app.ingest.parse import _period

    assert _period("Statement Period : 01 Oct 2026 - 31 Oct 2026")[0].isoformat() == "2026-10-01"


def test_each_same_second_transfer_gets_its_own_fee() -> None:
    from datetime import datetime

    from app.ingest.models import Counterparty, Row
    from app.ingest.parse import EAT, _attach_charges

    ts = datetime(2026, 10, 17, 7, 15, tzinfo=EAT)
    person = Counterparty("person")
    rows = [
        Row("SJT0000001", ts, "x", "Completed", 0, 25000, 0, Kind.P2P_OUT, person),
        Row("SJT0000002", ts, "x", "Completed", 0, 30000, 0, Kind.P2P_OUT, person),
        Row("SJC0000001", ts, "x", "Completed", 0, 700, 0, Kind.CHARGE),
        Row("SJC0000002", ts, "x", "Completed", 0, 700, 0, Kind.CHARGE),
    ]
    _attach_charges(rows)
    assert [r.fee_cents for r in rows[:2]] == [700, 700]


def test_empty_pdf_is_unreadable() -> None:
    out = io.BytesIO()
    pikepdf.new().save(out)
    with pytest.raises(StatementError) as err:
        parse_statement(out.getvalue(), "")
    assert err.value.code == "unreadable_pdf"


def test_malformed_page_resources_do_not_crash_the_scan() -> None:
    from app.ingest.parse import _pdf_signals

    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.pages[0].obj["/Resources"] = pikepdf.Array([1, 2])  # not a dictionary
    pdf.pages[0].obj["/Annots"] = pikepdf.Name("/Bogus")  # not an array
    signals = _pdf_signals(b"%%EOF", pdf)
    assert (signals.annotations, signals.fonts) == (0, ())


def test_reader_failures_become_unreadable_pdf_not_500(month, monkeypatch, client) -> None:
    import pdfplumber

    def broken(*args, **kwargs):
        raise KeyError("/Font")  # e.g. pdfminer on a malformed font dictionary

    monkeypatch.setattr(pdfplumber, "open", broken)
    with pytest.raises(StatementError) as err:
        parse_statement(build_statement(month), PASSWORD)
    assert err.value.code == "unreadable_pdf"
    r = _post(client, build_statement(month))
    assert r.status_code == 422 and r.json()["detail"]["code"] == "unreadable_pdf"
