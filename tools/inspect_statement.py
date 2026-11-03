# /// script
# requires-python = ">=3.12"
# dependencies = ["pdfplumber>=0.11", "pikepdf>=9"]
# ///
"""Print the STRUCTURE of an M-Pesa statement PDF without revealing what's in it.

    uv run tools/inspect_statement.py fixtures/private/<file>.pdf

The password is read from fixtures/private/statements.env (`<filename>=<password>`).
Output is safe to share: digits become 9, capitalised words (names, businesses) become X,
amounts are reduced to their shape, and checks are reported as counts. Nothing is written
to disk.
"""

from __future__ import annotations

import io
import re
import sys
from collections import Counter
from decimal import Decimal, InvalidOperation
from itertools import permutations
from pathlib import Path

import pdfplumber
import pikepdf

# The ONLY words ever printed: fixed M-Pesa statement vocabulary. Every other word (names,
# businesses, anything unexpected) becomes X, so a new kind of row can't leak a name.
SAFE_WORDS = {
    "m-pesa",
    "mpesa",
    "safaricom",
    "summary",
    "detailed",
    "statement",
    "transaction",
    "type",
    "paid",
    "in",
    "out",
    "total",
    "send",
    "money",
    "received",
    "agent",
    "deposit",
    "withdrawal",
    "lipa",
    "na",
    "paybill",
    "buy",
    "goods",
    "others",
    "customer",
    "name",
    "mobile",
    "number",
    "email",
    "address",
    "period",
    "request",
    "date",
    "receipt",
    "no",
    "completion",
    "time",
    "details",
    "status",
    "balance",
    "withdrawn",
    "completed",
    "failed",
    "pending",
    "transfer",
    "of",
    "funds",
    "charge",
    "to",
    "from",
    "payment",
    "small",
    "business",
    "merchant",
    "pay",
    "bill",
    "online",
    "acc",
    "bundle",
    "purchase",
    "postpaid",
    "prepaid",
    "by",
    "airtime",
    "original",
    "conversation",
    "is",
    "via",
    "account",
    "offers",
    "page",
    "verification",
    "code",
    "verify",
    "the",
    "validity",
    "this",
    "dial",
    "select",
    "my",
    "and",
    "follow",
    "prompts",
    "enter",
    "reversal",
    "fuliza",
    "overdraft",
    "repayment",
    "loan",
    "withdraw",
    "cash",
    "till",
    "bulk",
    "for",
    "with",
    "at",
    "on",
    "tokens",
    "kplc",
    "pochi",
    "la",
    "biashara",
    "reversed",
    "promotion",
    "bank",
    "b2c",
    "c2b",
    "b2b",
}


def is_detail_header(row: list[str | None]) -> bool:
    """True for the detail table's header row ("Receipt No. | Completion Time | ...")."""
    return (row[0] or "").strip().lower().startswith("receipt")


def mask(text: str | None) -> str:
    """Keep the shape and known statement wording of text; hide everything else."""
    if not text:
        return ""
    out = []
    for token in text.replace("\n", " / ").split():
        bare = token.strip(".,:;()'\"").lower()
        if "@" in token:
            out.append("<email>")
        elif any(c.isdigit() for c in token):
            out.append(re.sub(r"\d", "9", re.sub(r"[A-Za-z]", "A", token)))
        elif not bare or bare in SAFE_WORDS or not any(c.isalpha() for c in bare):
            out.append(token)
        else:
            out.append("X")
    return " ".join(out)


def money(cell: str | None) -> int | None:
    """'1,234.50' -> 123450 cents; blank -> None."""
    if not cell or not cell.strip():
        return None
    try:
        return int(Decimal(cell.replace(",", "").strip()) * 100)
    except InvalidOperation:
        return None


def password_for(pdf: Path) -> str | None:
    """Find the password: exact filename, then without .pdf / ignoring case, then the only entry."""
    env = pdf.parent / "statements.env"
    if not env.exists():
        return None
    entries = {}
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        name, sep, value = line.partition("=")
        if sep and name.strip():
            entries[name.strip()] = value.strip()
    for key, value in entries.items():
        if key == pdf.name:
            return value
    for key, value in entries.items():
        if key.lower() in (pdf.name.lower(), pdf.stem.lower()):
            return value
    if len(entries) == 1 and len(list(pdf.parent.glob("*.pdf"))) == 1:
        print("note: statements.env key doesn't match the filename; using its only entry")
        return next(iter(entries.values()))
    return None


