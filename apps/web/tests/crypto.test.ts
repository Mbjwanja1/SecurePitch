import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { CanonicalizationError, canonicalize, canonicalString } from "@/lib/crypto/canonical";
import {
  derToRaw,
  importPublicJwk,
  type PublicJwk,
  verifyPayloadSignature,
} from "@/lib/crypto/ecdsa";
import { fromB64url, sha256, toB64url, toHex } from "@/lib/crypto/encoding";
import {
  inclusionProof,
  leafHash,
  merkleRoot,
  nodeHash,
  type ProofStep,
  verifyInclusion,
} from "@/lib/crypto/merkle";

// Shape of spec/test-vectors.json (written by tools/gen_vectors.py).
type Vectors = {
  canonical: { name: string; input: unknown; canonical: string; sha256: string }[];
  leaves: { name: string; leaf: unknown; leaf_hash: string }[];
  trees: {
    size: number;
    leaf_objects: unknown[];
    leaf_hashes: string[];
    root: string;
    proofs: { index: number; steps: ProofStep[] }[];
  }[];
  signature: {
    public_jwk: PublicJwk;
    payload: unknown;
    canonical: string;
    digest: string;
    signature_der: string;
    signature_raw: string;
    tampered_payload: unknown;
  };
  approval: {
    leaf_objects: unknown[];
    payload: { merkle_root: string; rows_disclosed: number };
    canonical: string;
    challenge: string;
    challenge_b64url: string;
  };
  sealed: {
    payload: Record<string, unknown> & { approvals: { clientDataJSON: string }[] };
    canonical: string;
    digest: string;
    signature_der: string;
  };
};

// The same file the Python engine tests against. If both suites pass, they agree.
const vectors: Vectors = JSON.parse(
  readFileSync(resolve(__dirname, "../../../spec/test-vectors.json"), "utf-8"),
);

describe("canonical JSON", () => {
  it.each(vectors.canonical)("$name matches the Python output", async (c) => {
    expect(canonicalString(c.input)).toBe(c.canonical);
    expect(toHex(await sha256(canonicalize(c.input)))).toBe(c.sha256);
  });

  it.each([{ score: 0.94 }, { x: [1, 2.5] }, { big: 2 ** 53 }])("rejects unsafe value %j", (bad) => {
    expect(() => canonicalize(bad)).toThrow(CanonicalizationError);
  });
});

describe("Merkle tree", () => {
  it.each(vectors.leaves)("leaf hash for $name", async (l) => {
    expect(toHex(await leafHash(l.leaf))).toBe(l.leaf_hash);
  });

  it.each(vectors.trees)("tree of $size leaves: root and proofs", async (t) => {
    const hashes = await Promise.all(t.leaf_objects.map((o) => leafHash(o)));
    expect(hashes.map(toHex)).toEqual(t.leaf_hashes);
    const root = await merkleRoot(hashes);
    expect(toHex(root)).toBe(t.root);
    for (const p of t.proofs) {
      expect(await inclusionProof(hashes, p.index)).toEqual(p.steps);
      expect(await verifyInclusion(hashes[p.index], p.steps, root)).toBe(true);
    }
  });

  it("promotes an odd node instead of duplicating it", async () => {
    const [a, b, c] = await Promise.all([0, 1, 2].map((i) => leafHash({ i })));
    const root = toHex(await merkleRoot([a, b, c]));
    expect(root).toBe(toHex(await nodeHash(await nodeHash(a, b), c)));
    expect(root).not.toBe(toHex(await merkleRoot([a, b, c, c])));
  });

  it("rejects a proof for the wrong leaf", async () => {
    const hashes = await Promise.all([0, 1, 2, 3, 4, 5, 6].map((i) => leafHash({ i })));
    const root = await merkleRoot(hashes);
    const proof = await inclusionProof(hashes, 3);
    expect(await verifyInclusion(hashes[4], proof, root)).toBe(false);
  });

  it("refuses an empty tree", async () => {
    await expect(merkleRoot([])).rejects.toThrow();
  });
});

