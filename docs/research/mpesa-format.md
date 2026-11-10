# M-Pesa statement format

Findings from inspecting a genuine Safaricom M-Pesa full statement with `tools/inspect_statement.py`, which prints structure only (digits → `9`, names and businesses → `X`). **No personal data is recorded here.** Date of inspection: 2026-11-03.

**Sample so far:** 1 statement, 3-month period, 17 pages, 582 transactions. Every row had status `Completed`, so failed and reversed transactions haven't been seen yet. **We need 1–2 more statements** (a different person, an older period) before the parser is trusted at the field visit.

## 1. File

| Property | Genuine statement | Use in the integrity score |
|---|---|---|
| PDF version | 1.5 | Baseline |
| Encryption | RC4 128-bit (R3, V2), user password | The engine needs the password; decrypt in memory |
| Producer / Creator | `OpenPDF <version>` / `Safaricom …` | Strong baseline: an edited file is usually re-saved by different software |
| CreationDate vs ModDate | **Differ** | ⚠️ **Not a tamper signal.** The plan assumed they'd be equal; they aren't on genuine files |
| `%%EOF` markers / trailer `/Prev` | 1 / absent | Strong signal: never re-saved incrementally. An editor that appends changes adds both |
| Annotations, form fields | None | Any present is suspicious |
| Fonts | DejaVuSans, FuturaBT-Medium | Baseline: text added in another editor usually brings other fonts |

## 2. Page layout

**Page 1, above the tables:**

```text
Page 9 of 99
M-PESA STATEMENT
Customer Name: X X X
Mobile Number: 9999999999            ← the account holder's own number, unmasked
Email Address: <email>
Statement Period: 99 Mon 9999 - 99 Mon 9999
Request Date: 99 Mon 9999
SUMMARY
```

**Summary table (page 1 only):** `TRANSACTION TYPE | PAID IN | PAID OUT`, one row per type, with labels ending in a colon:
`SEND MONEY:`, `RECEIVED MONEY:`, `AGENT DEPOSIT:`, `AGENT WITHDRAWAL:`, `LIPA NA M-PESA (PAYBILL):`, `LIPA NA M-PESA (BUY GOODS):`, `OTHERS:`, `TOTAL:`. Amounts look like `99,999.99`.

**Every page:** one detail table (below), plus a **"Statement Verification Code"** table: *"To verify the validity of this M-PESA statement dial \*334#, select My account and follow the prompts to enter the code."*

> ⚠️ **Open question for Joy (product):** Safaricom provides its own authenticity check. What does `*334#` verification show, and to whom? If an auditor can verify a statement's code from their own phone, recording the code in the dossier would answer R1 ("is the statement genuine?") far better than any PDF forensics. Worth a quick test with a teammate's phone.

## 3. Detail table

All 582 rows extracted cleanly with pdfplumber's `extract_tables()`: 7 columns on every row and every page.

In this sample the header row repeats on all 17 pages. **Don't rely on that:** a table continued across a page may arrive without its header, so the parser only skips the first row when it actually is the header (`Receipt No. …`).

| # | Column | Format | Notes |
|---|---|---|---|
| 0 | Receipt No. | 10 uppercase letters/digits, e.g. `AAA999AAAA` | Matches `dossier_items.tx` |
| 1 | Completion Time | `YYYY-MM-DD HH:MM:SS` | Local time, no offset: store with `+03:00` |
| 2 | Details | Multi-line free text | See section 4 |
| 3 | Transaction Status | `Completed` | Other values not yet seen |
| 4 | Paid In | Blank, or positive `9,999.99` | |
| 5 | Withdrawn | Blank, or **negative** `-999.99` | Use the absolute value |
| 6 | Balance | `9,999.99` | |

**Order:** newest first.

**Receipt numbers:** a transfer and its charge share one receipt number (101 pairs in this sample). Two different transactions never do.

**Balance chain:** walking oldest → newest, `balance = previous balance + paid in − |withdrawn|` holds for **every row**, *provided rows with the same timestamp may come in either order*. A naive top-to-bottom check reports 108 false breaks out of 581. They come from 101 pairs of rows in the same second, typically a transfer and its charge, which the statement lists in varying order. **The parser must reorder within same-second groups before checking the chain** (groups are at most 2 rows in this sample).

## 4. Details column: transaction types

Line breaks inside the cell shown as `/`. Counts are from the sample.

| Pattern (masked) | Count | Meaning | Branch / counterparty |
|---|---|---|---|
| `Customer Transfer to - 999999***999 X X` | 112 | Send money to a person | P2P out → roster match candidate |
| `Customer Transfer to - 9999***999 X X` | 23 | Same, local-format mask | P2P out |
| `Customer Transfer of Funds Charge` | 89 | Fee for the previous transfer | Charge, attached to its transfer |
| `Customer Payment to Small Business to - 999999***999 X X` | 70+ | Pochi la Biashara | P2P out (business person) |
| `Funds received from - 999999***999 X X` | 40+ | Money received from a person | Club income candidate |
| `Merchant Payment to 9999999 - X X X` | 21+ | Buy Goods till | Branch A, `cp_type = till` |
| `Merchant Payment Online to 9999999 - X X` | 5 | Online till payment | Branch A |
| `Pay Bill Online to 9999999 - X Acc. AAA999…` | 22 | Paybill with account number | `cp_type = paybill` |
| `Pay Bill to 999999 - X Acc. 999999` | 4+ | Paybill | `cp_type = paybill` |
| `Pay Bill Charge` | 11 | Paybill fee | Charge |
| `Customer Bundle Purchase to … by - 999999***999 X X` | 27 | Data bundles | Personal (usually) |
| `Airtime Purchase` | 10 | Airtime | Personal (usually) |
| `Business Payment from 999999 - X Bulk Account via X Original conversation X is 999…` | 8 | Bank or business transfer in (B2C) | Income candidate |

Till and paybill numbers are 6–7 digits.

## 5. Counterparty phone numbers

- **Counterparty numbers are always masked.** The full number never appears (328 of 582 rows contain a masked number). Two forms occur:
  - international: 6 digits, `***`, 3 digits, e.g. `2547 12***789` → prefix `0712`, suffix `789`
  - local: 4 digits, `***`, 3 digits, e.g. `0712***789` → prefix `0712`, suffix `789`
- Both reduce to the same **national prefix (4 digits) + last 3 digits**. That is exactly what the plan's `mask_key = HMAC(pepper, prefix4 ∥ suffix3)` needs. **The full-number `phone_key` can never be matched from a statement**, so `mask_key` is the primary match key, confirmed by the name.
- Names appear in **both UPPER CASE and Title Case**, sometimes split across lines. Name matching must ignore case and line breaks.

## 6. What this changes in the plan

1. **Integrity score:** drop "CreationDate = ModDate"; keep "single `%%EOF` / no `/Prev`", producer/creator baseline, fonts baseline, no annotations or forms; add the **same-second reordering** rule to the balance chain check.
2. **Roster matching:** `mask_key` (prefix4 + suffix3) + case-insensitive name tokens is the primary path; `phone_key` stays for roster de-duplication only.
3. **Charges:** attach `Customer Transfer of Funds Charge` / `Pay Bill Charge` rows to the transaction in the same second, so a KES 250 transfer is reported with its fee.
4. **Investigate the `*334#` verification code** (section 2) as a stronger authenticity signal than PDF forensics.
5. **Synthetic fixtures** (`tools/make_fake_statement.py`) must reproduce: page-1 header, summary table, 7-column detail table, negative withdrawals, newest-first order, same-second charge pairs in both orders, both masked-number forms, mixed-case names, and the verification-code table.
