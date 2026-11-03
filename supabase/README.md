# Database (Supabase)

Owner: **Chris**. Migrations live in `migrations/` and run in filename order.

| Migration | What it adds |
|---|---|
| `…090000_core.sql` | Tables and types: clubs, members, roster (HMAC keys only), fixtures, dossiers, ledger rows, planned spends, receipts, attestations, passkey approvals, passkey credentials |
| `…090100_audit_log.sql` | Append-only, hash-chained audit log and `verify_audit_chain()` |
| `…090200_rls.sql` | Row-level security for every table; no table access for anonymous visitors |
| `…090300_dossier_rules.sql` | Lifecycle rules (draft → submitted → approved → sealed → revoked), `transition_dossier()`, `seal_dossier()`, and `public_dossier()` for the verifier |
| `…110000_api_role_grants.sql` | Explicit table privileges for the engine (`service_role`) and signed-in users (`authenticated`) |

## Every new table needs explicit GRANTs

Our project gives the API roles (`anon`, `authenticated`, `service_role`) **no table privileges by default**. A migration that adds a table must also grant what each role needs, at least `select, insert, update, delete` for `service_role` and `select` for `authenticated` where members should read it, or the engine and app get "permission denied". The test stand-in (`tests/supabase_stub.sql`) mirrors this, so a missing grant fails the tests.

## Rules the database enforces for every caller

- Club members see only their own club. Only managers and treasurers see the roster.
- In the browser, the manager can only re-tag or remove ledger rows (category, branch, fixture), and only while the dossier is a draft. Amounts, dates and receipt numbers can't be edited from the browser.
- Status changes go only through `transition_dossier()` (submit: manager with passkey signature; approve: treasurer with passkey signature and no open attestations; revoke: manager or treasurer, with a reason) and `seal_dossier()`. Both are callable only by the engine's service role.
- Sealed dossiers can only be revoked; revoked ones never change. Approvals and audit entries can't be edited or deleted, even by the service role.
- Passkeys are saved only by the backend (engine or a Next.js route handler using the secret key), after it has verified the WebAuthn registration against the challenge it issued. Browsers can read their own passkeys but can't insert one.
- Anonymous visitors can't read any table. They can call `public_dossier(id)`, which returns a sealed or revoked dossier by ID (no listing) with only the fields a verifier needs.

## Test the migrations locally

```bash
bash supabase/tests/run.sh
```

Needs Docker. It applies everything to a throwaway Postgres 17 container, using `tests/supabase_stub.sql` to stand in for Supabase's roles and `auth` schema, then runs `tests/rls_test.sql`, which acts as an anonymous visitor, another club's manager, the captain, the manager, the treasurer and the engine. CI runs the same script on every PR.

## Apply them to the real project

Direct database connections need port 5432, which many networks block ([ADR 0002](../docs/adr/0002-engine-uses-supabase-over-https.md)). Use one method and stick to it.

**Option A: Supabase CLI** (recommended; it records which migrations have run). On a network that allows 5432, such as a phone hotspot:

```bash
npx supabase login
npx supabase link --project-ref <project-ref>
npx supabase db push
```

**Option B: SQL editor** (works over HTTPS on any network). In the dashboard, open **SQL Editor**, then paste and run each file in `migrations/` in order. If you later switch to the CLI, first mark these as applied with `npx supabase migration repair --status applied <version>` for each file.

Never run anything in `tests/` against the real project.
