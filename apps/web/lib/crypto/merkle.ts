// Merkle tree (docs/CRYPTO_SPEC.md section 3). Must match services/engine/app/crypto/merkle.py.
import { canonicalize } from "./canonical";
import { type Bytes, concat, equalBytes, fromHex, sha256, toHex } from "./encoding";

const LEAF_PREFIX = new Uint8Array([0x00]);
const NODE_PREFIX = new Uint8Array([0x01]);

export type ProofStep = { side: "L" | "R"; hash: string }; // hash is hex, as in the vectors

export function leafHash(obj: unknown): Promise<Bytes> {
  return sha256(concat(LEAF_PREFIX, canonicalize(obj)));
}

export function nodeHash(left: Uint8Array, right: Uint8Array): Promise<Bytes> {
  return sha256(concat(NODE_PREFIX, left, right));
}

async function levels(leaves: Bytes[]): Promise<Bytes[][]> {
  if (leaves.length === 0) throw new Error("a Merkle tree needs at least one leaf");
  const all = [leaves];
  while (all[all.length - 1].length > 1) {
    const level = all[all.length - 1];
    const next: Bytes[] = [];
    for (let i = 0; i + 1 < level.length; i += 2) next.push(await nodeHash(level[i], level[i + 1]));
    if (level.length % 2) next.push(level[level.length - 1]); // promote, never duplicate
    all.push(next);
  }
  return all;
}

export async function merkleRoot(leaves: Bytes[]): Promise<Bytes> {
  const all = await levels(leaves);
  return all[all.length - 1][0];
}

export async function inclusionProof(leaves: Bytes[], index: number): Promise<ProofStep[]> {
  if (index < 0 || index >= leaves.length) throw new RangeError("leaf index out of range");
  const proof: ProofStep[] = [];
  const all = await levels(leaves);
  for (const level of all.slice(0, -1)) {
    if (index % 2) proof.push({ side: "L", hash: toHex(level[index - 1]) });
    else if (index + 1 < level.length) proof.push({ side: "R", hash: toHex(level[index + 1]) });
    index = Math.floor(index / 2);
  }
  return proof;
}

export async function verifyInclusion(
  leaf: Uint8Array,
  proof: ProofStep[],
  root: Uint8Array,
): Promise<boolean> {
  let h: Uint8Array = leaf;
  for (const step of proof) {
    const sibling = fromHex(step.hash);
    h = step.side === "L" ? await nodeHash(sibling, h) : await nodeHash(h, sibling);
  }
  return equalBytes(h, root);
}
