# SecurePitch

**Coffee Powered Innovators · KamiLimu Cybersecurity Track**

Community-based football coaches run club money through their personal M-Pesa lines, and sponsors can't trust those informal records. SecurePitch turns a coach's M-Pesa statement into a **sealed sponsor dossier**: it processes the statement in memory, keeps only the club's transactions, has two club officials approve it with their own passkeys, and seals it with a signature anyone can check. The coach never has to expose their personal spending.

> **Status:** built in an 11-day sprint, Thu 29 Oct → Sun 8 Nov 2026 (submission day).
> **Live site:** https://securepitch.kamilimu.dev (the sponsor verifier is at `/v/<dossier id>`).

## How it works

1. **Upload.** The coach uploads their M-Pesa statement. The engine reads it in memory and never writes it to disk.
2. **Match.** Payments are matched to the club roster using keyed hashes, so names and phone numbers are never published.
3. **Check.** An integrity score checks the running balance, reconciles the totals against the statement's own summary, and looks for signs the PDF was edited. (Asking random players to confirm they were paid is on the roadmap.)
4. **Approve.** The manager and the treasurer each sign the dossier with their own passkey.
5. **Seal and verify.** The platform signs the result with an ECDSA key (an AWS KMS key in production, a development key until AWS is set up; the verifier says which). A sponsor opens the dossier's link or QR code and every signature is checked in their own browser.

## The parts

| Part | Built with | Runs on |
|---|---|---|
| Web app and public verifier | Next.js 15, TypeScript, Tailwind, shadcn/ui, SimpleWebAuthn | Vercel |
| Engine | Python 3.12, FastAPI, pdfplumber, pikepdf, WeasyPrint | Docker (read-only, no disk writes) |
| Database and sign-in | Supabase: Postgres with row-level security, email and password | Supabase (Frankfurt) |
| Signing | ECDSA P-256 (AWS KMS in production) | AWS / engine |

## Repository layout

| Folder | What is in it |
|---|---|
| `apps/web` | The web app and the public verifier at `/v/<dossier id>` |
| `services/engine` | The engine: parsing, matching, approvals, sealing, dossier PDF |
| `supabase` | Database migrations and row-level security tests |
| `spec` | Shared test vectors that the engine and the browser must both pass |
| `tools` | Scripts: onboarding members, infrastructure checks, test-vector generation |
| `fixtures` | Synthetic clubs and statements for development (real data never goes here) |
| `docs` | Plan, crypto specification, infrastructure setup, decision records |

## Run it on your computer

### What you need

