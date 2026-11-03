"""Generate spec/test-vectors.json from the Python crypto implementation.

    uv run --project services/engine python tools/gen_vectors.py          write the file
    uv run --project services/engine python tools/gen_vectors.py --check  exit 1 if out of date

Everything here is synthetic. The signing key is derived from a public seed: test use only.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "engine"))

from app.crypto.canonical import b64url, canonicalize, sha256  # noqa: E402
from app.crypto.merkle import inclusion_proof, leaf_hash, merkle_root  # noqa: E402
from app.crypto.signer import (  # noqa: E402
    LocalSigner,
    der_to_raw,
    payload_digest,
    public_jwk,
)
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

OUT = ROOT / "spec" / "test-vectors.json"
TEST_KID = "test-vector-key-v1"

CANONICAL_CASES: list[tuple[str, Any]] = [
    ("key ordering and nesting", {"b": 2, "a": 1, "c": {"z": True, "y": None}}),
    (
        "string escapes",
        {"note": 'Line 1\nTab\there "quoted" \\ backslash', "ctrl": "\u0001"},
    ),
    ("non-ASCII text", {"name": "Wanjikũ Nyambura", "venue": "Camp Toyoyo – Jericho"}),
    ("integers", {"amt": 25000, "neg": -300, "zero": 0, "max_safe": 9007199254740991}),
    ("arrays and empties", {"list": [3, 1, 2], "empty_list": [], "empty_obj": {}}),
]

LEAVES: list[tuple[str, dict[str, Any]]] = [
    (
        "squad transport allowance",
        {
            "v": 1,
            "branch": "B",
            "tx": "SJK3ABC12D",
            "ts": "2026-10-17T07:15:00+03:00",
            "amt": 25000,
            "dir": "out",
            "cp": {"type": "player", "ref": "hmac:" + "ab" * 32},
            "cat": "transport",
            "fixture": "MD4-2026-10-17",
            "ev": {"receipt_sha256": None, "attest": [], "corroborated": True},
            "salt": "q3VbZ0xPa2N1dGVzdA",
        },
    ),
    (
        "merchant kit purchase",
        {
            "v": 1,
            "branch": "A",
            "tx": "SJL7KIT01Q",
            "ts": "2026-10-20T15:42:10+03:00",
            "amt": 2200000,
            "dir": "out",
            "cp": {"type": "till", "ref": "512345"},
            "cat": "kit",
            "fixture": None,
            "ev": {"receipt_sha256": "cd" * 32, "attest": [], "corroborated": False},
            "salt": "c2FsdC1mb3Ita2l0",
        },
    ),
    (
        "club income",
        {
            "v": 1,
            "branch": "I",
            "tx": "SJM2INC99Z",
            "ts": "2026-10-17T06:30:00+03:00",
            "amt": 400000,
            "dir": "in",
            "cp": {"type": "person", "ref": "hmac:" + "ef" * 32},
            "cat": "income",
            "fixture": None,
            "ev": {"receipt_sha256": None, "attest": [], "corroborated": False},
            "salt": "aW5jb21lLXNhbHQ",
        },
    ),
]

TREE_SIZES = [1, 2, 3, 4, 5, 7, 18]

PAYLOAD: dict[str, Any] = {
    "v": 1,
    "kid": TEST_KID,
    "dossier_id": "00000000-0000-4000-8000-000000000001",
    "club": {
        "id": "00000000-0000-4000-8000-0000000000c1",
        "name": "Synthetic Lionesses FC",
    },
    "period": {"from": "2026-10-01", "to": "2026-10-31"},
    "rows_total": 214,
    "rows_disclosed": 27,
    "totals_cents": {"transport": 750000, "kit": 2200000, "income": 720000},
    "integrity": {"score_bp": 9400, "balance_chain": True, "summary_match": True},
    "merkle_root": "",  # filled below
}


def test_signer() -> LocalSigner:
    scalar = int.from_bytes(sha256(b"securepitch public test vector key v1"), "big")
    return LocalSigner(TEST_KID, ec.derive_private_key(scalar, ec.SECP256R1()))


def build() -> dict[str, Any]:
    canonical = [
        {
            "name": name,
            "input": value,
            "canonical": canonicalize(value).decode("utf-8"),
            "sha256": sha256(canonicalize(value)).hex(),
        }
        for name, value in CANONICAL_CASES
    ]

    leaves = [{"name": n, "leaf": obj, "leaf_hash": leaf_hash(obj).hex()} for n, obj in LEAVES]

    trees = []
    for size in TREE_SIZES:
        hashes = [leaf_hash({"v": 1, "i": i}) for i in range(size)]
        indices = sorted({0, size // 2, size - 1})
        trees.append(
            {
                "size": size,
                "leaf_objects": [{"v": 1, "i": i} for i in range(size)],
                "leaf_hashes": [h.hex() for h in hashes],
                "root": merkle_root(hashes).hex(),
                "proofs": [
                    {
                        "index": i,
                        "steps": [s.to_json() for s in inclusion_proof(hashes, i)],
                    }
                    for i in indices
                ],
            }
        )

    payload = dict(PAYLOAD, merkle_root=merkle_root([leaf_hash(o) for _, o in LEAVES]).hex())
    tampered = json.loads(json.dumps(payload))
    tampered["totals_cents"]["kit"] = 2900000

    signer = test_signer()
    digest = payload_digest(payload)
    sig = signer.sign_digest(digest, deterministic=True)
    signature = {
        "kid": TEST_KID,
        "public_key_spki": b64url(signer.public_key_der()),
        "public_jwk": public_jwk(TEST_KID, signer.public_key_der()),
        "payload": payload,
        "canonical": canonicalize(payload).decode("utf-8"),
        "digest": digest.hex(),
        "signature_der": b64url(sig),
        "signature_raw": b64url(der_to_raw(sig)),
        "tampered_payload": tampered,
        "note": (
            "verify(payload) must succeed; "
            "verify(tampered_payload) with the same signature must fail"
        ),
    }

    return {
        "version": 1,
        "warning": (
            "Synthetic data. The signing key is derived from a public seed: "
            "never use it outside tests."
        ),
        "canonical": canonical,
        "leaves": leaves,
        "trees": trees,
        "signature": signature,
    }


def render() -> str:
    return json.dumps(build(), indent=2, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = render()
    if args.check:
        current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
        if current != text:
            print("spec/test-vectors.json is out of date; run tools/gen_vectors.py")
            return 1
        print("spec/test-vectors.json is up to date")
        return 0
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