def main(path: str) -> None:
    pdf_path = Path(path)
    raw = pdf_path.read_bytes()
    password = password_for(pdf_path) or ""
    # The filename is never printed: statements are often saved with the holder's name and
    # number in it, and masking digits alone would still show the name.
    print(f"file: <name redacted>.pdf  ({len(raw):,} bytes)")
    try:
        pikepdf.open(io.BytesIO(raw), password=password).close()
    except pikepdf.PasswordError:
        sys.exit(
            "Couldn't open the statement: its password is missing or wrong.\n"
            "Add a line   <exact PDF filename>=<password>   to statements.env in the same folder\n"
            "as the PDF (keep both inside fixtures/private/, which git ignores)."
        )

    # Structure and tamper signals (pikepdf) ---------------------------------------------------
    with pikepdf.open(io.BytesIO(raw), password=password) as doc:
        print(
            f"pdf version: {doc.pdf_version}, pages: {len(doc.pages)}, "
            f"encrypted: {doc.is_encrypted}"
        )
        if doc.is_encrypted:
            enc = doc.encryption
            print(
                f"encryption: R{enc.R} V{enc.V} stream={enc.stream_method.name} "
                f"string={enc.string_method.name} bits={enc.bits}"
            )
        info = {k: str(v) for k, v in doc.docinfo.items()} if doc.docinfo else {}
        for key in ("/Producer", "/Creator"):
            print(f"{key[1:].lower()}: {mask(info.get(key)) or '(none)'}")
        created, modified = info.get("/CreationDate"), info.get("/ModDate")
        print(
            f"creation date present: {bool(created)}, mod date present: {bool(modified)}, "
            f"equal: {created == modified if created and modified else 'n/a'}"
        )
        print(f"%%EOF markers (1 = never re-saved incrementally): {raw.count(b'%%EOF')}")
        print(f"xref sections: {raw.count(b'startxref')}, trailer /Prev present: {b'/Prev' in raw}")
        annots = sum(len(p.get("/Annots", [])) for p in doc.pages)
        print(f"annotations: {annots}, form fields: {'/AcroForm' in doc.Root}")
        fonts = set()
        for page in doc.pages:
            res = page.get("/Resources", {})
            for font in res.get("/Font", {}).values():
                fonts.add(str(font.get("/BaseFont", "?")))
        print(f"fonts: {sorted(re.sub(r'^/[A-Z]{6}\+', '/', f) for f in fonts)}")

    # Text layout and tables (pdfplumber) --------------------------------------------------------
    with pdfplumber.open(io.BytesIO(raw), password=password) as doc:
        first = doc.pages[0]
        print("\n--- page 1 text above the first table (masked)")
        tables = first.find_tables()
        top = tables[0].bbox[1] if tables else first.height
        header_text = first.crop((0, 0, first.width, top)).extract_text() or ""
        for line in header_text.splitlines():
            print("  " + mask(line))

        all_rows: list[list[str | None]] = []
        header_counts: Counter[str] = Counter()
        summary_rows: list[list[str | None]] = []
        for page in doc.pages:
            for table in page.extract_tables():
                if not table:
                    continue
                header = " | ".join(mask(c) for c in table[0])
                header_counts[header] += 1
                if "RECEIPT" in (table[0][0] or "").upper() or len(table[0]) >= 7:
                    # A table continued from the previous page may have no header row; only
                    # skip row 0 when it really is the header.
                    body = table[1:] if is_detail_header(table[0]) else table
                    all_rows.extend(r for r in body if any(r))
                elif "TRANSACTION TYPE" in header.upper():
                    summary_rows.extend(table[1:])

        print("\n--- table headers (count of tables with each)")
        for header, n in header_counts.most_common():
            print(f"  {n:>3} x  {header}")

        print("\n--- summary table rows (labels only; amounts as shapes)")
        for row in summary_rows:
            print("  " + " | ".join(mask(c) for c in row))

        print(f"\n--- detail rows: {len(all_rows)}")
        width_counts = Counter(len(r) for r in all_rows)
        print(f"columns per row: {dict(width_counts)}")
        if not all_rows:
            return
        n = len(all_rows[0])
        for col in range(n):
            shapes = Counter(mask(r[col]) if col != 2 else "" for r in all_rows if len(r) == n)
            if col == 2:
                continue
            print(f"column {col} shapes: {shapes.most_common(4)}")
        templates = Counter(mask(r[2]) for r in all_rows if len(r) == n)
        print(f"\n--- details column: {len(templates)} distinct templates (top 30)")
        for t, c in templates.most_common(30):
            print(f"  {c:>4} x  {t}")
        masked_numbers = sum(bool(re.search(r"\d+\*+\d+", r[2] or "")) for r in all_rows)
        print(f"rows whose details contain a masked number (e.g. 99******999): {masked_numbers}")

        rows = [r for r in all_rows if len(r) == n]
        if n >= 7:
            withdrawn = [money(r[5]) or 0 for r in rows]
            print(
                f"\nwithdrawn values written as negatives: "
                f"{sum(w < 0 for w in withdrawn)}/{len(rows)}"
            )
            naive, reordered = balance_chain_breaks(rows)
            print(
                f"balance chain breaks, oldest->newest: {naive} naive, "
                f"{reordered} after reordering rows within the same second"
            )


def balance_chain_breaks(rows: list[list[str | None]]) -> tuple[int, int]:
    """Count rows where balance != previous balance + paid in - |withdrawn|.

    Rows are newest-first. Rows sharing a timestamp (a transfer and its charge) appear in
    either order, so the second count tries every order within each same-second group.
    """
    seq = list(reversed(rows))
    amount = [(money(r[4]) or 0) - abs(money(r[5]) or 0) for r in seq]
    balance = [money(r[6]) for r in seq]

    def breaks(order: list[int]) -> int:
        return sum(
            balance[b] != (balance[a] or 0) + amount[b]
            for a, b in zip(order, order[1:], strict=False)
        )

    groups: list[list[int]] = []
    for i, row in enumerate(seq):
        if groups and seq[groups[-1][0]][1] == row[1]:
            groups[-1].append(i)
        else:
            groups.append([i])
    order: list[int] = []
    for group in groups:
        best = group
        if len(group) <= 6:
            # The first group has no earlier balance, so it only has to agree with itself.
            anchor = order[-1:]
            for candidate in permutations(group):
                if breaks([*anchor, *candidate]) == 0:
                    best = list(candidate)
                    break
        order.extend(best)
    return breaks(list(range(len(seq)))), breaks(order)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