- **Everyone:** Git, Node.js (LTS) and pnpm. You also need to be added to the GitHub repository by its owner.
- **Only to run the engine:** Docker Desktop.
- **Only for the Python tools and tests:** Python 3.12 and [uv](https://docs.astral.sh/uv/).

### The web app

```powershell
git clone https://github.com/Mbjwanja1/SecurePitch.git
cd SecurePitch\apps\web
npm i -g pnpm
pnpm install
Copy-Item .env.example .env.local
```

Open `apps\web\.env.local` and fill in the four values (on macOS or Linux, use `cp` instead of `Copy-Item`):

| Setting | Value | Where it comes from |
|---|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | `https://<project-ref>.supabase.co`, with nothing after `.co` | Supabase: Project Settings → Data API |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | starts with `sb_publishable_` | Supabase: Project Settings → API Keys. Safe in the browser. **Never use the secret key here.** |
| `ENGINE_URL` | `http://127.0.0.1:8000`, or the engine's public tunnel address | Chris |
| `ENGINE_INTERNAL_KEY` | a shared secret | Chris, through the password manager only |

Then start the app:

```powershell
pnpm dev
```

Open **http://localhost:3000**. Always use `localhost`, not the network address (`10.x.x.x`) that the terminal also prints: passkeys only work on the exact address they were made on.

### The engine

The engine runs in Docker so that statements can never touch persistent storage (see `docs/adr/0001-engine-in-docker.md`). From the repository root:

```powershell
Copy-Item services\engine\.env.example services\engine\.env   # fill in the values; ask Chris
docker compose up -d --build                                    # http://127.0.0.1:8000
docker compose --profile tunnel up -d --build                   # also opens a public HTTPS address
docker compose logs tunnel | Select-String trycloudflare        # print that address
```

The tunnel address changes every time the tunnel restarts. When it does, update `ENGINE_URL` (locally in `.env.local`, and in the Vercel project settings, followed by a redeploy). For passkeys to work, the engine's `WEBAUTHN_RP_ID` and `WEBAUTHN_ORIGINS` must match the address you open the web app on.

### Sign-in and accounts

There is no public sign-up. A club admin creates each account and adds it to a club:

```powershell
uv run tools/onboard_member.py --club "Demo Lionesses (test)" `
    --email you@example.com --name "Your Name" --role manager
```

Copy the club name exactly. If no club has that name, the script creates a new one.

Roles are `manager`, `treasurer` and `captain`. More detail, and how to reset a password, is in [`apps/web/README.md`](apps/web/README.md). If you sign in and see "You're not in a club yet", your account has not been added to a club.

### From setup to a first sealed dossier

1. **Sign in as the manager** at `/login`. Open **Manage roster** on the dashboard and add the players, or import a CSV.
2. **Add a passkey** at `/settings/passkeys` (the manager and the treasurer each need one).
3. **Upload a statement** with **Upload a statement** on the dashboard. For development, generate a synthetic statement with `uv run --project services/engine python tools/make_fake_statement.py`. It writes `fixtures/synthetic/statement_genuine-layout.pdf`, with the password `123456`. Add `--variant tampered-amount` for a statement whose integrity score drops. Tag each club transaction and save the draft.
4. **Submit** the draft: the manager signs it with their passkey.
5. **Approve** as the treasurer: sign in as the treasurer and sign with their passkey. The dossier is sealed straight away. If sealing fails, a **Seal the dossier** button appears on its page to retry.
6. **Verify** at `/v/<dossier id>`. A sponsor sees the same page, without an account: the seal and both passkey signatures. Download the sealed PDF from the dossier's page and give it to sponsors. Its QR code opens this page, which can also check that a PDF they were given is the one SecurePitch issued.

### Tests and checks

From `apps/web`:

```powershell
pnpm test         # unit tests
pnpm lint         # ESLint
pnpm typecheck    # TypeScript
```

From the repository root: `uv run --directory services/engine pytest` runs the engine tests. On Windows, the dossier PDF rendering tests skip, because they need Pango. They run in Docker and in CI, where `CI=1` makes them fail instead of skip.

### If something goes wrong

| What you see | What to do |
|---|---|
| `pnpm` is not recognized | Run `npm i -g pnpm` and reopen the terminal. If it still fails, put `npx` in front of each command, for example `npx pnpm install`. |
| "NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY is not set" | `.env.local` is missing or empty. Fill it in, then **restart** `pnpm dev`: it only reads that file at startup. |
| The app opens on port 3001, or `localhost:3000` shows old settings | An earlier server is still running. Stop it with `Ctrl + C` or `Stop-Process`, and start again. |
| A warning about a cross-origin request from `10.x.x.x` | You opened the app through the network address. Use `http://localhost:3000`. |
| "SecurePitch's engine isn't available right now" | The engine isn't running, or `ENGINE_URL` or `ENGINE_INTERNAL_KEY` is wrong. If you use a tunnel, its address may have changed. |
| The Vercel check is red on your pull request | Expected for people who are not on the project owner's Vercel plan. The CI checks are the ones that matter. |

## Working rules

- **Never commit** real statements, rosters, phone numbers, passwords or keys. Real data belongs in `fixtures/private/`, which is git-ignored. Secrets travel only through the password manager, never through chat or email.
- Every change goes on a **feature branch** and a **pull request**, reviewed by someone else, and merged with **"Create a merge commit"**.
- Add the files you changed by name; do not use `git add .`.

## Team

| Person | Owns |
|---|---|
| Chris Waweru | Engine, crypto, database and security |
| Catherine Atieno | Web app, passkeys and the public verifier |
| Joy Mbugua | Product, dossier design, compliance and testing (repo owner) |

## Documentation

- **[Build plan](docs/PLAN.md):** the design review, architecture, data model, API, threat model and risks.
- **[Crypto specification](docs/CRYPTO_SPEC.md):** how rows, trees and signatures are encoded, so anyone can re-implement the verifier.
- **[Infrastructure setup](docs/INFRA_SETUP.md):** AWS, KMS and the engine host, step by step.
- **[Decision records](docs/adr):** why the engine runs in Docker, how it reaches Supabase, and how passkey approvals work.
- `docs/ARCHITECTURE.md`, `docs/API.md`, `docs/THREAT_MODEL.md`, `docs/DPIA.md`, `docs/TEST_PLAN.md`: being written for submission.
