// The sponsor's verifier, against the sealed test vector the engine produced (spec/test-vectors.json).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { canonicalize } from "@/lib/crypto/canonical";
import type { PublicJwk } from "@/lib/crypto/ecdsa";
import { type Bytes, concat, sha256, toB64url } from "@/lib/crypto/encoding";
import {
  approvalPayloadOf,
  checkApproval,
  isDisplayable,
  type PublicRecord,
  type SealedApproval,
  type SealedPayload,
  verifyDossier,
} from "@/lib/verify";

const vectors = JSON.parse(
  readFileSync(resolve(__dirname, "../../../spec/test-vectors.json"), "utf-8"),
);
const PAYLOAD: SealedPayload = vectors.sealed.payload;
const KEYS: PublicJwk[] = [vectors.signature.public_jwk];
const RP = { rpId: vectors.sealed.rp_id, origins: [vectors.sealed.origin] };

function record(changes: Partial<PublicRecord> = {}): PublicRecord {
  return {
    id: PAYLOAD.dossier_id,
    status: "sealed",
    payload: structuredClone(PAYLOAD),
    kid: PAYLOAD.kid,
    signature: vectors.sealed.signature_der,
    sealed_at: PAYLOAD.sealed_at,
    revoked_at: null,
    revoke_reason: null,
    ...changes,
  };
}

describe("verifying a sealed dossier", () => {
  it("accepts the genuine sealed dossier: seal and both passkeys", async () => {
    const v = await verifyDossier(record(), KEYS, RP);
    expect(v.seal.ok).toBe(true);
    expect(v.approvals.map((a) => [a.role, a.check.ok])).toEqual([
      ["manager", true],
      ["treasurer", true],
    ]);
    expect(v.authentic).toBe(true);
  });

  it("rebuilds the challenge the passkeys signed", async () => {
    const c = await sha256(canonicalize(approvalPayloadOf(PAYLOAD)));
    expect(toB64url(c)).toBe(vectors.approval.challenge_b64url);
  });

  it("refuses a change of one cent", async () => {
    const r = record();
    r.payload.totals_cents.transport += 1;
    const v = await verifyDossier(r, KEYS, RP);
    expect(v.seal.ok).toBe(false);
    expect(v.authentic).toBe(false);
  });

  it("refuses a seal by a key SecurePitch doesn't publish", async () => {
    const v = await verifyDossier(record(), [{ ...KEYS[0], kid: "other" }], RP);
    expect(v.seal).toMatchObject({ ok: false, detail: expect.stringContaining("isn't published") });
  });

  it("refuses a genuine seal shown under another dossier's address", async () => {
    const v = await verifyDossier(record({ id: "00000000-0000-0000-0000-000000000000" }), KEYS, RP);
    expect(v.record.ok).toBe(false);
    expect(v.authentic).toBe(false);
  });

  it("checks each passkey: swapped signatures, other sites and missing signers fail", async () => {
    const swapped = record();
    const [m, t] = swapped.payload.approvals;
    [m.signature, t.signature] = [t.signature, m.signature];
    expect((await verifyDossier(swapped, KEYS, RP)).approvals.every((a) => !a.check.ok)).toBe(true);

    const elsewhere = await verifyDossier(record(), KEYS, { ...RP, origins: ["https://evil.test"] });
    expect(elsewhere.approvals[0].check.detail).toContain("not on SecurePitch");
    const otherRp = await verifyDossier(record(), KEYS, { ...RP, rpId: "evil.test" });
    expect(otherRp.approvals[0].check.detail).toContain("different website");

    const one = record();
    one.payload.approvals = one.payload.approvals.slice(0, 1);
    const v = await verifyDossier(one, KEYS, RP);
    expect(v.approvals[1].check).toEqual({ ok: false, detail: "Signature missing." });
    expect(v.authentic).toBe(false);
  });

  it("refuses the manager's passkey used for the treasurer too", async () => {
    const r = record();
    r.payload.approvals[1] = { ...r.payload.approvals[0], role: "treasurer" };
    expect((await verifyDossier(r, KEYS, RP)).approvals[1].check.ok).toBe(false);
  });

  it("reports a revoked dossier as revoked even though its signatures hold", async () => {
    const v = await verifyDossier(
      record({ status: "revoked", revoked_at: "2026-11-06T09:00:00+03:00", revoke_reason: "test" }),
      KEYS,
      RP,
    );
    expect([v.authentic, v.status]).toEqual([true, "revoked"]);
  });
});

