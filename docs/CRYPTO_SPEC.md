# SecurePitch cryptography specification

**Version 1.** Owner: Chris. Implemented by `services/engine/app/crypto/` (Python) and `apps/web/lib/crypto/` (TypeScript). Both must pass [`spec/test-vectors.json`](../spec/test-vectors.json); if they disagree, the vectors win.

This document is the contract between the engine that seals dossiers and the verifier that sponsors use. Any change to it needs a new `v` number and regenerated vectors.

## 1. Encoding

| Data | Encoding |
|---|---|
| Hashes, Merkle roots, digests | lowercase hex |
| Signatures, public keys, salts, private keys | base64url **without** padding when writing. Decoders also accept padded input and **reject** any character outside `A-Z a-z 0-9 - _` instead of skipping it. |
| Money | integer cents: KES 250 → `25000` |
| Timestamps | ISO 8601 with offset: `2026-10-17T07:15:00+03:00` |
| Ratios and scores | integer basis points: 94% → `9400` |

**No floating-point numbers** may appear in anything hashed or signed. Python and JavaScript format some floats differently, so a float could make the same dossier hash differently in the engine and the browser. Implementations reject floats rather than encode them. (This replaces the plan's `"score": 0.94` with `"score_bp": 9400`.)

## 2. Canonical JSON

Objects are serialised with **RFC 8785 (JSON Canonicalization Scheme)**: keys sorted, no whitespace, UTF-8, minimal string escaping. We use maintained libraries instead of hand-written serialisers:

- Python: [`rfc8785`](https://pypi.org/project/rfc8785/)
- TypeScript: [`canonicalize`](https://www.npmjs.com/package/canonicalize)

Integers must be within ±(2⁵³ − 1) so JavaScript represents them exactly. Object keys are ASCII.

## 3. Merkle tree

```text
leaf_hash(obj)  = SHA-256( 0x00 ‖ canonical(obj) )
node_hash(L, R) = SHA-256( 0x01 ‖ L ‖ R )          (L, R are 32-byte hashes)
```

- The `0x00` / `0x01` prefixes (domain separation, as in RFC 6962) stop a leaf from being passed off as an internal node.
- At each level, hashes are paired left to right. **An unpaired last node is promoted unchanged** to the next level. It is never duplicated: duplication lets two different leaf lists share a root (CVE-2012-2459).
- Leaves are sorted by `(ts, tx)` before the tree is built, so the same set of rows always gives the same root.
- An empty tree is an error. A dossier has at least one row.
- With one leaf, the root is that leaf's hash.

### Inclusion proof

A proof is the list of sibling hashes from the leaf up to the root, each tagged with the side the sibling sits on:

```json
[{"side": "R", "hash": "<hex>"}, {"side": "L", "hash": "<hex>"}]
```

To verify: start with `h = leaf_hash`; for each step, `h = node_hash(step.hash, h)` if the side is `L`, else `node_hash(h, step.hash)`. The proof is valid if the final `h` equals the root. Levels where the node was promoted contribute no step.

## 4. Leaf object (one disclosed club row)

```json
{
  "v": 1,
  "branch": "B",
  "tx": "SJK3ABC12D",
  "ts": "2026-10-17T07:15:00+03:00",
  "amt": 25000,
  "fee": 700,
  "dir": "out",
  "cp": {"type": "player", "ref": "hmac:<hex>"},
  "cat": "transport",
  "fixture": "MD4-2026-10-17",
  "ev": {"receipt_sha256": null, "attest": [], "corroborated": true},
  "salt": "<16 random bytes, base64url>"
}
```

`branch` is `A` (merchant), `B` (squad) or `I` (club income). `cp.type` is `player`, `till`, `paybill` or `person`. The `salt` stops anyone from guessing a small leaf (one amount, one date) by brute force and checking it against a published hash.

- `ts` is Kenyan time with seconds and the `+03:00` offset, whatever zone the database returns.
- `fee` is the M-Pesa charge paid with this transfer, in cents (`0` if none). Club spending totals include it.
- `cp.ref` is a player code (`P07`) for roster players, the till or paybill number for businesses, and `hmac:<mask_key>` (section 8) for anyone else.
- `ev.receipt_sha256` is the SHA-256 of the receipt photo, or `null`. Until attestations and player corroboration are built (ADR 0003), `ev.attest` is `[]` and `ev.corroborated` is `false`: stated, not left out.

## 5. Signatures

- Algorithm: **ECDSA on P-256 with SHA-256** (`ES256`). KMS key spec `ECC_NIST_P256`; WebCrypto `{name: "ECDSA", namedCurve: "P-256"}`.
- **What is signed:** `d = SHA-256(canonical(payload))`. The signer receives the 32-byte digest `d`. With KMS this is `Sign(MessageType=DIGEST, SigningAlgorithm=ECDSA_SHA_256)`.
- **Signature format on the wire:** DER, base64url. This is what KMS returns.
- **Verifying in the browser:** WebCrypto's `verify()` hashes its input itself, so pass it the **canonical payload bytes, not `d`**. It also expects the raw 64-byte `r ‖ s` form, so convert from DER first. The vectors include both forms so this conversion is tested.
- **Public keys** are published as JWK at `/.well-known/securepitch-keys.json`: `{"kid", "kty": "EC", "crv": "P-256", "x", "y", "alg": "ES256"}`. Every payload names its `kid`, so keys can be rotated.

### Signer implementations

| `SIGNER` | Key lives | Use |
|---|---|---|
| `kms` | AWS KMS, never exportable | Real dossiers |
| `local` | `LOCAL_SIGNING_KEY` in `.env` (base64url PKCS#8 DER) | Development and tests, and the fallback while AWS isn't ready. Dossiers sealed with a local key use a `kid` starting `local-` and the verifier labels them as not production-signed. |

Generate a local key with:

```bash
uv run --directory services/engine python -m app.crypto.signer --generate
```

## 6. Approval challenge (passkeys)

The manager and the treasurer each sign the dossier with their own passkey (ADR 0003). What they sign is the **approval payload**:

```json
{
  "v": 1,
  "dossier_id": "<uuid>",
  "club": {"id": "<uuid>", "name": "Synthetic Lionesses FC"},
  "period": {"from": "2026-10-01", "to": "2026-10-31"},
  "source_sha256": "<hex: SHA-256 of the original statement PDF>",
  "rows_total": 47,
  "rows_disclosed": 20,
  "merkle_root": "<hex: root over the leaves of section 4>",
  "totals_cents": {"income": 400000, "meals": 180000, "transport": 462600},
  "integrity": {"score_bp": 9500, "checks": {"balance_chain": true, "producer_baseline": false}},
  "planned_spends": [{"supplier": "…", "till": "5123456", "amt": 1500000, "purpose": "Away kit"}]
}
```

- `totals_cents` sums each category's leaves: `amt + fee` for money out, `amt` for money in.
- `rows_total` counts every row of the statement; `rows_disclosed` counts the leaves. The difference is what the coach kept personal, shown to the treasurer before signing.
- `planned_spends` is ordered by `(till, amt, supplier, purpose)`, comparing strings by Unicode code point (not a database collation).

The WebAuthn challenge is

```text
c = SHA-256( canonical(approval payload) )        32 bytes; clientDataJSON.challenge = base64url(c)
```

Both approvers sign the same `c`: the ledger freezes when the manager submits, and the database refuses a treasurer signature over any other challenge. Sealing (section 5) adds exactly three fields, `kid`, `approvals` and `sealed_at`, and signs the result, so the platform seal covers the passkey signatures. A verifier rebuilds `c` by removing those three fields from the sealed payload.

Each approval in the sealed payload carries the WebAuthn assertion (`authenticatorData`, `clientDataJSON`, `signature`) and the credential public key. A verifier checks that `clientDataJSON.type` is `webauthn.get`, its `challenge` equals `base64url(c)`, its `origin` is the SecurePitch web app, the authenticator data's RP ID hash is SHA-256 of the RP ID, the user-verified flag is set, and the signature over `authenticatorData ‖ SHA-256(clientDataJSON)` verifies (ES256, or RS256 for older Windows Hello).

The `approval` entry in the test vectors gives a snapshot, its sorted leaves, the payload, and `c`.

## 7. Test vectors

`spec/test-vectors.json` is generated by `tools/gen_vectors.py` from the Python implementation, using a fixed, publicly known test key. It contains:

- `canonical`: input objects and their exact canonical strings and SHA-256
- `leaves`: example leaf objects and their leaf hashes
- `trees`: leaf lists of sizes 1, 2, 3, 4, 5, 7 and 18 with roots and inclusion proofs
- `signature`: the test public key (SPKI and JWK), a payload, its digest, a deterministic (RFC 6979) signature in DER and raw form, and a tampered payload that must fail

Regenerate after any intentional change:

```bash
uv run --project services/engine python tools/gen_vectors.py
```

The engine's test suite fails if the committed file is out of date.

**The test key is public. Never use it for anything but tests.**

## 8. Roster keys

Implemented in `services/engine/app/roster/keys.py`. Raw phone numbers are never stored: the engine turns each one into two keyed hashes as soon as it arrives, then discards it.

```text
club_key  = HMAC-SHA256(ROSTER_PEPPER, "securepitch/roster/v1/club/" || club_id)
phone_key = HMAC-SHA256(club_key, "phone:" || E.164)                 e.g. "+2547XXXXXXXX"
mask_key  = HMAC-SHA256(club_key, "mask:" || prefix4 || "|" || suffix3)  e.g. "0712|678"
```

- **Why HMAC, not plain SHA-256:** Kenya's mobile numbers are a space of about 10⁹, so an unkeyed hash can be reversed by trying them all in minutes. Without `ROSTER_PEPPER` (32 random bytes held only by the engine), the keys reveal nothing.
- **Why a key per club:** the same player in two clubs gets unrelated keys, so rosters can't be linked across clubs.
- **Why two keys:** statements only ever show the masked form (`0712***678`), so `mask_key` is what matching uses. `phone_key` de-duplicates the roster. The `phone:` and `mask:` prefixes keep the two from ever colliding.
- **Normalising:** `07XX XXX XXX`, `07XX-XXX-XXX`, `2547XXXXXXXX` and `+254 7XX XXX XXX` all become `+2547XXXXXXXX`. Only Kenyan mobiles (`7…` and `1…`) are accepted.
- **Matching:** a statement row's masked number gives `mask_key`; a roster player with that key is **verified** if the statement's name shares a word with the player's name (ignoring case and punctuation), **number only** if not (often a parent's line), and **ambiguous** if several players share the key and the name doesn't pick one.

Rotating `ROSTER_PEPPER` invalidates every stored key, so it's backed up with the other engine secrets, and changing it means re-importing rosters.
