// Turns a passkey's COSE public key (as stored by the engine) into a WebCrypto key.
// Handles the two algorithms the engine accepts: ES256 (EC P-256) and RS256 (RSA).
import { type Bytes, toB64url } from "./encoding";

type Cbor = number | Uint8Array | string | Map<number | string, Cbor>;

function read(buf: Uint8Array, pos: { i: number }): Cbor {
  const first = buf[pos.i++];
  if (first === undefined) throw new Error("truncated COSE key");
  const major = first >> 5;
  const info = first & 0x1f;
  let len: number;
  if (info < 24) len = info;
  else if (info === 24) len = buf[pos.i++];
  else if (info === 25) {
    len = (buf[pos.i] << 8) | buf[pos.i + 1];
    pos.i += 2;
  } else throw new Error("unsupported CBOR length in COSE key");
  if (len === undefined || Number.isNaN(len))
    throw new Error("truncated COSE key");

  switch (major) {
    case 0:
      return len;
    case 1:
      return -1 - len;
    case 2:
    case 3: {
      const out = buf.slice(pos.i, pos.i + len);
      if (out.length !== len) throw new Error("truncated COSE key");
      pos.i += len;
      return major === 2 ? out : new TextDecoder().decode(out);
    }
    case 5: {
      const map = new Map<number | string, Cbor>();
      for (let n = 0; n < len; n++) {
        const k = read(buf, pos);
        if (typeof k !== "number" && typeof k !== "string")
          throw new Error("bad COSE map key");
        map.set(k, read(buf, pos));
      }
      return map;
    }
    default:
      throw new Error("unsupported CBOR type in COSE key");
  }
}

function bytesOf(map: Map<number | string, Cbor>, label: number): Uint8Array {
  const v = map.get(label);
  if (!(v instanceof Uint8Array))
    throw new Error(`COSE key is missing field ${label}`);
  return v;
}

export type PasskeyKey = { key: CryptoKey; alg: "ES256" | "RS256" };

export async function coseToKey(cose: Bytes): Promise<PasskeyKey> {
  const map = read(cose, { i: 0 });
  if (!(map instanceof Map)) throw new Error("COSE key is not a map");
  const kty = map.get(1);
  const alg = map.get(3);

  if (kty === 2 && alg === -7 && map.get(-1) === 1) {
    const key = await crypto.subtle.importKey(
      "jwk",
      {
        kty: "EC",
        crv: "P-256",
        x: toB64url(bytesOf(map, -2)),
        y: toB64url(bytesOf(map, -3)),
        ext: true,
      },
      { name: "ECDSA", namedCurve: "P-256" },
      false,
      ["verify"],
    );
    return { key, alg: "ES256" };
  }
  if (kty === 3 && alg === -257) {
    const key = await crypto.subtle.importKey(
      "jwk",
      {
        kty: "RSA",
        alg: "RS256",
        n: toB64url(bytesOf(map, -1)),
        e: toB64url(bytesOf(map, -2)),
        ext: true,
      },
      { name: "RSASSA-PKCS1-v1_5", hash: "SHA-256" },
      false,
      ["verify"],
    );
    return { key, alg: "RS256" };
  }
  throw new Error("unsupported passkey algorithm");
}
