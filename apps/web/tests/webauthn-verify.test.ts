import { describe, expect, it } from "vitest";

import { type Bytes, concat, sha256, toB64url } from "../lib/crypto/encoding";
import {
  approvalPayload,
  verifyAssertion,
} from "../lib/crypto/webauthn-verify";

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

async function makeAssertion(challenge: Bytes, flags = 0x05, origin = ORIGIN) {
  const kp = await crypto.subtle.generateKey(
    { name: "ECDSA", namedCurve: "P-256" },
    true,
    ["sign", "verify"],
  );
  const authenticatorData = concat(
    await sha256(enc(RP_ID)),
    new Uint8Array([flags]),
    new Uint8Array(4),
  );
  const clientDataJSON = enc(
    JSON.stringify({
      type: "webauthn.get",
      challenge: toB64url(challenge),
      origin,
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
  return {
    authenticatorData,
    clientDataJSON,
    signature: rawToDer(raw),
    publicKey: kp.publicKey,
  };
}

const challenge = Uint8Array.from({ length: 32 }, (_, i) => i);
const base = {
  alg: "ES256" as const,
  expectedChallenge: challenge,
  expectedOrigin: ORIGIN,
  expectedRpId: RP_ID,
};

describe("verifyAssertion", () => {
  it("accepts a valid assertion", async () => {
    expect(
      await verifyAssertion({ ...base, ...(await makeAssertion(challenge)) }),
    ).toEqual({ ok: true });
  });
  it("rejects a different challenge", async () => {
    const other = Uint8Array.from({ length: 32 }, () => 7);
    const r = await verifyAssertion({
      ...base,
      ...(await makeAssertion(other)),
    });
    expect(r.ok).toBe(false);
  });
  it("rejects when user verification is missing", async () => {
    const r = await verifyAssertion({
      ...base,
      ...(await makeAssertion(challenge, 0x01)),
    });
    expect(r).toEqual({ ok: false, reason: "user verification flag not set" });
  });
  it("rejects the wrong origin", async () => {
    const r = await verifyAssertion({
      ...base,
      ...(await makeAssertion(challenge, 0x05, "https://evil.example")),
    });
    expect(r).toEqual({ ok: false, reason: "wrong origin" });
  });
  it("rejects a signature made by a different key", async () => {
    const a = await makeAssertion(challenge);
    const b = await makeAssertion(challenge);
    expect(
      (await verifyAssertion({ ...base, ...a, publicKey: b.publicKey })).ok,
    ).toBe(false);
  });
});

describe("approvalPayload", () => {
  it("removes exactly the three fields sealing adds", () => {
    const sealed = {
      v: 1,
      dossier_id: "x",
      kid: "k",
      approvals: [],
      sealed_at: "t",
    };
    expect(approvalPayload(sealed)).toEqual({ v: 1, dossier_id: "x" });
  });
});
