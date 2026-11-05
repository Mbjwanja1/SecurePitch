import { describe, expect, it } from "vitest";

import { canonicalize } from "../lib/crypto/canonical";
import { type Bytes, concat, sha256, toB64url } from "../lib/crypto/encoding";
import {
  type SealedPayload,
  verifyDossier,
} from "../lib/crypto/verify-dossier";

const RP_ID = "localhost";
const ORIGIN = "http://localhost:3000";
const enc = (s: string) => new TextEncoder().encode(s);

function derInt(b: Uint8Array): number[] {
  let i = 0;
  while (i < b.length - 1 && b[i] === 0) i++;
  let v = Array.from(b.slice(i));
  if (v[0] & 0x80) v = [0, ...v];
  return [0x02, v.length, ...v];
}
function rawToDer(raw: Uint8Array): Bytes {
  const body = [...derInt(raw.slice(0, 32)), ...derInt(raw.slice(32))];
  return Uint8Array.from([0x30, body.length, ...body]);
}
const ec = () =>
  crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, [
    "sign",
    "verify",
  ]);

async function approval(role: string, challenge: Bytes) {
  const kp = await ec();
  const authenticatorData = concat(
    await sha256(enc(RP_ID)),
    new Uint8Array([0x05]),
    new Uint8Array(4),
  );
  const clientDataJSON = enc(
    JSON.stringify({
      type: "webauthn.get",
      challenge: toB64url(challenge),
      origin: ORIGIN,
    }),
  );
  const signed = concat(authenticatorData, await sha256(clientDataJSON));
  const raw = new Uint8Array(
    await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      kp.privateKey,
      signed,
    ),
  );
  const jwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
  return {
    role,
    cred_id: `cred-${role}`,
    pubkey: {
      kty: "EC",
      crv: "P-256",
      alg: "ES256" as const,
      x: jwk.x!,
      y: jwk.y!,
    },
    authenticatorData: toB64url(authenticatorData),
    clientDataJSON: toB64url(clientDataJSON),
    signature: toB64url(rawToDer(raw)),
  };
}

async function sealedFixture() {
  const approvalPayload = {
    v: 1,
    dossier_id: "d1",
    club: { id: "c1", name: "Synthetic Lionesses FC" },
    merkle_root: "ab".repeat(32),
    rows_total: 47,
    rows_disclosed: 20,
    totals_cents: { transport: 462600 },
  };
  const c = await sha256(canonicalize(approvalPayload));
  const sealed = {
    ...approvalPayload,
    kid: "sp-test-1",
    approvals: [await approval("manager", c), await approval("treasurer", c)],
    sealed_at: "2026-11-05T14:02:11+03:00",
  } as SealedPayload;

  const platform = await ec();
  const raw = new Uint8Array(
    await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      platform.privateKey,
      canonicalize(sealed),
    ),
  );
  const pj = await crypto.subtle.exportKey("jwk", platform.publicKey);
  return {
    sealed,
    signature: toB64url(rawToDer(raw)),
    keys: [
      {
        kid: "sp-test-1",
        kty: "EC" as const,
        crv: "P-256" as const,
        alg: "ES256" as const,
        x: pj.x!,
        y: pj.y!,
      },
    ],
  };
}

const base = {
  status: "sealed" as const,
  expectedOrigin: ORIGIN,
  expectedRpId: RP_ID,
};
const failed = (r: Awaited<ReturnType<typeof verifyDossier>>) =>
  r.checks.filter((c) => !c.ok).map((c) => c.id);

describe("verifyDossier", () => {
  it("passes a genuine sealed dossier", async () => {
    const f = await sealedFixture();
    const r = await verifyDossier({
      ...base,
      ...f,
      fragmentRoot: f.sealed.merkle_root,
    });
    expect(failed(r)).toEqual([]);
    expect(r.ok).toBe(true);
  });

  it("fails when a number is changed after sealing", async () => {
    const f = await sealedFixture();
    const r = await verifyDossier({
      ...base,
      ...f,
      sealed: { ...f.sealed, rows_total: 99 },
    });
    expect(r.ok).toBe(false);
    expect(failed(r)).toEqual(
      expect.arrayContaining(["seal", "manager", "treasurer"]),
    );
  });

  it("fails when an approval is missing", async () => {
    const f = await sealedFixture();
    const sealed = {
      ...f.sealed,
      approvals: f.sealed.approvals.slice(0, 1),
    } as SealedPayload;
    const r = await verifyDossier({ ...base, ...f, sealed });
    expect(failed(r)).toContain("treasurer");
  });

  it("fails when the platform key is unknown", async () => {
    const f = await sealedFixture();
    const r = await verifyDossier({ ...base, ...f, keys: [] });
    expect(failed(r)).toEqual(["seal"]);
  });

  it("fails when the QR root belongs to another dossier", async () => {
    const f = await sealedFixture();
    const r = await verifyDossier({
      ...base,
      ...f,
      fragmentRoot: "cd".repeat(32),
    });
    expect(failed(r)).toEqual(["root"]);
  });

  it("fails a revoked dossier even when the signatures are valid", async () => {
    const f = await sealedFixture();
    const r = await verifyDossier({ ...base, ...f, status: "revoked" });
    expect(failed(r)).toEqual(["status"]);
  });
});
