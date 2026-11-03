# Infrastructure setup

How to bring SecurePitch's approved resources to life, and why each step is done this way. Owner: **Chris**. Do the steps in order; the last one proves everything works.

| Resource | What it does in SecurePitch | Region |
|---|---|---|
| AWS KMS key | Holds the platform's private signing key. Seals every dossier. The key can't be exported, so nobody (including us) can forge a seal outside AWS. | `af-south-1` (Cape Town) |
| AWS Budget | Emails us before costs pass $5. | Global |
| IAM user `securepitch-engine` | The only identity the engine uses. It can sign with that one key and nothing else. | Global |
| Supabase project | Postgres database with row-level security, email-OTP login, and file storage for sealed PDFs. | `eu-central-1` (Frankfurt) |
| Docker Desktop | Runs the Python engine in a locked-down container on the team laptop. | Local |

---

## 1. AWS account

1. Create the account at <https://aws.amazon.com> (needs a card; we'll spend about $1–2 a month).
2. **Secure the root user.** Account menu → Security credentials → assign an MFA device. The root user can close the account and change billing, so after this step it is only used for billing.
3. **Create a daily admin identity.** IAM → Users → Create user `chris-admin` → console access → attach `AdministratorAccess` → enable MFA. Sign out of root and work as `chris-admin`.
4. **Enable Cape Town.** Account menu → Account → AWS Regions → `Africa (Cape Town) af-south-1` → Enable. It's an opt-in region and can take a few minutes to activate. We use it because it is the closest AWS region to Nairobi.

## 2. Budget alert

Billing and Cost Management → Budgets → Create budget → **Monthly cost budget** → amount **$5** → email alerts to all three of us at 80% actual and 100% forecasted.

*Why:* a forgotten resource or leaked key shows up as cost first. Two budgets are free.

## 3. KMS signing key

Switch the console region to **af-south-1**, then KMS → Customer managed keys → Create key:

| Setting | Value | Why |
|---|---|---|
| Key type | Asymmetric | Anyone can verify with the public key; only KMS can sign |
| Key usage | Sign and verify | It never encrypts anything |
| Key spec | `ECC_NIST_P256` | The curve browsers support natively in WebCrypto, so the verifier needs no extra library |
| Alias | `securepitch-seal` | Code refers to `alias/securepitch-seal`, so we can rotate keys without code changes |
| Key administrators | `chris-admin` | |
| Key users | leave empty | Access is granted to the engine user by the IAM policy in step 4 |

Copy the **key ID** and your **account ID** for the next step. Cost: $1/month for the key plus a fraction of a cent per signature.

## 4. Sign-only IAM user for the engine

The plan called this a "scoped IAM role". A role needs something to assume it, such as a cloud server. Our engine runs on a laptop, so the base credential has to be an access key anyway. We make that key as weak as possible instead:

1. IAM → Policies → Create policy → JSON → paste [`infra/aws/engine-kms-policy.json`](../infra/aws/engine-kms-policy.json), replacing `<ACCOUNT_ID>` and `<KEY_ID>`. Name it `SecurePitchEngineSign`.
2. IAM → Users → Create user `securepitch-engine` → **no** console access → attach `SecurePitchEngineSign` only.
3. Open the user → Security credentials → Create access key → "Application running outside AWS". Put the two values in `services/engine/.env` (copy it from `.env.example`). They are shown once.

What the policy allows: `kms:Sign` on that one key, only with `ECDSA_SHA_256` over a pre-computed digest, plus reading the public key. If this key leaks, the attacker can't read data, create resources or run up a bill; the worst case is signing digests until we disable the key, which takes one click. Gitleaks blocks AWS keys from being committed, and we rotate the access key after the sprint.

## 5. Supabase project

1. Sign up at <https://supabase.com> with the team's shared email, create an organisation `Coffee Powered Innovators`, and invite Catherine and Joy.
2. New project `securepitch`, region **Central EU (Frankfurt)**, plan Free. Generate a strong database password and store it in a password manager, not in chat.
3. Project Settings → Data API: copy the **Project URL** (`https://<ref>.supabase.co`, with nothing after `.co`) into `SUPABASE_URL`. Project Settings → API Keys → **Secret keys** → create one named `engine` (`sb_secret_…`) → `SUPABASE_SERVICE_ROLE_KEY`. Catherine needs the URL and the **publishable** key (`sb_publishable_…`) for `apps/web/.env.local`; share them privately, never in the repo.
4. **Connect** (top of the dashboard) → Connection string → **Session pooler** → `DATABASE_URL`, with your database password filled in. **Only migrations use this** ([ADR 0002](adr/0002-engine-uses-supabase-over-https.md)); the engine talks to Supabase over HTTPS. The "Direct connection" address only works over IPv6, which Docker Desktop and most local networks don't have.

