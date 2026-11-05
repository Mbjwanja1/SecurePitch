# SecurePitch: finishing plan (5–8 Nov)

This plan covers what is left to build, as of Thursday 5 November (Day 8 of [PLAN.md](PLAN.md)). Most new work goes to Catherine and Joy. Chris's remaining engine work is listed at the end so you can see where you depend on him.

## Where we are

These are built, merged and tested live:
- statement parser and integrity score
- roster matching and matchday batches
- tagging
- draft dossiers
- passkey approvals (manager, then treasurer)
- the platform seal
- the public verifier at `/v/<id>`.

The core trust chain works end to end.

**Still to do** (detailed below):
- deployment on Vercel
- the AWS signing key
- the sealed PDF with a QR code
- receipts
- captain attestation
- a roster screen
- the documents judges read
- the field session, deck and rehearsals.

**Schedule change:** the PDF and deployment can't be ready by Friday morning, so we propose moving the field session with the Lionesses from **Friday 6 to Saturday 7, morning**. We'll confirm this with the mentors.

## At a glance

| # | Task | Owner | Needs | Due |
|---|---|---|---|---|
| J1 | Deploy the web app on Vercel | Joy | Engine URL and internal key from Chris | Fri 6, midday |
| J2 | KamiLimu subdomain | Joy | J1 | Fri 6 (DNS depends on KamiLimu) |
| J3 | Dossier PDF template (4 pages) | Joy | — | Fri 6, 18:00 |
| J4 | Fix PR 18 (synthetic fixtures and answer key) | Joy | — | Fri 6, morning |
| J5 | DPIA and consent wording (English and Swahili) | Joy | — | Fri 6 |
| J6 | Field session on Saturday | Joy | J2, the PDF | Sat 7, morning |
| J7 | DEMO_SCRIPT, FIELD_REPORT, TEST_PLAN, deck | Joy | J6 | Sat 7 to Sun 8 |
| C1 | AWS account and KMS signing key | Catherine | A payment card | Fri 6, midday |
| C2 | Receipt capture on the tagging screen | Catherine | Chris's receipts endpoint | Fri 6 |
| C3 | PDF hash check on the verifier | Catherine | The sealed PDF | Sat 7, morning |
| C4 | Roster import screen | Catherine | — (the engine endpoint exists) | Fri 6 |
| C5 | Captain attestation page `/a/[token]` | Catherine | Chris's attestation endpoints | Sat 7 (cut if late) |
| C6 | README, demo phones, backup video | Catherine | J2 | Sat 7 to Sun 8 |

Every code change goes on a feature branch and a PR. Someone else reviews it, and we merge with "Create a merge commit". Secrets never go in the repo, chat or email: use the password manager.

---

## Joy

### J1 · Deploy the web app on Vercel

This has to be Joy: Vercel imports the repository from its owner's GitHub account. Vercel's free Hobby plan has one user per project, so Joy runs it, and Chris and Catherine can't sign in to it.

1. Go to <https://vercel.com>, sign in with GitHub (the account that owns `SecurePitch`), then **Add New… → Project** and import the repository.
2. On **Configure Project**:
   - **Root Directory:** click Edit, choose `apps/web`, then Continue. The web app is the only part Vercel runs; the engine stays in Docker.
   - **Framework Preset:** Next.js (detected automatically). Leave the build settings at their defaults; Vercel finds pnpm from the lockfile.
   - **Environment Variables:** add the four below for **Production**. The names must be exactly these: the app reads `PUBLISHABLE_KEY`, not `ANON_KEY`.

     | Name | Value | Where it comes from |
     |---|---|---|
     | `NEXT_PUBLIC_SUPABASE_URL` | `https://<ref>.supabase.co` | Chris (not secret) |
     | `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | `sb_publishable_…` | Chris (safe in the browser) |
     | `ENGINE_URL` | The engine's tunnel address, `https://….trycloudflare.com` | Chris, on the day |
     | `ENGINE_INTERNAL_KEY` | The shared engine key | Chris, **through the password manager only**. Tick **Sensitive**. |

