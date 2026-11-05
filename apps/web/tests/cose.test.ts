import { describe, expect, it } from "vitest";

import { coseToKey } from "../lib/crypto/cose";
import { concat, fromB64url } from "../lib/crypto/encoding";

const b = (...n: number[]) => Uint8Array.from(n);
const msg = new TextEncoder().encode("hello");

describe("coseToKey", () => {
  it("imports an ES256 key that verifies a real signature", async () => {
    const kp = await crypto.subtle.generateKey(
      { name: "ECDSA", namedCurve: "P-256" },
      true,
      ["sign", "verify"],
    );
    const jwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
    // {1:2, 3:-7, -1:1, -2:x, -3:y}
    const cose = concat(
      b(0xa5, 0x01, 0x02, 0x03, 0x26, 0x20, 0x01, 0x21, 0x58, 0x20),
      fromB64url(jwk.x!),
      b(0x22, 0x58, 0x20),
      fromB64url(jwk.y!),
    );
    const { key, alg } = await coseToKey(cose);
    expect(alg).toBe("ES256");
    const sig = await crypto.subtle.sign(
      { name: "ECDSA", hash: "SHA-256" },
      kp.privateKey,
      msg,
    );
    expect(
      await crypto.subtle.verify(
        { name: "ECDSA", hash: "SHA-256" },
        key,
        sig,
        msg,
      ),
    ).toBe(true);
  });

  it("imports an RS256 key that verifies a real signature", async () => {
    const kp = await crypto.subtle.generateKey(
      {
        name: "RSASSA-PKCS1-v1_5",
        modulusLength: 2048,
        publicExponent: b(1, 0, 1),
        hash: "SHA-256",
      },
      true,
      ["sign", "verify"],
    );
    const jwk = await crypto.subtle.exportKey("jwk", kp.publicKey);
    // {1:3, 3:-257, -1:n, -2:e}
    const cose = concat(
      b(0xa4, 0x01, 0x03, 0x03, 0x39, 0x01, 0x00, 0x20, 0x59, 0x01, 0x00),
      fromB64url(jwk.n!),
      b(0x21, 0x43),
      fromB64url(jwk.e!),
    );
    const { key, alg } = await coseToKey(cose);
    expect(alg).toBe("RS256");
    const sig = await crypto.subtle.sign(
      { name: "RSASSA-PKCS1-v1_5" },
      kp.privateKey,
      msg,
    );
    expect(
      await crypto.subtle.verify({ name: "RSASSA-PKCS1-v1_5" }, key, sig, msg),
    ).toBe(true);
  });

  it("rejects an unsupported algorithm", async () => {
    await expect(coseToKey(b(0xa2, 0x01, 0x02, 0x03, 0x27))).rejects.toThrow();
  });
});
