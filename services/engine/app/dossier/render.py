"""The sealed dossier PDF: Joy's templates, filled only from what the approvers signed.

The render context is built from the sealed payload and the dossier's ledger rows, and the rows
are first checked to rebuild exactly the payload that was signed (same Merkle root, totals and
planned spends). So the PDF can't show a row, an amount or a name the signatures don't cover.

The PDF itself is not signed: it contains the seal's QR code, so its hash can't be signed into
it. Its SHA-256 is stored next to the seal (CRYPTO_SPEC section 5), and the verifier page lets a
sponsor check a PDF they were given against it.

Rendering is locked down: Jinja autoescapes everything except the QR code (built here by segno),
and WeasyPrint may load only files inside the templates folder and data: URIs, so a club or
supplier name containing HTML can't make the engine fetch anything.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any

import segno
from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from markupsafe import Markup

from app.approvals import payload as approval
from app.approvals.seal import approval_payload_of
from app.ingest.parse import EAT

TEMPLATES = Path(__file__).parent / "templates"
MAX_PDF_BYTES = 10 * 1024 * 1024  # matches the storage bucket's limit

CATEGORY_LABEL = {
    "transport": "Transport",
    "allowance": "Allowance",
    "meals": "Meals",
    "kit": "Kit",
    "ground_hire": "Ground hire",
    "income": "Income",
    "other": "Other",
}


class RenderError(ValueError):
    """Why a dossier PDF can't be made. The message is safe to show the user."""


# Formatting: the templates print strings and never do arithmetic --------------------------------


def kes(cents: int) -> str:
    """12345678 -> 'KES 123,456.78'; whole shillings drop the cents: 762600 -> 'KES 7,626'."""
    sign = "-" if cents < 0 else ""
    whole, rest = divmod(abs(cents), 100)
    return f"{sign}KES {whole:,}" + (f".{rest:02d}" if rest else "")


def _eat(ts: str) -> datetime:
    return datetime.fromisoformat(ts).astimezone(EAT)


def _day(d: datetime | date) -> str:
    return f"{d.day} {d:%b}"


def period_label(start: str, end: str) -> str:
    """One calendar month -> 'October 2026'; anything else -> '5 Oct – 2 Nov 2026'."""
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    if a.day == 1 and (a.year, a.month) == (b.year, b.month):
        nxt = date(b.year + (b.month == 12), b.month % 12 + 1, 1)
        if (nxt - b).days == 1:
            return f"{a:%B %Y}"
    if a.year == b.year:
        return f"{_day(a)} – {_day(b)} {b.year}"
    return f"{_day(a)} {a.year} – {_day(b)} {b.year}"


def club_short(name: str) -> str:
    """The crest: initials of the first three words, e.g. 'Nairobi City Inspectorate' -> 'NCI'."""
    words = [w for w in re.findall(r"[A-Za-z0-9]+", name) if w.upper() not in {"FC", "THE"}]
    return ("".join(w[0] for w in words[:3]) or "SP").upper()


def _paid_to(item: dict[str, Any]) -> str:
    """Never a person's name: players by pseudonym, businesses by their public number."""
    t, ref, incoming = item["cp_type"], item["cp_ref"], item["dir"] == "in"
    if t == "player":
        who = ref
    elif t in ("till", "paybill"):
        who = f"{t.capitalize()} {ref}"
    else:
        who = "an individual" if incoming else "Private individual"
    return f"From {who}" if incoming else who


# The render context ---------------------------------------------------------------------------


def _check_rows_match_seal(sealed: dict[str, Any], snapshot: dict[str, Any]) -> None:
    """The rows must rebuild the signed approval payload exactly, or nothing is rendered."""
    try:
        rebuilt, _ = approval.build(snapshot)
    except (KeyError, TypeError, ValueError):
        raise RenderError("The dossier's ledger rows are incomplete") from None
    if rebuilt != approval_payload_of(sealed):
        raise RenderError("The dossier's ledger rows don't match what was signed")


