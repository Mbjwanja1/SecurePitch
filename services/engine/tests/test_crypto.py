import json
from pathlib import Path

import pytest
from botocore.stub import Stubber

from app.crypto.canonical import CanonicalizationError, b64url_decode, canonicalize, sha256
from app.crypto.merkle import (
    ProofStep,
    inclusion_proof,
    leaf_hash,
    merkle_root,
    node_hash,
    sort_leaf_objects,
    verify_inclusion,
)
from app.crypto.signer import (
    KmsSigner,
    LocalSigner,
    der_to_raw,
    payload_digest,
    signer_from_env,
    verify_digest,
)

VECTORS = json.loads(
    (Path(__file__).resolve().parents[3] / "spec" / "test-vectors.json").read_text("utf-8")
)


# ---- canonical JSON -------------------------------------------------------------------


@pytest.mark.parametrize("case", VECTORS["canonical"], ids=lambda c: c["name"])
def test_canonical_vectors(case: dict) -> None:
    out = canonicalize(case["input"])
    assert out.decode("utf-8") == case["canonical"]
    assert sha256(out).hex() == case["sha256"]


@pytest.mark.parametrize("bad", [{"score": 0.94}, {"x": [1, 2.5]}, {"big": 2**53}, {1: "a"}])
def test_canonical_rejects_unsafe_values(bad: object) -> None:
    with pytest.raises(CanonicalizationError):
        canonicalize(bad)


# ---- Merkle tree ----------------------------------------------------------------------


@pytest.mark.parametrize("case", VECTORS["leaves"], ids=lambda c: c["name"])
def test_leaf_vectors(case: dict) -> None:
    assert leaf_hash(case["leaf"]).hex() == case["leaf_hash"]


@pytest.mark.parametrize("tree", VECTORS["trees"], ids=lambda t: f"size-{t['size']}")
def test_tree_vectors(tree: dict) -> None:
    hashes = [leaf_hash(o) for o in tree["leaf_objects"]]
    assert [h.hex() for h in hashes] == tree["leaf_hashes"]
    root = merkle_root(hashes)
    assert root.hex() == tree["root"]
    for p in tree["proofs"]:
        steps = [ProofStep(s["side"], bytes.fromhex(s["hash"])) for s in p["steps"]]
        assert [s.to_json() for s in inclusion_proof(hashes, p["index"])] == p["steps"]
        assert verify_inclusion(hashes[p["index"]], steps, root)


def test_odd_node_is_promoted_not_duplicated() -> None:
    a, b, c = (leaf_hash({"i": i}) for i in range(3))
    assert merkle_root([a, b, c]) == node_hash(node_hash(a, b), c)
    assert merkle_root([a, b, c]) != merkle_root([a, b, c, c])


def test_leaf_cannot_pose_as_node() -> None:
    a, b = leaf_hash({"i": 0}), leaf_hash({"i": 1})
    assert merkle_root([a, b]) != leaf_hash({"pair": (a + b).hex()})
    assert node_hash(a, b) != sha256(a + b)


def test_proof_fails_for_wrong_leaf_or_root() -> None:
    hashes = [leaf_hash({"i": i}) for i in range(7)]
    root, proof = merkle_root(hashes), inclusion_proof(hashes, 3)
    assert not verify_inclusion(hashes[4], proof, root)
    assert not verify_inclusion(hashes[3], proof, leaf_hash({"other": True}))


def test_empty_tree_is_an_error() -> None:
    with pytest.raises(ValueError):
        merkle_root([])


def test_rows_sorted_by_time_then_receipt() -> None:
    rows = [
        {"ts": "2026-10-17T09:00:00+03:00", "tx": "B"},
        {"ts": "2026-10-17T07:15:00+03:00", "tx": "Z"},
        {"ts": "2026-10-17T07:15:00+03:00", "tx": "A"},
    ]
    assert [r["tx"] for r in sort_leaf_objects(rows)] == ["A", "Z", "B"]


# ---- signatures -----------------------------------------------------------------------


def test_signature_vector_verifies_and_tamper_fails() -> None:
    sig = VECTORS["signature"]
    public = b64url_decode(sig["public_key_spki"])
    der = b64url_decode(sig["signature_der"])
    assert canonicalize(sig["payload"]).decode("utf-8") == sig["canonical"]
    assert payload_digest(sig["payload"]).hex() == sig["digest"]
    assert verify_digest(public, payload_digest(sig["payload"]), der)
    assert not verify_digest(public, payload_digest(sig["tampered_payload"]), der)
    assert der_to_raw(der) == b64url_decode(sig["signature_raw"])


