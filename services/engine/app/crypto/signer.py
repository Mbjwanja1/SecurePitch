"""Dossier signing (docs/CRYPTO_SPEC.md section 5).

The seal pipeline only ever sees the Signer interface, so switching from the local
development key to AWS KMS is a configuration change (SIGNER=kms), not a code change.
"""

from __future__ import annotations

import argparse
import json
import os
from collections.abc import Mapping
from typing import Any, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils

from app.crypto.canonical import b64url, b64url_decode, canonicalize, sha256

_PREHASHED = ec.ECDSA(utils.Prehashed(hashes.SHA256()))


class Signer(Protocol):
    kid: str

    def sign_digest(self, digest: bytes) -> bytes:
        """Return a DER-encoded ECDSA P-256 signature over a 32-byte SHA-256 digest."""
        ...

    def public_key_der(self) -> bytes:
        """Return the public key as DER SubjectPublicKeyInfo."""
        ...


class LocalSigner:
    """Signs with a P-256 key held in memory. Development, tests and the pre-AWS fallback."""

    def __init__(self, kid: str, private_key: ec.EllipticCurvePrivateKey) -> None:
        if not isinstance(private_key.curve, ec.SECP256R1):
            raise ValueError("local signing key must be P-256")
        self.kid = kid
        self._key = private_key

    @classmethod
    def generate(cls, kid: str = "local-dev") -> LocalSigner:
        return cls(kid, ec.generate_private_key(ec.SECP256R1()))

    @classmethod
    def from_b64(cls, kid: str, pkcs8_b64url: str) -> LocalSigner:
        key = serialization.load_der_private_key(b64url_decode(pkcs8_b64url), password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("LOCAL_SIGNING_KEY is not an EC private key")
        return cls(kid, key)

    def private_key_b64(self) -> str:
        return b64url(
            self._key.private_bytes(
                serialization.Encoding.DER,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            )
        )

    def sign_digest(self, digest: bytes, *, deterministic: bool = False) -> bytes:
        _check_digest(digest)
        algorithm = (
            ec.ECDSA(utils.Prehashed(hashes.SHA256()), deterministic_signing=True)
            if deterministic
            else _PREHASHED
        )
        return self._key.sign(digest, algorithm)

    def public_key_der(self) -> bytes:
        return self._key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )


class KmsSigner:
    """Signs with an AWS KMS ECC_NIST_P256 key. The private key never leaves KMS."""

    def __init__(self, kid: str, key_id: str, client: Any) -> None:
        self.kid = kid
        self._key_id = key_id
        self._client = client
        self._public_der: bytes | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> KmsSigner:
        import boto3  # imported lazily so local development never needs AWS libraries loaded

        # Use credentials from the mapping we were given, so an explicit config (tests,
        # staging) is honoured. If it has none, boto3 falls back to its usual chain
        # (environment variables, ~/.aws, an IAM role).
        credentials = {
            "aws_access_key_id": env.get("AWS_ACCESS_KEY_ID"),
            "aws_secret_access_key": env.get("AWS_SECRET_ACCESS_KEY"),
            "aws_session_token": env.get("AWS_SESSION_TOKEN"),
        }
        client = boto3.client(
            "kms",
            region_name=env.get("AWS_REGION", "af-south-1"),
            **{k: v for k, v in credentials.items() if v},
        )
        return cls(env["KMS_KID"], env["KMS_KEY_ID"], client)

    def sign_digest(self, digest: bytes) -> bytes:
        _check_digest(digest)
        response = self._client.sign(
            KeyId=self._key_id,
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )
        return response["Signature"]

    def public_key_der(self) -> bytes:
        if self._public_der is None:
            self._public_der = self._client.get_public_key(KeyId=self._key_id)["PublicKey"]
        return self._public_der


def signer_from_env(env: Mapping[str, str] | None = None) -> Signer:
    env = os.environ if env is None else env
    mode = env.get("SIGNER", "kms").strip().lower()
    if mode == "local":
        return LocalSigner.from_b64(env.get("LOCAL_KID", "local-dev"), env["LOCAL_SIGNING_KEY"])
    if mode == "kms":
        return KmsSigner.from_env(env)
    raise ValueError(f"SIGNER must be 'kms' or 'local', not {mode!r}")


def _check_digest(digest: bytes) -> None:
    if len(digest) != 32:
        raise ValueError("expected a 32-byte SHA-256 digest")


def payload_digest(payload: Any) -> bytes:
    """d = SHA-256(canonical(payload)): the value every signer signs."""
    return sha256(canonicalize(payload))


def verify_digest(public_der: bytes, digest: bytes, signature_der: bytes) -> bool:
    key = serialization.load_der_public_key(public_der)
    if not isinstance(key, ec.EllipticCurvePublicKey):
        return False
    try:
        key.verify(signature_der, digest, _PREHASHED)
    except InvalidSignature:
        return False
    return True


def der_to_raw(signature_der: bytes) -> bytes:
    """DER ECDSA signature -> 64-byte r||s, the form WebCrypto's verify() expects."""
    r, s = utils.decode_dss_signature(signature_der)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def public_jwk(kid: str, public_der: bytes) -> dict[str, str]:
    key = serialization.load_der_public_key(public_der)
    if not isinstance(key, ec.EllipticCurvePublicKey):
        raise ValueError("not an EC public key")
    numbers = key.public_numbers()
    return {
        "kid": kid,
        "kty": "EC",
        "crv": "P-256",
        "alg": "ES256",
        "x": b64url(numbers.x.to_bytes(32, "big")),
        "y": b64url(numbers.y.to_bytes(32, "big")),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SecurePitch signing utilities")
    parser.add_argument(
        "--generate", action="store_true", help="print a new LOCAL_SIGNING_KEY value"
    )
    parser.add_argument(
        "--public-jwk",
        action="store_true",
        help="print the configured signer's public JWK, for RETIRED_PUBLIC_KEYS when rotating",
    )
    args = parser.parse_args()
    if args.generate:
        print(LocalSigner.generate().private_key_b64())
    if args.public_jwk:
        s = signer_from_env()
        print(json.dumps(public_jwk(s.kid, s.public_key_der())))
