// ES256 signature verification in the browser (docs/CRYPTO_SPEC.md section 5).
import { canonicalize } from "./canonical";
import { type Bytes, fromB64url } from "./encoding";

export type PublicJwk = { kid: string; kty: "EC"; crv: "P-256"; alg: "ES256"; x: string; y: string };

/**
 * KMS returns DER-encoded ECDSA signatures; WebCrypto's verify() expects raw 64-byte r||s.
 * DER: 0x30 len 0x02 rLen r 0x02 sLen s, where r and s may carry a leading 0x00.
 */
export function derToRaw(der: Uint8Array): Bytes {
  let i = 0;
  const expect = (byte: number) => {
    if (der[i++] !== byte) throw new Error("malformed DER signature");
  };
  const readInt = (): Uint8Array => {
    expect(0x02);
    const len = der[i++];
    let int = der.subarray(i, i + len);
    i += len;
    while (int.length > 32 && int[0] === 0x00) int = int.subarray(1);
    if (int.length > 32 || int.length === 0) throw new Error("malformed DER signature");
    return int;
  };
  expect(0x30);
  const total = der[i++];
  if (total !== der.length - 2) throw new Error("malformed DER signature");
  const r = readInt();
  const s = readInt();
  if (i !== der.length) throw new Error("malformed DER signature");
  const raw = new Uint8Array(64);
  raw.set(r, 32 - r.length);
  raw.set(s, 64 - s.length);
  return raw;
}

export function importPublicJwk(jwk: PublicJwk): Promise<CryptoKey> {
  return crypto.subtle.importKey(
    "jwk",
    { kty: jwk.kty, crv: jwk.crv, x: jwk.x, y: jwk.y, ext: true },
    { name: "ECDSA", namedCurve: "P-256" },
    false,
    ["verify"],
  );
}

/**
 * Verify a platform seal. WebCrypto hashes its input itself, so it receives the canonical
 * payload bytes, not the digest the signer signed: SHA-256 is applied exactly once either way.
 */
export async function verifyPayloadSignature(
  key: CryptoKey,
  payload: unknown,
  signatureDerB64url: string,
): Promise<boolean> {
  let raw: Bytes;
  try {
    raw = derToRaw(fromB64url(signatureDerB64url));
  } catch {
    return false;
  }
  return crypto.subtle.verify(
    { name: "ECDSA", hash: "SHA-256" },
    key,
    raw,
    canonicalize(payload),
  );
}
