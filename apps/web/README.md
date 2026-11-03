# SecurePitch web app

Next.js 15 (App Router) PWA for coaches, treasurers and captains, plus the public dossier verifier. Owner: **Catherine**.

## Run it

```bash
cd apps/web
pnpm install
cp .env.example .env.local     # then fill in the values
pnpm dev                       # http://localhost:3000
```

| Command | What it does |
|---|---|
| `pnpm dev` | Development server with hot reload |
| `pnpm build` | Production build (what Vercel runs) |
| `pnpm lint` | ESLint |
| `pnpm typecheck` | TypeScript, no output |

## Sign-in

Users sign in with **email and password**. There is no public sign-up and no "forgot password" email: we don't have an email provider, so a club admin creates accounts and resets passwords. (Emailed sign-in codes are in git history and can return once SMTP is set up.) Approving and sealing a dossier will still require a passkey.

**One-time Supabase setting:** Authentication → Sign In / Providers → turn **off** "Allow new users to sign up". The publishable key ships in the browser, so with sign-ups on, anyone could create an account by calling Supabase directly. `tools/check_infra.py` fails until it's off.

**Adding someone to a club** (from the repo root; uses the engine's secret key from `services/engine/.env`):

```bash
uv run tools/onboard_member.py --club "Nairobi City Inspectorate Lionesses" \
    --email coach@example.com --name "Coach Eugene" --role manager
```

It creates the club if it doesn't exist, creates the account already confirmed, and adds the membership. You type the password at a hidden prompt (at least 12 characters), or pass `--generate-password` to have one generated and shown once. Give it to the person privately, in person or by phone. Running it again for an existing account adds or updates the membership and leaves the password unchanged.

**Resetting a password:** Supabase dashboard → Authentication → Users → the user → Reset password.

## Layout

| Path | What it is |
|---|---|
| `app/(auth)/login` | Email-code sign-in |
| `app/(app)/*` | Signed-in pages (`/dashboard`, later `/club`, `/statements`, `/dossiers`, `/settings`) |
| `app/auth/signout` | Sign-out endpoint |
| `middleware.ts`, `lib/supabase/` | Session refresh and route protection |
| `components/ui/` | shadcn/ui components |