*Why Frankfurt:* Supabase has no African region. Frankfurt keeps data under GDPR, which helps the Kenya Data Protection Act cross-border transfer assessment. **Joy:** record this transfer and its safeguards in the DPIA.

*Free-tier catch:* free projects pause after 7 days without activity. The daily work keeps it awake; open the dashboard on demo morning to be sure.

## 6. Engine secrets

Generate the two engine-only secrets and add them to `services/engine/.env`:

```bash
# macOS, Linux, WSL (on Windows, use `py` instead of `python3`)
python3 -c "import secrets; print(secrets.token_urlsafe(32))"                                     # ENGINE_INTERNAL_KEY
python3 -c "import secrets, base64; print(base64.b64encode(secrets.token_bytes(32)).decode())"    # ROSTER_PEPPER
```

`ENGINE_INTERNAL_KEY` is how the engine knows a request came from our web app; once the tunnel is up the engine is on the public internet. `ROSTER_PEPPER` keys the HMAC of player phone numbers. **Back up `ROSTER_PEPPER` in the password manager:** if it's lost, every roster has to be re-imported.

## 7. Docker Desktop

The engine runs in Docker Desktop on the team laptop, reached through a Cloudflare Tunnel (see [ADR 0001](adr/0001-engine-in-docker.md)).

1. Settings → General → **Use the WSL 2 based engine** on.
2. Settings → Resources → give it at least 4 GB of memory.
3. **Turn off WSL swap** so in-memory data can't be paged to disk. Create or edit `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   swap=0
   ```
   then run `wsl --shutdown` and restart Docker Desktop. Without this, the Linux VM can move the container's in-memory files to a swap file on disk under memory pressure, which would quietly break the "never touches disk" claim.

**Network:** the engine laptop needs outbound **port 443** (Supabase) and **port 7844** (Cloudflare Tunnel). Campus, office and venue Wi-Fi often block 7844, and the tunnel then fails with Cloudflare error 530. On any such network, **put the engine laptop on a phone hotspot**; the other devices can stay on the venue Wi-Fi. See [ADR 0002](adr/0002-engine-uses-supabase-over-https.md).

## 8. Prove it

```bash
uv run tools/check_infra.py
```

Expected output when everything is right (with `SIGNER=kms`):

```text
PASS  Docker engine running
PASS  AWS credentials valid                       arn:aws:iam::<account>:user/securepitch-engine
PASS  KMS key is ECC_NIST_P256, SIGN_VERIFY, enabled
PASS  KMS sign -> local verify round trip         valid DER signature, 7x bytes
PASS  IAM user is sign-only (cannot list keys)    kms:ListKeys denied, as intended
PASS  Supabase service key has admin rights
PASS  Database login (for migrations only)        aws-1-eu-central-1.pooler.supabase.com:5432, Postgres 17.x
PASS  Engine secrets valid                        internal key length ok; roster pepper is 32 bytes
```

With `SIGNER=local` the three AWS-only checks show `SKIP` and a local-key round trip runs instead.

What each check proves:

- **Sign round trip:** signs a digest exactly as the dossier seal will, then verifies it locally with the public key.
- **Sign-only:** passes only if the engine's credentials are *refused* something they shouldn't have.
- **Admin rights:** calls the Auth admin API, which only a secret key can use. (`/auth/v1/health` would also accept the public publishable key, so it can't catch a pasted wrong key.)
- **Database (migrations only):** logs in with `DATABASE_URL` and runs a query. It reports **WARN**, not FAIL, when it can't connect, because the engine itself uses HTTPS. A timeout means the network blocks database ports; to run migrations, use a phone hotspot or paste the SQL into the Supabase SQL editor.
- **Secrets:** checks `ROSTER_PEPPER` is valid base64 of exactly 32 bytes, so a bad value fails here rather than at the first roster import.