def build_context(
    sealed: dict[str, Any], snapshot: dict[str, Any], verify_base: str
) -> dict[str, Any]:
    """Everything the templates read, from a sealed payload and an approval_snapshot()."""
    _check_rows_match_seal(sealed, snapshot)
    items = sorted(snapshot["items"], key=lambda i: (_eat(i["ts"]), i["tx"]))
    totals = sealed["totals_cents"]
    income = totals.get("income", 0)
    spending = sum(v for k, v in totals.items() if k != "income")
    sealed_at = _eat(sealed["sealed_at"])
    verify_base = verify_base.rstrip("/")
    url = f"{verify_base}/{sealed['dossier_id']}"

    ledger = []
    for i in items:
        amount = kes(i["amt_cents"])
        if i["dir"] == "out" and i.get("fee_cents"):
            amount += f" + {kes(i['fee_cents'])[4:]} fee"
        ledger.append(
            {
                "date": _day(_eat(i["ts"])),
                "receipt": i["tx"],
                "category": CATEGORY_LABEL.get(i["category"], i["category"]),
                "paid_to": _paid_to(i),
                "amount": amount,
                # Every row comes from the parsed statement; a receipt photo is stronger evidence.
                # Player confirmations (attestations) aren't built yet, so "player" never appears.
                "evidence": "receipt" if i.get("receipt_sha256") else "statement",
            }
        )

    merchant_out = [i for i in items if i["branch"] == "A"]
    squad_out = [i for i in items if i["branch"] == "B"]
    to_players = [i for i in squad_out if i["cp_type"] == "player"]
    with_receipt = sum(1 for i in merchant_out if i.get("receipt_sha256"))

    by_player: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for i in to_players:
        by_player[i["cp_ref"]].append(i)
    players = [
        {
            "pseudonym": code,
            "what": " · ".join(sorted({CATEGORY_LABEL[i["category"]] for i in rows})),
            "dates": [_day(_eat(i["ts"])) for i in rows],
            "amount": kes(sum(i["amt_cents"] for i in rows)),
            "confirmed": False,  # player attestation (C5) isn't built
        }
        for code, rows in sorted(by_player.items())
    ]

    return {
        "club": {"name": sealed["club"]["name"], "short": club_short(sealed["club"]["name"])},
        "period": {"label": period_label(sealed["period"]["from"], sealed["period"]["to"])},
        "dossier": {"id": sealed["dossier_id"]},
        "sealed_at": f"{sealed_at.day} {sealed_at:%B %Y, %H:%M}",
        "sealed_at_short": f"{_day(sealed_at)} {sealed_at.year}",
        "totals": {"club_spending": kes(spending), "net_funds": kes(income - spending)},
        "rows_disclosed": sealed["rows_disclosed"],
        "integrity": {"score": f"{sealed['integrity']['score_bp'] / 100:g}"},
        "planned_spends": [
            {
                "purpose": p["purpose"],
                "till": f"{p['till']} · {p['supplier']}",
                "amount": kes(p["amt"]),
            }
            for p in sealed["planned_spends"]
        ],
        "ledger_rows": ledger,
        "coverage": {
            "receipts": f"{with_receipt} / {len(merchant_out)}",
            "players": f"0 / {len(to_players)}",
            # Squad payments that couldn't be matched to a registered player.
            "exceptions": str(len(squad_out) - len(to_players)),
        },
        "squad": {
            "players": len(by_player),
            "matchdays": len({i["fixture_code"] for i in to_players if i["fixture_code"]}),
            "total": kes(sum(i["amt_cents"] for i in to_players)),
        },
        "players": players,
        "receipts": [],  # receipt capture (C2) isn't built
        "verify_base": verify_base,
        "verify_url": url,
        "qr_svg": qr_svg(url),
        "kid": sealed["kid"],
    }


def qr_svg(url: str) -> Markup:
    """Inline SVG, the only value the templates print unescaped. Built here, never user input."""
    svg = segno.make(url, error="m", micro=False).svg_inline(
        scale=3, border=0, dark="#0a3d2a", omitsize=True
    )
    return Markup(svg)  # noqa: S704 - generated by segno from our own URL


# Rendering ------------------------------------------------------------------------------------

_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html", "j2"]),
    undefined=StrictUndefined,  # a missing field is a bug, not a blank on a sealed document
)


def render_html(context: dict[str, Any]) -> str:
    return _env.get_template("dossier.html.j2").render(**context)


def _templates_only_fetcher() -> Any:
    """A WeasyPrint fetcher for the stylesheet and fonts in the templates folder and data: URIs
    (receipt thumbnails) only. Anything else, or any failure to load, stops the render: a sealed
    document is never produced with a missing font or a silently dropped image."""
    from urllib.request import url2pathname

    from weasyprint.urls import URLFetcher

    root = TEMPLATES.resolve()

    class TemplatesOnly(URLFetcher):
        def fetch(self, url: str, headers: Any = None) -> Any:
            if url.startswith("file:"):
                path = Path(url2pathname(url.split("?")[0].removeprefix("file:"))).resolve()
                if not path.is_relative_to(root):
                    raise ValueError("The dossier may only load files from its templates folder")
            return super().fetch(url, headers)

    return TemplatesOnly(allowed_protocols=("file", "data"), fail_on_errors=True)


def render_pdf(context: dict[str, Any]) -> bytes:
    """A4 PDF bytes. WeasyPrint is imported here so the engine starts without Pango installed
    (local Windows development); the Docker image has it."""
    html = render_html(context)
    try:
        from weasyprint import HTML
        from weasyprint.urls import FatalURLFetchingError
    except OSError:  # Pango's libraries aren't installed
        raise RenderError("PDF rendering isn't available on this engine") from None
    try:
        pdf = HTML(
            string=html, base_url=TEMPLATES.as_uri() + "/", url_fetcher=_templates_only_fetcher()
        ).write_pdf()
    except FatalURLFetchingError:  # a BaseException: a font, style or image failed to load
        raise RenderError("The dossier PDF couldn't load its fonts or images") from None
    if pdf is None or len(pdf) > MAX_PDF_BYTES:
        raise RenderError("The dossier PDF couldn't be made")
    return pdf


def main(argv: list[str] | None = None) -> int:
    """Render the synthetic sample dossier: a local preview, and the CI check that rendering works
    inside the read-only container. Prints the size and page count; writes a file only if asked.

        python -m app.dossier.render              # check only
        python -m app.dossier.render out.pdf      # also save it
    """
    import io
    import json
    import sys

    import pikepdf

    from app.dossier import sample

    args = sys.argv[1:] if argv is None else argv
    snap = sample.snapshot()
    pdf = render_pdf(build_context(sample.sealed_payload(snap), snap, "https://example.org/v"))
    with pikepdf.open(io.BytesIO(pdf)) as doc:
        pages = len(doc.pages)
    if args:
        Path(args[0]).write_bytes(pdf)
    print(json.dumps({"bytes": len(pdf), "pages": pages}))
    return 0 if pages >= 4 else 1  # four sections; a long ledger takes extra sheets


if __name__ == "__main__":
    raise SystemExit(main())