3. Click **Deploy**. After a minute or two you'll have `https://<project>.vercel.app`.
4. **Settings → Functions → Function Region:** choose **Frankfurt (fra1)**, where our Supabase database is. The default (Washington, US) adds a transatlantic round trip to every page. Then redeploy (**Deployments → ⋯ → Redeploy**).
5. Check that `https://<project>.vercel.app/login` loads and that `https://<project>.vercel.app/.well-known/securepitch-keys.json` shows a key.

**The engine address changes.** The engine runs on Chris's laptop behind a free Cloudflare quick tunnel, and its address changes whenever the tunnel restarts. When Chris sends a new address, update `ENGINE_URL` (**Settings → Environment Variables**) and **redeploy**: Vercel only picks up a changed variable on the next deployment. Chris will avoid restarting the tunnel near the demo.

### J2 · KamiLimu subdomain

1. In the Vercel project, open **Settings → Domains**, type the subdomain KamiLimu assigned (for example `securepitch.<their-domain>`) and click **Add**.
2. Vercel shows the domain as "Invalid Configuration". That's expected until KamiLimu adds the DNS record.
3. **Copy the records exactly as Vercel shows them** into the email to KamiLimu: type, name and value. The value is often `cname.vercel-dns.com`, but newer projects get their own value (such as `….vercel-dns-0xx.com`), so don't type it from memory. If Vercel also lists a **TXT** record (`_vercel`, `vc-domain-verify=…`), send that too.
4. When KamiLimu replies, refresh the Domains page until it shows **Valid Configuration**. Vercel issues the HTTPS certificate on its own.
5. **Send the final domain to Chris at once.** Passkeys are tied to one exact domain, so he has to:
   - set the engine's `WEBAUTHN_RP_ID` to the subdomain
   - set `WEBAUTHN_ORIGINS` to `https://<subdomain>`
   - restart the engine.
