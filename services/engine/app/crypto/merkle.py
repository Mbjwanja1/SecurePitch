"""Merkle tree over dossier rows (docs/CRYPTO_SPEC.md section 3)."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal

from app.crypto.canonical import canonicalize, sha256

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


@dataclass(frozen=True)
class ProofStep:
    side: Literal["L", "R"]  # which side the sibling sits on
    hash: bytes

    def to_json(self) -> dict[str, str]:
        return {"side": self.side, "hash": self.hash.hex()}


def leaf_hash(obj: Any) -> bytes:
    return sha256(LEAF_PREFIX + canonicalize(obj))


def node_hash(left: bytes, right: bytes) -> bytes:
    return sha256(NODE_PREFIX + left + right)


def sort_leaf_objects(objs: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order rows by (ts, tx) so the same set of rows always gives the same root."""
    return sorted(objs, key=lambda o: (o["ts"], o["tx"]))


def _levels(leaves: Sequence[bytes]) -> list[list[bytes]]:
    if not leaves:
        raise ValueError("a Merkle tree needs at least one leaf")
    levels = [list(leaves)]
    while len(levels[-1]) > 1:
        level = levels[-1]
        nxt = [node_hash(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
        if len(level) % 2:
            nxt.append(level[-1])  # promote the unpaired node; never duplicate it
        levels.append(nxt)
    return levels


def merkle_root(leaves: Sequence[bytes]) -> bytes:
    return _levels(leaves)[-1][0]


def inclusion_proof(leaves: Sequence[bytes], index: int) -> list[ProofStep]:
    if not 0 <= index < len(leaves):
        raise IndexError("leaf index out of range")
    proof = []
    for level in _levels(leaves)[:-1]:
        if index % 2:
            proof.append(ProofStep("L", level[index - 1]))
        elif index + 1 < len(level):
            proof.append(ProofStep("R", level[index + 1]))
        index //= 2
    return proof


def verify_inclusion(leaf: bytes, proof: Sequence[ProofStep], root: bytes) -> bool:
    h = leaf
    for step in proof:
        h = node_hash(step.hash, h) if step.side == "L" else node_hash(h, step.hash)
    return h == root
