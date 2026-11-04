# ADR 0003: Passkey-signed approvals, verified by the engine

- **Status:** Proposed
- **Date:** 2026-11-05
- **Decider:** Chris Waweru, with the team

## Context

The plan's fix for the "one-man show" risk (R2) is that the manager and the treasurer each sign the dossier with their own passkey, so a sponsor can check both signatures instead of trusting a database flag. The schema already has `approvals` (immutable once written), `webauthn_credentials`, and `transition_dossier()`, which refuses to submit or approve without the matching approval row.

Three questions were open:

1. **What exactly is signed?** CRYPTO_SPEC section 6 said "the payload without approvals and sealed_at", but the sealed payload wasn't defined yet.
2. **Who verifies the passkey response?** The plan named `@simplewebauthn/server` in the web app, but the web app holds only the publishable key: it can't write approvals, and the database must not take its word that a signature verified.
3. **How do we stop the ledger changing between "build the challenge" and "record the signature"?** The manager signs while the dossier is still a draft, and drafts can be edited.

## Decision

1. **The approval payload** (CRYPTO_SPEC section 6) holds the dossier and club IDs, the period, the statement's SHA-256, rows total and disclosed, the Merkle root of the leaves, totals by category (fees included), the integrity checks and planned spends. The WebAuthn challenge is `SHA-256(canonical(approval payload))`. Sealing adds exactly `kid`, `approvals` and `sealed_at`. Leaves gain a `fee` field. The `approval` test vector fixes this for both implementations.
2. **The engine verifies** passkey registrations and assertions with py_webauthn. The Next.js route handlers pass the session user as `X-Actor-Id`, as for statements (ADR 0002 rule 7). User verification (fingerprint, face or PIN) is required. The RP ID and allowed origins come from engine configuration (`WEBAUTHN_RP_ID`, `WEBAUTHN_ORIGINS`), never from the request. Algorithms are ES256 and RS256, which the sponsor's browser can verify with WebCrypto.
3. **The database checks it all again, atomically.** `approve_dossier()` locks the dossier and refuses the signature if any of these fail:
   - the signer holds the right role for the status (manager for a draft, treasurer once submitted)
   - the passkey is registered to the signer
   - its signature counter went up (or both are zero)
   - the content fingerprint, a SHA-256 over `approval_content()`, still equals the one the challenge was built from
   - the treasurer's challenge equals the manager's

   It then stores the leaf hashes (manager only), the approval and the counter, and moves the status, all in one transaction.
4. **Registration needs no server session.** The engine hands the browser a state token holding the challenge, user and expiry (5 minutes), HMAC-signed with a key derived from `ENGINE_INTERNAL_KEY`.

## Consequences

- An approval in the database is a passkey signature that verified against the exact rows stored, by someone holding that role at that moment. Nobody, including the engine, can change it afterwards.
- A verifier can recheck everything offline from the sealed payload: rebuild `c` and verify each assertion (CRYPTO_SPEC section 6). That's the next PR (sealing) and the one after (verifier).
- Passkeys are bound to the web app's domain. Moving to a new domain needs re-registration, and `WEBAUTHN_RP_ID` / `WEBAUTHN_ORIGINS` must match the deployed web app.
- **Open:** attestations and player corroboration (`ev.attest`, `ev.corroborated`) are not built yet and are signed as `[]` and `false`. When they are built, they must be complete before the manager submits (or move outside the leaves); otherwise the leaves, and so the challenge, would change between the two signatures. The database already refuses approval while attestations are open.
- **Open:** the manager both prepares and approves; the treasurer is the only independent check. A third approver (club chair, 2-of-3) remains on the roadmap.