describe("ES256 platform seal", () => {
  const sig = vectors.signature;

  it("canonical payload and digest match the engine", async () => {
    expect(canonicalString(sig.payload)).toBe(sig.canonical);
    expect(toHex(await sha256(canonicalize(sig.payload)))).toBe(sig.digest);
  });

  it("converts KMS-style DER signatures to WebCrypto raw form", () => {
    expect(toB64url(derToRaw(fromB64url(sig.signature_der)))).toBe(sig.signature_raw);
  });

  it("verifies the signed payload with WebCrypto", async () => {
    const key = await importPublicJwk(sig.public_jwk);
    expect(await verifyPayloadSignature(key, sig.payload, sig.signature_der)).toBe(true);
  });

  it("rejects the tampered payload", async () => {
    const key = await importPublicJwk(sig.public_jwk);
    expect(await verifyPayloadSignature(key, sig.tampered_payload, sig.signature_der)).toBe(false);
  });

  it("rejects a garbled signature without throwing", async () => {
    const key = await importPublicJwk(sig.public_jwk);
    expect(await verifyPayloadSignature(key, sig.payload, "AAAA")).toBe(false);
  });
});

describe("base64url decoding (same rules as the engine)", () => {
  const text = (bytes: Uint8Array) => new TextDecoder().decode(bytes);

  it.each([
    ["Zm9v", "foo"],
    ["Zm8", "fo"],
    ["Zm8=", "fo"],
    ["Zg==", "f"],
    ["Zm9v=", "foo"],
    ["", ""],
  ])("accepts %j", (input, expected) => {
    expect(text(fromB64url(input))).toBe(expected);
  });

  it.each(["Zm9v!!", "Zm 9v", "Zm9v+", "Z", "Zg===", "Zm9v/"])("rejects %j", (bad) => {
    expect(() => fromB64url(bad)).toThrow("invalid base64url");
  });
});

describe("base64url encoding of large inputs", () => {
  it("encodes 5 MB (a receipt photo) without overflowing the call stack and round-trips", () => {
    const bytes = new Uint8Array(5 * 1024 * 1024);
    for (let i = 0; i < bytes.length; i++) bytes[i] = (i * 31 + 7) & 0xff;
    const decoded = fromB64url(toB64url(bytes));
    expect(decoded.length).toBe(bytes.length);
    expect(decoded.every((v, i) => v === bytes[i])).toBe(true);
  });

  it("matches Node's base64url for chunk-boundary sizes", () => {
    for (const n of [0, 1, 2, 3, 0x8000 - 1, 0x8000, 0x8000 + 1, 3 * 0x8000 + 2]) {
      const bytes = Uint8Array.from({ length: n }, (_, i) => (i * 17) & 0xff);
      expect(toB64url(bytes)).toBe(Buffer.from(bytes).toString("base64url"));
    }
  });
});

describe("passkey approval challenge (CRYPTO_SPEC section 6)", () => {
  const a = vectors.approval;

  it("rebuilds the signed Merkle root from the leaves", async () => {
    const hashes = await Promise.all(a.leaf_objects.map((o) => leafHash(o)));
    expect(toHex(await merkleRoot(hashes))).toBe(a.payload.merkle_root);
    expect(a.payload.rows_disclosed).toBe(a.leaf_objects.length);
  });

  it("rebuilds the challenge both approvers' passkeys signed", async () => {
    expect(canonicalString(a.payload)).toBe(a.canonical);
    const challenge = await sha256(canonicalize(a.payload));
    expect(toHex(challenge)).toBe(a.challenge);
    expect(toB64url(challenge)).toBe(a.challenge_b64url); // as in clientDataJSON.challenge
  });
});

describe("sealed dossier (CRYPTO_SPEC section 5)", () => {
  const s = vectors.sealed;

  it("verifies the platform seal over the whole sealed payload", async () => {
    expect(canonicalString(s.payload)).toBe(s.canonical);
    expect(toHex(await sha256(canonicalize(s.payload)))).toBe(s.digest);
    const key = await importPublicJwk(vectors.signature.public_jwk);
    expect(await verifyPayloadSignature(key, s.payload, s.signature_der)).toBe(true);
  });

  it("rebuilds the approvers' challenge by removing kid, approvals and sealed_at", async () => {
    const { kid, approvals, sealed_at, ...approved } = s.payload;
    expect([kid, sealed_at]).not.toContain(undefined);
    expect(approved).toEqual(vectors.approval.payload);
    for (const a of approvals) {
      const clientData = JSON.parse(new TextDecoder().decode(fromB64url(a.clientDataJSON)));
      expect(clientData.challenge).toBe(vectors.approval.challenge_b64url);
    }
  });

  it("any change to the sealed payload breaks the seal", async () => {
    const key = await importPublicJwk(vectors.signature.public_jwk);
    const tampered = { ...s.payload, rows_disclosed: 2 };
    expect(await verifyPayloadSignature(key, tampered, s.signature_der)).toBe(false);
  });
});
