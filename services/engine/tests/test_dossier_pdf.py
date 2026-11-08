"""The sealed dossier PDF: the render context, the locked-down renderer and the endpoints.

Rendering needs Pango, which the Docker image and CI have and a plain Windows machine doesn't.
Those tests skip locally, and fail in CI rather than skip, so rendering can't quietly go untested.
"""

from __future__ import annotations

import copy
import hashlib
import io
import os

import pikepdf
import pytest

from app.dossier import render, sample
from app.dossier.render import RenderError, build_context, club_short, kes, period_label
from tests.test_approvals import CAPTAIN, DOSSIER, KEY, MANAGER, OUTSIDER, post
from tests.test_seal import FAKE_PDF, approve, approved_but_unsealed, engine  # noqa: F401

BASE = "https://example.org/v"
EVIL = '<img src="http://169.254.169.254/latest/meta-data/">Lionesses'


def context(snap=None, sealed=None):
    snap = snap or sample.snapshot()
    return build_context(sealed or sample.sealed_payload(snap), snap, BASE)


def needs_pango() -> None:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        if os.environ.get("CI"):
            raise
        pytest.skip("Pango isn't installed here; this runs in Docker and CI")


# Formatting -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("cents", "text"),
    [(762600, "KES 7,626"), (12345678, "KES 123,456.78"), (5, "KES 0.05"), (-150000, "-KES 1,500")],
)
def test_money_is_cents_shown_as_shillings(cents, text) -> None:
    assert kes(cents) == text


@pytest.mark.parametrize(
    ("start", "end", "label"),
    [
        ("2026-10-01", "2026-10-31", "October 2026"),
        ("2026-12-01", "2026-12-31", "December 2026"),
        ("2026-10-05", "2026-11-02", "5 Oct – 2 Nov 2026"),
        ("2026-10-01", "2026-10-30", "1 Oct – 30 Oct 2026"),
        ("2026-12-20", "2027-01-05", "20 Dec 2026 – 5 Jan 2027"),
    ],
)
def test_period_labels(start, end, label) -> None:
    assert period_label(start, end) == label


def test_the_crest_uses_initials() -> None:
    assert club_short("Nairobi City Inspectorate Lionesses") == "NCI"
    assert club_short("Synthetic Lionesses FC") == "SL"


# What the PDF says ------------------------------------------------------------------------------


def test_totals_come_from_the_sealed_payload() -> None:
    c = context()
    assert c["totals"] == {"club_spending": "KES 25,479", "net_funds": "KES 24,521"}
    assert c["rows_disclosed"] == 22
    assert c["integrity"]["score"] == "95"
    assert c["sealed_at_short"] == "1 Nov 2026"


def test_the_pdf_never_names_a_person() -> None:
    paid_to = {r["paid_to"] for r in context()["ledger_rows"]}
    assert "P01" in paid_to and "Private individual" in paid_to
    assert not any("hmac" in p for p in paid_to)  # the keyed hash isn't printed either


def test_income_says_where_it_came_from() -> None:
    assert context()["ledger_rows"][0]["paid_to"] == "From Paybill 400200"


@pytest.mark.parametrize(
    ("direction", "text"), [("in", "From an individual"), ("out", "Private individual")]
)
def test_individuals_read_naturally_both_ways(direction, text) -> None:
    row = {"cp_type": "person", "cp_ref": "hmac:x", "dir": direction}
    assert render._paid_to(row) == text


def test_no_matched_players_shows_one_message_not_an_empty_grid() -> None:
    c = context(sample.snapshot(players=False))
    assert c["players"] == [] and c["squad"]["players"] == 0
    assert c["coverage"]["exceptions"] == "19"  # 18 unmatched fares and the meal
    html = render.render_html(c)
    assert "No payments to registered players in this period." in html
    assert 'class="squad-grid"' not in html


def test_only_what_exists_is_claimed() -> None:
    c = context()
    assert {r["evidence"] for r in c["ledger_rows"]} == {"statement", "receipt"}
    assert all(p["confirmed"] is False for p in c["players"])
    assert c["coverage"] == {"receipts": "1 / 2", "players": "0 / 18", "exceptions": "1"}
    assert c["squad"] == {"players": 6, "matchdays": 3, "total": "KES 9,000"}
    html = render.render_html(c)
    assert "Awaiting confirmation" in html and "</span> Confirmed" not in html
    assert "No receipt photos are attached" in html
    assert "redacted before sealing" not in html  # true only once receipts exist


