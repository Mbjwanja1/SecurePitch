// Verifying a sealed dossier as a sponsor would (CRYPTO_SPEC sections 5 and 6): only the public
// record, the published platform keys and WebCrypto. Nothing here trusts the SecurePitch server
// beyond the keys it publishes.
import { canonicalize } from "./crypto/canonical";
import { derToRaw, importPublicJwk, type PublicJwk, verifyPayloadSignature } from "./crypto/ecdsa";
import { type Bytes, concat, equalBytes, fromB64url, sha256, toB64url } from "./crypto/encoding";

export type PasskeyJwk =
  | { kty: "EC"; crv: "P-256"; alg: "ES256"; x: string; y: string }
  | { kty: "RSA"; alg: "RS256"; n: string; e: string };

export type SealedApproval = {
  role: "manager" | "treasurer";
  signed_at: string;
  cred_id: string;
  pubkey: PasskeyJwk;
  authenticatorData: string;
  clientDataJSON: string;
  signature: string;
};

export type SealedPayload = {
  v: number;
  dossier_id: string;
  club: { id: string; name: string };
  period: { from: string; to: string };
  source_sha256: string;
  rows_total: number;
  rows_disclosed: number;
  merkle_root: string;
  totals_cents: Record<string, number>;
  integrity: { score_bp: number; checks: Record<string, boolean> };
  planned_spends: { supplier: string; till: string; amt: number; purpose: string }[];
  kid: string;
  approvals: SealedApproval[];
  sealed_at: string;
};

/** What public_dossier() returns: the sealed payload and seal, plus the unsigned status. */
export type PublicRecord = {
  id: string;
  status: "sealed" | "revoked";
  payload: SealedPayload;
  kid: string;
  signature: string;
  sealed_at: string;
  revoked_at: string | null;
  revoke_reason: string | null;
};

/** Where passkey signatures must come from: this web app's RP ID and origins. */
export type RelyingParty = { rpId: string; origins: string[] };

export type Check = { ok: boolean; detail: string };

export type Verification = {
  seal: Check;
  record: Check;
  approvals: { role: string; check: Check }[];
  /** All signatures valid. A revoked dossier can still be authentic; see `status`. */
  authentic: boolean;
  status: "sealed" | "revoked";
};

const ROLES = ["manager", "treasurer"] as const;

/** The approval payload both passkeys signed: the sealed payload minus what sealing added. */
export function approvalPayloadOf(sealed: SealedPayload): Record<string, unknown> {
  const added = new Set(["kid", "approvals", "sealed_at"]);
  return Object.fromEntries(Object.entries(sealed).filter(([k]) => !added.has(k)));
}

async function checkSeal(record: PublicRecord, keys: PublicJwk[]): Promise<Check> {
  const jwk = keys.find((k) => k.kid === record.payload.kid);
  if (!jwk) {
    return { ok: false, detail: `Signing key "${record.payload.kid}" isn't published by SecurePitch.` };
  }
  try {
    const key = await importPublicJwk(jwk);
    if (await verifyPayloadSignature(key, record.payload, record.signature)) {
      return { ok: true, detail: `Signed by SecurePitch with key ${jwk.kid}.` };
    }
  } catch {
    // An unusable key or signature is a failed seal, not a crash.
  }
  return { ok: false, detail: "The seal doesn't match: something in this dossier was changed." };
}

/** The unsigned record must describe the signed payload, not some other dossier. */
function checkRecord(record: PublicRecord): Check {
  if (record.payload.dossier_id !== record.id || record.payload.kid !== record.kid) {
    return { ok: false, detail: "The signed contents belong to a different dossier." };
  }
  return { ok: true, detail: "The signed contents are this dossier's." };
}

async function verifyAssertionSignature(
  jwk: PasskeyJwk,
  signature: Bytes,
  data: Bytes,
): Promise<boolean> {
  if (jwk.kty === "EC" && jwk.crv === "P-256") {
    const key = await crypto.subtle.importKey(
      "jwk",
      { kty: "EC", crv: "P-256", x: jwk.x, y: jwk.y, ext: true },
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
    return crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, derToRaw(signature), data);
  }
  if (jwk.kty === "RSA") {
    // Older Windows Hello passkeys: RS256, signature already raw.
    const key = await crypto.subtle.importKey(
      "jwk",
      { kty: "RSA", n: jwk.n, e: jwk.e, alg: "RS256", ext: true },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    return crypto.subtle.verify("RSASSA-PKCS1-v1_5", key, signature, data);
  }
  return false;
}

/** One approver's WebAuthn assertion, checked as CRYPTO_SPEC section 6 lists. */
export async function checkApproval(
  a: SealedApproval,
  challenge: Bytes,
  rp: RelyingParty,
): Promise<Check> {
  try {
    const clientDataBytes = fromB64url(a.clientDataJSON);
    const clientData = JSON.parse(new TextDecoder().decode(clientDataBytes));
    if (clientData.type !== "webauthn.get") {
      return { ok: false, detail: "Not a passkey sign-in signature." };
    }
    if (clientData.challenge !== toB64url(challenge)) {
      return { ok: false, detail: "The passkey signed something other than this dossier." };
    }
    if (!rp.origins.includes(clientData.origin)) {
      return { ok: false, detail: `Signed on ${clientData.origin}, not on SecurePitch.` };
    }
    const authData = fromB64url(a.authenticatorData);
    const rpIdHash = await sha256(new TextEncoder().encode(rp.rpId));
    if (authData.length < 37 || !equalBytes(authData.subarray(0, 32), rpIdHash)) {
      return { ok: false, detail: "The passkey belongs to a different website." };
    }
    if (!(authData[32] & 0x01) || !(authData[32] & 0x04)) {
      return { ok: false, detail: "The signer wasn't verified by fingerprint, face or PIN." };
    }
    const data = concat(authData, await sha256(clientDataBytes));
    if (await verifyAssertionSignature(a.pubkey, fromB64url(a.signature), data)) {
      return { ok: true, detail: "Signed with their passkey, verified by fingerprint, face or PIN." };
    }
  } catch {
    // Malformed assertion: treated as a bad signature below.
  }
  return { ok: false, detail: "The passkey signature doesn't match." };
}

export async function verifyDossier(
  record: PublicRecord,
  keys: PublicJwk[],
  rp: RelyingParty,
): Promise<Verification> {
  const challenge = await sha256(canonicalize(approvalPayloadOf(record.payload)));
  const given = record.payload.approvals ?? [];
  const approvals = await Promise.all(
    ROLES.map(async (role, i) => {
      const a = given[i];
      if (!a || a.role !== role) {
        return { role, check: { ok: false, detail: "Signature missing." } };
      }
      return { role, check: await checkApproval(a, challenge, rp) };
    }),
  );
  if (given.length === 2 && given[0].cred_id === given[1].cred_id) {
    approvals[1].check = { ok: false, detail: "Signed with the manager's passkey, not their own." };
  }
  const seal = await checkSeal(record, keys);
  const recordCheck = checkRecord(record);
  return {
    seal,
    record: recordCheck,
    approvals,
    authentic:
      given.length === ROLES.length &&
      seal.ok &&
      recordCheck.ok &&
      approvals.every((a) => a.check.ok),
    status: record.status,
  };
}
