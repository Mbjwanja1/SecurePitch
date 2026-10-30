# SecurePitch

**Coffee Powered Innovators · KamiLimu Cybersecurity Track**

Community-based football coaches run club money through their personal M-Pesa lines, and sponsors can't trust those informal records. SecurePitch turns a coach's M-Pesa statement into a **sealed sponsor dossier**: it processes the statement in memory, keeps only the club's transactions, has two club officials approve it with their own passkeys, and seals it with a signature anyone can check. The coach never has to expose their personal spending.

> **Status:** 11-day build sprint, Thu 29 Oct → Sun 8 Nov 2026. Feature freeze Day 8 at 18:00; field test Day 9 with the Lionesses.

## How it works

1. **Upload.** The coach uploads their M-Pesa statement. The engine reads it in memory and never writes it to disk.
2. **Match.** Payments are matched to the club roster using keyed hashes, so names and phone numbers are never published.
3. **Check.** An integrity score checks the running balance, reconciles totals against the statement's own summary, and asks randomly chosen players to confirm they were paid.
4. **Approve.** The coach and the treasurer each sign the dossier with a passkey.
5. **Seal and verify.** The platform signs the result with an AWS KMS key. A sponsor scans the QR code on the PDF and checks every signature in their browser.

## Stack

| Part | Built with |
|---|---|
| Web app and public verifier | Next.js 15, TypeScript, Tailwind, shadcn/ui, SimpleWebAuthn (Vercel) |
| Engine | Python 3.12, FastAPI, pdfplumber, pikepdf, WeasyPrint (Docker) |
| Database and auth | Supabase (Postgres with row-level security, email OTP) |
| Signing | AWS KMS, ECC P-256 |

## Getting started

You need Node.js LTS, pnpm, Python 3.12, uv, Docker Desktop and the Supabase CLI.

```bash
git clone https://github.com/Mbjwanja1/SecurePitch.git
cd SecurePitch

# Engine on http://localhost:8000
docker compose up --build

# Web app
cd apps/web
pnpm install
pnpm dev
```

Copy `.env.example` to `.env` in `apps/web` and `services/engine` and fill in the keys. The full list is in [section 18 of the build plan](docs/PLAN.md#18-day-1-setup-commands).

> **Never commit real statements, rosters or phone numbers.** They belong in `fixtures/private/`, which is git-ignored. Use the synthetic files in `fixtures/synthetic/` for development and tests.

## Team

| Person | Owns |
|---|---|
| Chris Waweru | Engine, crypto, database and security |
| Catherine Atieno | Web app, passkeys and the public verifier |
| Joy Mbugua | Product, dossier design, compliance and testing (repo owner) |

## Documentation

- **[Build plan](docs/PLAN.md)**: the full design review, architecture, crypto spec, data model, API, day-by-day sprint, threat model, risks and demo script.
- `docs/ARCHITECTURE.md`, `docs/CRYPTO_SPEC.md`, `docs/API.md`, `docs/THREAT_MODEL.md`, `docs/DPIA.md`, `docs/TEST_PLAN.md`: written during the sprint (owners and due dates in [section 16 of the plan](docs/PLAN.md#16-documentation-set)).