@pytest.mark.parametrize(
    "tamper",
    [
        lambda s: s["items"][0].__setitem__("amt_cents", s["items"][0]["amt_cents"] + 1),
        lambda s: s["items"].pop(),
        lambda s: s["items"][3].__setitem__("cp_ref", "P99"),
        lambda s: s["planned_spends"].pop(),
    ],
)
def test_rows_that_dont_match_the_seal_are_never_rendered(tamper) -> None:
    snap = sample.snapshot()
    sealed = sample.sealed_payload(snap)
    changed = copy.deepcopy(snap)
    tamper(changed)
    with pytest.raises(RenderError, match="don't match"):
        build_context(sealed, changed, BASE)


def test_a_club_renamed_after_signing_doesnt_match_the_seal() -> None:
    snap = sample.snapshot()
    sealed = sample.sealed_payload(snap)
    with pytest.raises(RenderError, match="don't match"):
        build_context(sealed, sample.snapshot("Renamed After Signing"), BASE)


# The template ---------------------------------------------------------------------------------


def test_one_document_with_four_sections() -> None:
    html = render.render_html(context())
    assert html.count("<!doctype") == 1 and html.count('class="page"') == 4
    assert f"{BASE}/{sample.DOSSIER_ID}" in html


def test_user_typed_text_is_escaped() -> None:
    snap = sample.snapshot(EVIL)
    snap["planned_spends"][0]["purpose"] = "<script>alert(1)</script>"
    html = render.render_html(context(snap))
    assert "<img" not in html and "<script" not in html and "&lt;img" in html


def test_only_the_qr_code_is_raw_svg() -> None:
    assert render.render_html(context()).count("<svg") == 1


def test_a_missing_field_is_an_error_not_a_blank() -> None:
    c = context()
    del c["kid"]
    with pytest.raises(Exception, match="kid"):
        render.render_html(c)


# Rendering (needs Pango) ------------------------------------------------------------------------


def test_renders_a4_with_the_embedded_fonts() -> None:
    needs_pango()
    pdf = render.render_pdf(context())
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        assert len(doc.pages) >= 4
        box = [float(v) for v in doc.pages[0].mediabox]
        assert round(box[2]) == 595 and round(box[3]) == 842
        fonts = {
            str(f.get("/BaseFont"))
            for page in doc.pages
            for f in page.Resources["/Font"].as_dict().values()
        }
    assert any("Plex" in f for f in fonts) and any("Barlow" in f for f in fonts)


def test_the_empty_squad_message_is_one_line_in_the_pdf() -> None:
    # As a grid item it rendered a word per line (seen on the live demo dossier).
    needs_pango()
    import pypdfium2

    pdf = pypdfium2.PdfDocument(render.render_pdf(context(sample.snapshot(players=False))))
    lines = [
        line.strip()
        for i in range(len(pdf))
        for line in pdf[i].get_textpage().get_text_range().splitlines()
    ]
    assert "No payments to registered players in this period." in lines


def test_a_club_name_with_html_renders_safely() -> None:
    needs_pango()
    assert render.render_pdf(context(sample.snapshot(EVIL))).startswith(b"%PDF")


@pytest.mark.parametrize(
    "url", ["http://169.254.169.254/latest/meta-data/", "https://example.org/x.png", "ftp://x/y"]
)
def test_the_network_is_refused(url) -> None:
    needs_pango()
    with pytest.raises(ValueError, match="disallowed protocol"):
        render._templates_only_fetcher().fetch(url)


def test_files_outside_the_templates_folder_are_refused() -> None:
    needs_pango()
    fetcher = render._templates_only_fetcher()
    with pytest.raises(ValueError, match="templates folder"):
        fetcher.fetch("file:///etc/passwd")
    with pytest.raises(ValueError, match="templates folder"):
        fetcher.fetch((render.TEMPLATES / ".." / ".." / "main.py").resolve().as_uri())
    assert fetcher.fetch((render.TEMPLATES / "dossier.css").as_uri()).read()


def test_a_missing_stylesheet_stops_the_render(monkeypatch) -> None:
    needs_pango()
    c = context()
    html = render.render_html(c).replace("dossier.css", "missing.css")
    monkeypatch.setattr(render, "render_html", lambda _: html)
    with pytest.raises(RenderError, match="fonts or images"):
        render.render_pdf(c)


# Sealing and the endpoints ----------------------------------------------------------------------

