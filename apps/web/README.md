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

Users sign in with a **6-digit code sent by email** (Supabase email OTP). There is no public sign-up: accounts are created by invitation.

One-time Supabase setup:

1. **Authentication → Email Templates → Magic Link**: replace the body with a message containing `{{ .Token }}`, for example:
   ```html
   <h2>Your SecurePitch sign-in code</h2>
   <p>Enter this code to sign in: <strong>{{ .Token }}</strong></p>
   <p>It expires in 1 hour. If you didn't ask for it, ignore this email.</p>
   ```
   Without this change Supabase emails a link instead of a code.
2. **Authentication → Users → Add user → Send invitation** for each person who needs access.

Supabase's built-in email service is for testing only: it sends a few emails an hour, and only to members of the Supabase organisation. Before the field test with real club officials, configure custom SMTP (Authentication → Emails → SMTP settings).

## Layout

| Path | What it is |
|---|---|
| `app/(auth)/login` | Email-code sign-in |
| `app/(app)/*` | Signed-in pages (`/dashboard`, later `/club`, `/statements`, `/dossiers`, `/settings`) |
| `app/auth/signout` | Sign-out endpoint |
| `middleware.ts`, `lib/supabase/` | Session refresh and route protection |
| `components/ui/` | shadcn/ui components |