def test_local_signer_round_trip_and_key_reload() -> None:
    signer = LocalSigner.generate("local-test")
    digest = payload_digest({"v": 1, "amt": 25000})
    sig = signer.sign_digest(digest)
    assert verify_digest(signer.public_key_der(), digest, sig)
    assert len(der_to_raw(sig)) == 64
    reloaded = LocalSigner.from_b64("local-test", signer.private_key_b64())
    assert reloaded.public_key_der() == signer.public_key_der()


def test_signer_rejects_non_digest_input() -> None:
    with pytest.raises(ValueError):
        LocalSigner.generate().sign_digest(b"not a digest")


def test_signer_from_env_local() -> None:
    key = LocalSigner.generate().private_key_b64()
    signer = signer_from_env({"SIGNER": "local", "LOCAL_SIGNING_KEY": key, "LOCAL_KID": "local-x"})
    assert signer.kid == "local-x"
    with pytest.raises(ValueError):
        signer_from_env({"SIGNER": "nope"})


def test_kms_signer_sends_digest_with_correct_parameters() -> None:
    import boto3

    stand_in = LocalSigner.generate()  # plays the part of the key inside KMS
    digest = payload_digest({"v": 1})
    client = boto3.client(
        "kms",
        region_name="af-south-1",
        aws_access_key_id="testing",
        aws_secret_access_key="testing",  # noqa: S106 - fake credentials for the stub
    )
    with Stubber(client) as stub:
        stub.add_response(
            "sign",
            {"Signature": stand_in.sign_digest(digest), "SigningAlgorithm": "ECDSA_SHA_256"},
            {
                "KeyId": "alias/securepitch-seal",
                "Message": digest,
                "MessageType": "DIGEST",
                "SigningAlgorithm": "ECDSA_SHA_256",
            },
        )
        stub.add_response(
            "get_public_key",
            {"PublicKey": stand_in.public_key_der()},
            {"KeyId": "alias/securepitch-seal"},
        )
        signer = KmsSigner("sp-2026-01", "alias/securepitch-seal", client)
        sig = signer.sign_digest(digest)
        assert verify_digest(signer.public_key_der(), digest, sig)


# ---- review fixes (PR 4) ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Zm9v", b"foo"),
        ("Zm8", b"fo"),
        ("Zm8=", b"fo"),
        ("Zg==", b"f"),
        ("Zm9v=", b"foo"),
        ("", b""),
    ],
)
def test_b64url_decode_accepts_with_or_without_padding(text: str, expected: bytes) -> None:
    assert b64url_decode(text) == expected


@pytest.mark.parametrize("bad", ["Zm9v!!", "Zm 9v", "Zm9v+", "Z", "Zg===", "Zm9v/"])
def test_b64url_decode_rejects_invalid_input_instead_of_skipping_it(bad: str) -> None:
    with pytest.raises(ValueError):
        b64url_decode(bad)


def test_kms_signer_uses_credentials_from_the_given_mapping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENTKEYIDSHOULDNOTBEUSED")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient")
    signer = KmsSigner.from_env(
        {
            "KMS_KID": "sp-test",
            "KMS_KEY_ID": "alias/securepitch-seal",
            "AWS_REGION": "af-south-1",
            "AWS_ACCESS_KEY_ID": "EXPLICITKEYIDFROMMAPPING",
            "AWS_SECRET_ACCESS_KEY": "explicit",  # noqa: S106 - fake value
        }
    )
    creds = signer._client._request_signer._credentials
    assert creds.access_key == "EXPLICITKEYIDFROMMAPPING"
    assert signer._client.meta.region_name == "af-south-1"


def test_kms_signer_without_credentials_uses_the_default_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AMBIENTKEYIDFROMENVIRONMENT")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ambient")
    signer = KmsSigner.from_env({"KMS_KID": "sp-test", "KMS_KEY_ID": "alias/securepitch-seal"})
    assert signer._client._request_signer._credentials.access_key == "AMBIENTKEYIDFROMENVIRONMENT"