SHA = hashlib.sha256(FAKE_PDF).hexdigest()
PDF_URL = f"/v1/dossiers/{DOSSIER}/pdf"


def get(client, actor):
    return client.get(PDF_URL, headers={"X-Internal-Key": KEY, "X-Actor-Id": actor})


def test_sealing_stores_the_pdf_and_records_its_hash(engine) -> None:  # noqa: F811
    client, db, _ = engine
    r = approve(client)
    assert r.json()["status"] == "sealed" and r.json()["pdf_sha256"] == SHA
    assert db.pdf_sha256 == SHA
    assert db.pdf_path == f"{db.content['dossier']['club_id']}/{DOSSIER}/{SHA}.pdf"
    assert db.files[db.pdf_path] == FAKE_PDF
    assert db.sealed["p_pdf_path"] is None  # attached afterwards, by the one code path


def test_a_failed_render_never_blocks_the_seal_and_can_be_retried(
    engine,  # noqa: F811
    monkeypatch,
) -> None:
    client, db, _ = engine

    def broken(context):
        raise RenderError("PDF rendering isn't available on this engine")

    monkeypatch.setattr(render, "render_pdf", broken)
    r = approve(client)
    assert r.json()["status"] == "sealed" and db.status == "sealed"
    assert "isn't available" in r.json()["pdf_error"] and db.pdf_sha256 is None

    monkeypatch.setattr(render, "render_pdf", lambda context: FAKE_PDF)
    r = post(client, PDF_URL, {}, MANAGER)
    assert r.status_code == 200 and r.json() == {"pdf_sha256": SHA} and db.pdf_sha256 == SHA


def test_making_the_pdf_twice_keeps_the_first(engine, monkeypatch) -> None:  # noqa: F811
    client, db, _ = engine
    approve(client)
    monkeypatch.setattr(render, "render_pdf", lambda context: b"%PDF-different bytes")
    r = post(client, PDF_URL, {}, MANAGER)
    assert r.json() == {"pdf_sha256": SHA} and len(db.files) == 1


def test_losing_a_race_returns_the_winners_pdf(engine, monkeypatch) -> None:  # noqa: F811
    client, db, _ = engine
    approve(client)
    db.pdf_path, db.pdf_sha256 = None, None
    original = db.attach_dossier_pdf

    def raced(p):
        original({**p, "p_pdf_path": "winner.pdf", "p_pdf_sha256": "ab" * 32})
        return original(p)

    monkeypatch.setattr(db, "attach_dossier_pdf", raced)
    r = post(client, PDF_URL, {}, MANAGER)
    assert r.status_code == 200 and r.json() == {"pdf_sha256": "ab" * 32}


def test_only_a_sealed_dossier_gets_a_pdf(engine) -> None:  # noqa: F811
    client, db, app = engine
    approved_but_unsealed(client, db, app)
    r = post(client, PDF_URL, {}, MANAGER)
    assert r.status_code == 409 and db.files == {}


@pytest.mark.parametrize(("actor", "status"), [(CAPTAIN, 403), (OUTSIDER, 404)])
def test_only_approvers_can_make_the_pdf(engine, actor, status) -> None:  # noqa: F811
    client, _, _ = engine
    approve(client)
    assert post(client, PDF_URL, {}, actor).status_code == status


def test_club_members_can_download_it(engine) -> None:  # noqa: F811
    client, _, _ = engine
    approve(client)
    r = get(client, CAPTAIN)
    assert r.status_code == 200 and r.content == FAKE_PDF
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["cache-control"] == "no-store"
    assert f"securepitch-dossier-{DOSSIER}.pdf" in r.headers["content-disposition"]


def test_outsiders_cant_tell_a_dossier_exists(engine) -> None:  # noqa: F811
    client, _, _ = engine
    approve(client)
    r = get(client, OUTSIDER)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "not_found"


def test_a_file_changed_in_storage_is_never_handed_out(engine) -> None:  # noqa: F811
    client, db, _ = engine
    approve(client)
    db.files[db.pdf_path] = b"%PDF-tampered"
    r = get(client, MANAGER)
    assert r.status_code == 502 and r.json()["detail"]["code"] == "pdf_mismatch"


def test_no_pdf_yet(engine) -> None:  # noqa: F811
    client, db, app = engine
    approved_but_unsealed(client, db, app)
    r = get(client, MANAGER)
    assert r.status_code == 404 and r.json()["detail"]["code"] == "no_pdf"
