# /// script
# requires-python = ">=3.12"
# dependencies = ["boto3>=1.35", "cryptography>=43", "httpx>=0.27", "python-dotenv>=1.0"]
# ///
"""Check that SecurePitch's approved resources are live and configured as the plan expects.

Usage (from the repo root):
    uv run tools/check_infra.py
    uv run tools/check_infra.py --env-file services/engine/.env

Never prints secrets. Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from collections.abc import Callable

import boto3
import httpx
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from dotenv import load_dotenv

results: list[tuple[str, bool, str]] = []


def check(name: str) -> Callable[[Callable[[], str]], Callable[[], str]]:
    """Record a check: the function returns a detail string, or raises to fail."""

    def wrap(fn: Callable[[], str]) -> Callable[[], str]:
        try:
            results.append((name, True, fn()))
        except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        return fn

    return wrap


def require(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(f"missing in .env: {', '.join(missing)}")


def run_checks() -> None:
    region = os.environ.get("AWS_REGION", "af-south-1")

    @check("Docker engine running")
    def _docker() -> str:
        out = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return f"server {out.stdout.strip()}"

    @check("AWS credentials valid")
    def _identity() -> str:
        require("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        arn = boto3.client("sts", region_name=region).get_caller_identity()["Arn"]
        if arn.endswith(":root"):
            raise RuntimeError(
                "these are root credentials; use the securepitch-engine IAM user"
            )
        return arn

    kms = boto3.client("kms", region_name=region)

    @check("KMS key is ECC_NIST_P256, SIGN_VERIFY, enabled")
    def _key() -> str:
        require("KMS_KEY_ID")
        meta = kms.describe_key(KeyId=os.environ["KMS_KEY_ID"])["KeyMetadata"]
        problems = []
        if meta["KeySpec"] != "ECC_NIST_P256":
            problems.append(f"KeySpec is {meta['KeySpec']}")
        if meta["KeyUsage"] != "SIGN_VERIFY":
            problems.append(f"KeyUsage is {meta['KeyUsage']}")
        if meta["KeyState"] != "Enabled":
            problems.append(f"KeyState is {meta['KeyState']}")
        if problems:
            raise RuntimeError("; ".join(problems))
        return f"{meta['KeyId']} in {region}"

    @check("KMS sign -> local verify round trip")
    def _sign() -> str:
        # Same path the dossier seal will use: hash locally, KMS signs the digest (MessageType=DIGEST).
        digest = hashlib.sha256(b"securepitch infra check").digest()
        sig = kms.sign(
            KeyId=os.environ["KMS_KEY_ID"],
            Message=digest,
            MessageType="DIGEST",
            SigningAlgorithm="ECDSA_SHA_256",
        )["Signature"]
        der_pub = kms.get_public_key(KeyId=os.environ["KMS_KEY_ID"])["PublicKey"]
        pub = serialization.load_der_public_key(der_pub)
        assert isinstance(pub, ec.EllipticCurvePublicKey)
        pub.verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
        # KMS returns DER (~70-72 bytes); the browser verifier must convert to raw 64-byte r||s.
        return f"valid DER signature, {len(sig)} bytes"

    @check("IAM user is sign-only (cannot list keys)")
    def _least_privilege() -> str:
        try:
            kms.list_keys(Limit=1)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "AccessDeniedException":
                return "kms:ListKeys denied, as intended"
            raise
        raise RuntimeError(
            "kms:ListKeys was allowed; the IAM policy is broader than infra/aws/engine-kms-policy.json"
        )

    @check("Supabase API reachable with service key")
    def _supabase() -> str:
        require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        url = os.environ["SUPABASE_URL"].rstrip("/")
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        r = httpx.get(f"{url}/auth/v1/health", headers={"apikey": key}, timeout=15)
        r.raise_for_status()
        return f"{url} auth healthy"

    @check("Engine secrets generated")
    def _secrets() -> str:
        require("ENGINE_INTERNAL_KEY", "ROSTER_PEPPER")
        if len(os.environ["ENGINE_INTERNAL_KEY"]) < 32:
            raise RuntimeError("ENGINE_INTERNAL_KEY is shorter than 32 characters")
        return "present"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default="services/engine/.env")
    args = parser.parse_args()
    if not load_dotenv(args.env_file):
        print(f"note: {args.env_file} not found; using the current environment only\n")

    try:
        run_checks()
    except (BotoCoreError, ClientError) as exc:  # e.g. no region or credentials at all
        results.append(("AWS client setup", False, str(exc)))

    width = max(len(name) for name, _, _ in results)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name.ljust(width)}  {detail}")
    failed = sum(not ok for _, ok, _ in results)
    print(f"\n{len(results) - failed}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
