// Runs every check a sponsor's browser makes on a sealed dossier (docs/CRYPTO_SPEC.md sections 5 and 6).
import {
  type PublicJwk,
  importPublicJwk,
  verifyPayloadSignature,
} from "./ecdsa";
import { fromB64url } from "./encoding";
import { approvalChallenge, verifyAssertion } from "./webauthn-verify";

export type ApprovalEntry = {
  role: string;
  signed_at?: string;
  cred_id: string;
  pubkey: {
    kty: string;
    crv?: string;
    alg: "ES256" | "RS256";
    x?: string;
    y?: string;
    n?: string;
    e?: string;
  };
  authenticatorData: string;
  clientDataJSON: string;
  signature: string;
};

export type SealedPayload = Record<string, unknown> & {
  kid: string;
  approvals: ApprovalEntry[];
  merkle_root: string;
};

export type CheckId = "seal" | "manager" | "treasurer" | "root" | "status";
export type Check = {
  id: CheckId;
  label: string;
  ok: boolean;
  detail?: string;
};
export type VerifyResult = { ok: boolean; checks: Check[]; localKey: boolean };

export type VerifyInput = {
  sealed: SealedPayload;
  signature: string; // platform seal: DER, base64url
  keys: PublicJwk[];
  status: "sealed" | "revoked";
  expectedOrigin: string;
  expectedRpId: string;
  fragmentRoot?: string; // the root from the QR code's URL fragment, if any
};

const ROLES = ["manager", "treasurer"] as const;

function importApprovalKey(k: ApprovalEntry["pubkey"]): Promise<CryptoKey> {
  if (k.alg === "ES256") {
    return crypto.subtle.importKey(
      "jwk",
      { kty: "EC", crv: "P-256", x: k.x, y: k.y, ext: true },
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
  }
  return crypto.subtle.importKey(
    "jwk",
    { kty: "RSA", alg: "RS256", n: k.n, e: k.e, ext: true },
    { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
    false,
    ["verify"],
  );
}

async function checkSeal(i: VerifyInput): Promise<Check> {
  const label = "SecurePitch seal";
  const jwk = i.keys.find((k) => k.kid === i.sealed.kid);
  if (!jwk)
    return {
      id: "seal",
      label,
      ok: false,
      detail: `no published key for ${i.sealed.kid}`,
    };
  try {
    const ok = await verifyPayloadSignature(
      await importPublicJwk(jwk),
      i.sealed,
      i.signature,
    );
    return {
      id: "seal",
      label,
      ok,
      detail: ok ? undefined : "signature does not match this dossier",
    };
  } catch {
    return {
      id: "seal",
      label,
      ok: false,
      detail: "seal could not be checked",
    };
  }
}

async function checkApproval(
  i: VerifyInput,
  role: (typeof ROLES)[number],
  challenge: Awaited<ReturnType<typeof approvalChallenge>>,
): Promise<Check> {
  const label =
    role === "manager"
      ? "Manager's passkey signature"
      : "Treasurer's passkey signature";
  const entries = Array.isArray(i.sealed.approvals) ? i.sealed.approvals : [];
  const entry = entries.find((a) => a.role === role);
  if (!entry)
    return {
      id: role,
      label,
      ok: false,
      detail: "no signature from this role",
    };
  try {
    const r = await verifyAssertion({
      authenticatorData: fromB64url(entry.authenticatorData),
      clientDataJSON: fromB64url(entry.clientDataJSON),
      signature: fromB64url(entry.signature),
      publicKey: await importApprovalKey(entry.pubkey),
      alg: entry.pubkey.alg,
      expectedChallenge: challenge,
      expectedOrigin: i.expectedOrigin,
      expectedRpId: i.expectedRpId,
    });
    return r.ok
      ? { id: role, label, ok: true }
      : { id: role, label, ok: false, detail: r.reason };
  } catch {
    return {
      id: role,
      label,
      ok: false,
      detail: "signature could not be checked",
    };
  }
}

export async function verifyDossier(i: VerifyInput): Promise<VerifyResult> {
  const checks: Check[] = [await checkSeal(i)];

  try {
    const challenge = await approvalChallenge(i.sealed);
    for (const role of ROLES)
      checks.push(await checkApproval(i, role, challenge));
  } catch {
    for (const role of ROLES) {
      checks.push({
        id: role,
        label: `${role} passkey signature`,
        ok: false,
        detail: "dossier could not be read",
      });
    }
  }

  if (i.fragmentRoot !== undefined) {
    const same = i.fragmentRoot === i.sealed.merkle_root;
    checks.push({
      id: "root",
      label: "QR code matches this dossier",
      ok: same,
      detail: same ? undefined : "the QR code belongs to a different dossier",
    });
  }

  checks.push({
    id: "status",
    label: "Not revoked",
    ok: i.status !== "revoked",
    detail:
      i.status === "revoked" ? "this dossier has been revoked" : undefined,
  });

  return {
    ok: checks.every((c) => c.ok),
    checks,
    localKey: i.sealed.kid.startsWith("local-"),
  };
}