6. In **Supabase → Authentication → URL Configuration**:
   - set **Site URL** to `https://<subdomain>`
   - add `https://<subdomain>/**` under **Redirect URLs**.

   (Chris can do this if you don't have Supabase access.)
7. **Everyone re-registers their passkeys on the subdomain.** Passkeys made on `localhost` don't carry over. Passkeys made on `<project>.vercel.app` won't work on the subdomain either, so use only the subdomain from now on.
8. Test it from a phone on mobile data:
   - sign in
   - add a passkey
   - open `https://<subdomain>/.well-known/securepitch-keys.json`.

### J3 · Dossier PDF template

This is the document sponsors hold; it's the 2:20 beat of the demo. Joy writes the HTML and CSS; Chris renders it in the engine with WeasyPrint and adds the QR code.

- **Page 1:**
  - club, period, totals by category (with fees), club rows out of statement rows, and the integrity score
  - planned spends
  - the QR code (Chris leaves a 35 mm square box for it)
  - "Verify at `https://<subdomain>/v/<id>`".
- **Page 2:** the ledger. Date, receipt number, category, counterparty (`Player P03`, `Till 5123456`, or "Someone not on the roster"; never a phone number), amount and fee.
- **Page 3:** squad audit, by pseudonym only (P01–P18), with no names or numbers.
- **Page 4:** receipt thumbnails, each linked to its ledger line. If receipts slip, the page says "No receipts attached".
- **Rules:** A4, plain system fonts, no external images or web fonts (the engine renders offline), black text that survives a photocopy.
- **Data:** Chris will send a sample JSON with every field. Put placeholders like `{{ totals.transport }}` in the template and he'll wire them up.

Hand over the HTML and CSS file in a PR to `services/engine/app/render/templates/` by **Friday 18:00**.

### J4 · Fix PR 18

Apply the review comments already on the PR:
- update the branch from `main`
- LNS becomes `MD3-2026-10-17`
- mark SJC, SJA0000002 and SJD0000004 as `fee`
- set the fixtures header to `fixture_code,match_date,opponent,venue`
- add the roster columns `is_minor,consent_by,consent_at`
- end every file with a newline.

Also decide whether SJD0000007 (KES 3,200) is club income. Once it's merged, Chris adds a CI test that runs your answer key through the engine.

### J5 · DPIA and consent

- `docs/DPIA.md`, under the Kenya Data Protection Act 2019:
  - **What we store:** club rows only. Personal rows never leave the coach's phone. Player phone numbers are kept only as keyed hashes (HMAC).
  - **Lawful basis.**
  - **Minors**, with parental consent and who gave it.
  - **The transfer to Supabase in Frankfurt (EU)** and its safeguards.
  - **Retention, and data subjects' rights.**
- **Consent wording** (English and Swahili) for:
  - adding a player to the roster
  - parental consent for players under 18
  - the coach uploading a statement.

  Catherine puts this wording on the roster screen (C4).

### J6 · Field session (Saturday morning)

1. Confirm the new date with Eugene and Sarah, including consent for any photos or quotes.
2. Tasks to time:
   - upload a statement
   - tag 5 items
   - (captain attests, if C5 shipped)
   - treasurer signs
   - a sponsor scans the QR code.
3. Record time to dossier, every hesitation, and quotes. If Eugene's real statement breaks the parser, use the synthetic statement on his phone and write down the gap honestly.
4. In the evening, triage with the team: rank the issues P1 or P2.

### J7 · Documents and pitch

- `docs/DEMO_SCRIPT.md`: PLAN §17, with timings and a fallback for each beat (backup video, a pre-sealed PDF).
- `docs/TEST_PLAN.md`: each journey, with results.
- `docs/FIELD_REPORT.md`: method, timings, quotes, and the issues found and fixed.
- **Funder test:** send the sealed PDF to the funder contacts. Ask them to scan the QR code, time it, and send a quote.
- **The deck:** 10 slides, with field data and screenshots. The roadmap slide covers:
  - player corroboration
  - offline app (PWA)
  - USSD
  - a transparency log
  - moving the engine to a managed host.
- **Sunday:** 3 timed rehearsals and one mock Q&A round.

---

## Catherine

### C1 · AWS account and KMS signing key

Follow [INFRA_SETUP.md](INFRA_SETUP.md) sections 1 to 4. They're written step by step. The differences from that document:

1. **Account:** create it with the team email. A card is needed; it costs about $1–2 a month. Put MFA on the root user, then create your own admin user, **`catherine-admin`** (instead of `chris-admin`), with MFA. Work as that user, not as root.
2. **Enable Cape Town (`af-south-1`):** **Account → AWS Regions**. It can take a few minutes. Switch the console to that region before the next step, or the key ends up in the wrong place.
3. **Budget:** a $5 monthly budget, with email alerts to all three of us (INFRA_SETUP §2).
4. **KMS key** (INFRA_SETUP §3):
   - Asymmetric, Sign and verify, `ECC_NIST_P256`
   - alias `securepitch-seal`
   - key administrator `catherine-admin`.
5. **Engine user** (INFRA_SETUP §4):
   - Create the policy from [`infra/aws/engine-kms-policy.json`](../infra/aws/engine-kms-policy.json), replacing `<ACCOUNT_ID>` and `<KEY_ID>`, and name it `SecurePitchEngineSign`.
   - Create the user `securepitch-engine` with **no console access** and that policy only.
6. **Access key:** user `securepitch-engine` → **Security credentials → Create access key** → "Application running outside AWS". The secret is shown **only once**: save it straight into the password manager and share it with Chris there. Never use WhatsApp, email or the repo; gitleaks would block it anyway.
7. **Send Chris** (not secret, normal chat is fine): the account ID, the key ID, and the region `af-south-1`.

**Chris then:**
1. Adds the current `local-dev` public key to `RETIRED_PUBLIC_KEYS`, so the dossiers already sealed keep verifying.
2. Sets `SIGNER=kms`.
3. Runs `tools/check_infra.py`, expecting four PASS lines.
4. Seals a fresh dossier. Its verifier page no longer says "development key".

If AWS isn't working by **Saturday midday**, we demo with the development key. The verifier already labels it honestly, and KMS goes on the roadmap slide.

### C2 · Receipt capture

On the tagging screen, each club row gets an "Attach receipt" button:
- **Input:** an `<input type="file" accept="image/*" capture="environment">`, so phones open the camera.
- **Before upload:** resize in the browser (longest side 1600 px, JPEG).
- **The engine** re-encodes the photo, strips EXIF (which holds GPS location), hashes it, and stores it.
- **After upload:** show the thumbnail and a short hash on the row.

Chris adds the endpoint `POST /v1/dossiers/{id}/receipts`; agree the request shape with him first. The receipt's hash goes into the row's leaf (`ev.receipt_sha256`). That means receipts must be attached **before the manager signs**, so put the button on the draft dossier page.

### C3 · PDF hash check on the verifier

On `/v/[id]`, add "Check a PDF you received":
1. Drop or choose a file.
2. Compute SHA-256 in the browser (`crypto.subtle.digest`); nothing is uploaded.
3. Compare it with `pdf_sha256` from the public record.

Show a green "This is the sealed PDF", or a red "This PDF is not the one SecurePitch sealed". Test it with a copy where one byte is changed. This is the demo's "tampered PDF turns red" moment.

### C4 · Roster import screen

`/club/[clubId]/roster`, for the manager only:
- **Input:** a form or CSV upload with player code, name, phone number, fkf_id (optional), is_minor, consent_by and consent_at. Show Joy's consent wording (J5) above it.
- **Submit:** post through a Next.js route handler to the engine's existing `POST /v1/clubs/{club}/roster`. Copy the pattern of `app/api/club/[clubId]/statements/parse`, including `requireManager`.
- **After saving:** show "18 players saved". **Never display phone numbers back**; the engine stores only hashes.
- **Navigation:** link the screen from the dashboard next to "Upload a statement".

Without this screen, Eugene depends on Chris to load his roster during the field session.

### C5 · Captain attestation (cut if late)

`/a/[token]` is a public page for the captain:
- It shows one transaction (date, amount and category; no names) and asks "Did this happen?" with Yes or No.
- On the draft page, a "Send to captain" sheet offers WhatsApp (`https://wa.me/?text=…`), SMS (`sms:`), copy link, and a QR code.
- Chris adds the endpoints that issue and answer tokens (single use, they expire in 48 hours, and only the token's hash is stored).

If this isn't done by **Saturday 12:00**, it moves to the roadmap slide; the treasurer's passkey signature still carries that beat of the demo.

### C6 · README, demo phones, backup video

- `README.md`: what SecurePitch is, the live link, and setup on a clean machine, from cloning to the first sealed dossier. Test it by following it yourself.
- **Demo phones:**
  - charged
  - passkeys registered **on the subdomain**
  - the verifier link bookmarked
  - one pre-sealed PDF saved on each phone.
- **Backup video:** a 2-minute recording of the whole flow, made on Saturday after the fixes.

---

## Chris (for reference: what you're waiting on)

| What | For | Due |
|---|---|---|
| Send the Supabase URL, the publishable key, the engine tunnel URL, and the internal key (password manager) | J1 | Thu evening |
| Set `WEBAUTHN_RP_ID` and `WEBAUTHN_ORIGINS` to the subdomain, restart the engine, set the Supabase Site URL | J2 | When DNS works |
| Render the sealed PDF (WeasyPrint and Joy's template), add the QR code (`segno`), hash it, upload it, and record `pdf_sha256` | J3, C3 | Sat 7, morning |
| Receipts endpoint: re-encode, strip EXIF, hash, store, set the row's `receipt_sha256` | C2 | Fri 6 |
| Attestation endpoints | C5 | Fri 6, night |
| Switch to KMS; keep `local-dev` published as retired | C1 | When C1 is done |
| Answer-key test in CI | J4 | After PR 18 merges |
| `tools/verify_dossier.py` (offline verifier), rate limits, and CSP on the verifier | Hardening | Sat 7 |
| `THREAT_MODEL.md`, `ARCHITECTURE.md`, `API.md` | Judging | Sat 7 |

## Timeline

| When | Joy | Catherine | Chris |
|---|---|---|---|
| **Thu 5, evening** | Mentor check; start J1 | Mentor check; start C1 | Mentor check; send J1 values; start PDF rendering |
| **Fri 6** | J1, J2, J4, J5; J3 by 18:00 | C1, C4, C2 | Receipts endpoint, attestation endpoints, PDF rendering |
| **Sat 7** | J6 field session (morning); triage (evening) | C3, C5 (or cut), field support | PDF plus QR live; KMS switch; P1 fixes; docs |
| **Sun 8** | J7 deck, rehearsals, submission | C6, demo phones | Final fixes until 12:00, tag `v1.0.0`, seal a fresh demo dossier |

**Moves to the roadmap slide:**
- player corroboration
- PWA and offline use
- Swahili beyond the consent screens
- the inclusion-proof screen
- a managed engine host with a fixed address
- KMS, if AWS isn't ready.