describe("RS256 passkeys (older Windows Hello)", () => {
  async function rsaApproval(flags = 0x05): Promise<{ a: SealedApproval; challenge: Bytes }> {
    const challenge = await sha256(canonicalize(approvalPayloadOf(PAYLOAD)));
    const pair = await crypto.subtle.generateKey(
      {
        name: "RSASSA-PKCS1-v1_5",
        modulusLength: 2048,
        publicExponent: new Uint8Array([1, 0, 1]),
        hash: "SHA-256",
      },
      true,
      ["sign", "verify"],
    );
    const jwk = await crypto.subtle.exportKey("jwk", pair.publicKey);
    const clientData = new TextEncoder().encode(
      JSON.stringify({ type: "webauthn.get", challenge: toB64url(challenge), origin: RP.origins[0] }),
    );
    const authData = concat(
      await sha256(new TextEncoder().encode(RP.rpId)),
      new Uint8Array([flags, 0, 0, 0, 1]),
    );
    const signature = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5",
      pair.privateKey,
      concat(authData, await sha256(clientData)),
    );
    return {
      challenge,
      a: {
        role: "manager",
        signed_at: "2026-11-04T10:00:00+03:00",
        cred_id: "rsa",
        pubkey: { kty: "RSA", alg: "RS256", n: jwk.n!, e: jwk.e! },
        authenticatorData: toB64url(authData),
        clientDataJSON: toB64url(clientData),
        signature: toB64url(new Uint8Array(signature)),
      },
    };
  }

  it("verifies an RS256 assertion, and requires user verification", async () => {
    const good = await rsaApproval();
    expect((await checkApproval(good.a, good.challenge, RP)).ok).toBe(true);
    const presenceOnly = await rsaApproval(0x01);
    expect((await checkApproval(presenceOnly.a, presenceOnly.challenge, RP)).detail).toContain(
      "wasn't verified",
    );
  });

  it("refuses a key labelled with any algorithm but RS256 or ES256", async () => {
    const good = await rsaApproval();
    const ps256 = { ...good.a, pubkey: { ...good.a.pubkey, alg: "PS256" } } as unknown as SealedApproval;
    expect((await checkApproval(ps256, good.challenge, RP)).ok).toBe(false);

    const ec = record();
    (ec.payload.approvals[0].pubkey as { alg: string }).alg = "ES384";
    expect((await verifyDossier(ec, KEYS, RP)).approvals[0].check.ok).toBe(false);
  });
});

describe("damaged records", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const damage: [string, (p: any) => void][] = [
    ["no approvals", (p) => delete p.approvals],
    ["null approvals", (p) => (p.approvals = null)],
    ["no kid", (p) => delete p.kid],
    ["no club", (p) => delete p.club],
    ["a fractional amount", (p) => (p.totals_cents.transport = 1.5)],
    ["a planned spend without an amount", (p) => (p.planned_spends = [{ supplier: "x" }])],
  ];

  it.each(damage)("fails every check, without throwing, on %s", async (_, mutate) => {
    const r = record();
    mutate(r.payload);
    expect(isDisplayable(r)).toBe(false);
    const v = await verifyDossier(r, KEYS, RP);
    expect(v.authentic).toBe(false);
    expect(v.seal.detail).toContain("damaged");
  });

  it("accepts the genuine record as displayable", () => {
    expect(isDisplayable(record())).toBe(true);
    expect(isDisplayable(null)).toBe(false);
  });
});
