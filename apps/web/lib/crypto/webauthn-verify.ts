// Browser-side check of a passkey (WebAuthn) approval (docs/CRYPTO_SPEC.md section 6).
import { canonicalize } from "./canonical";
import { derToRaw } from "./ecdsa";
import { type Bytes, concat, equalBytes, sha256, toB64url } from "./encoding";

/** Fields that sealing adds. Removing them from a sealed payload gives what was approved. */
const SEAL_ONLY_FIELDS = ["kid", "approvals", "sealed_at"] as const;

export function approvalPayload(
  sealed: Record<string, unknown>,
): Record<string, unknown> {
  const out = { ...sealed };
  for (const field of SEAL_ONLY_FIELDS) delete out[field];
  return out;
}

/** c = SHA-256(canonical(approval payload)): the challenge both approvers signed. */
export function approvalChallenge(
  sealed: Record<string, unknown>,
): Promise<Bytes> {
  return sha256(canonicalize(approvalPayload(sealed)));
}

export type AssertionCheck = { ok: true } | { ok: false; reason: string };

export type AssertionInput = {
  authenticatorData: Bytes;
  clientDataJSON: Bytes;
  signature: Bytes; // as sent by the authenticator: DER for ES256
  publicKey: CryptoKey;
  alg: "ES256" | "RS256";
  expectedChallenge: Bytes; // the 32-byte c
  expectedOrigin: string;
  expectedRpId: string;
};

const FLAG_UP = 0x01;
const FLAG_UV = 0x04;

export async function verifyAssertion(
  a: AssertionInput,
): Promise<AssertionCheck> {
  let client: { type?: string; challenge?: string; origin?: string };
  try {
    client = JSON.parse(new TextDecoder().decode(a.clientDataJSON));
  } catch {
    return { ok: false, reason: "clientDataJSON is not valid JSON" };
  }
  if (client.type !== "webauthn.get")
    return { ok: false, reason: "wrong assertion type" };
  if (client.challenge !== toB64url(a.expectedChallenge)) {
    return { ok: false, reason: "challenge does not match this dossier" };
  }
  if (client.origin !== a.expectedOrigin)
    return { ok: false, reason: "wrong origin" };

  if (a.authenticatorData.length < 37)
    return { ok: false, reason: "authenticator data too short" };
  const rpIdHash = await sha256(new TextEncoder().encode(a.expectedRpId));
  if (!equalBytes(a.authenticatorData.subarray(0, 32), rpIdHash)) {
    return { ok: false, reason: "wrong relying party" };
  }
  const flags = a.authenticatorData[32];
  if (!(flags & FLAG_UP))
    return { ok: false, reason: "user presence flag not set" };
  if (!(flags & FLAG_UV))
    return { ok: false, reason: "user verification flag not set" };

  const signed = concat(a.authenticatorData, await sha256(a.clientDataJSON));
  let valid: boolean;
  try {
    valid =
      a.alg === "ES256"
        ? await crypto.subtle.verify(
            { name: "ECDSA", hash: "SHA-256" },
            a.publicKey,
            derToRaw(a.signature),
            signed,
          )
        : await crypto.subtle.verify(
            { name: "RSASSA-PKCS1-v1_5" },
            a.publicKey,
            a.signature,
            signed,
          );
  } catch {
    return { ok: false, reason: "signature could not be checked" };
  }
  return valid ? { ok: true } : { ok: false, reason: "signature is invalid" };
}
