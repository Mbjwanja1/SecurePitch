# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "boto3>=1.35", "cryptography>=43", "httpx>=0.27", "python-dotenv>=1.0", "psycopg[binary]>=3.2",
# ]
# ///
"""Check that SecurePitch's approved resources are live and configured as the plan expects.

Usage (from the repo root):
    uv run tools/check_infra.py
    uv run tools/check_infra.py --env-file services/engine/.env

With SIGNER=local the AWS checks are skipped and the local signing key is checked instead.
Never prints secrets. Exits non-zero if any check fails.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import re
import subprocess
import sys
from collections.abc import Callable
from urllib.parse import urlsplit

import boto3
import httpx
import psycopg
from botocore.exceptions import BotoCoreError, ClientError
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from dotenv import load_dotenv

# (status, name, detail); status is PASS, FAIL, WARN or SKIP. Only FAIL makes the script fail.
results: list[tuple[str, str, str]] = []


def check(name: str, *, required: bool = True) -> Callable[[Callable[[], str]], Callable[[], str]]:
    """Record a check: the function returns a detail string, or raises to fail.

    A check with required=False reports WARN instead of FAIL: it matters for some tasks
    (like running migrations) but not for the engine itself.
    """

    def wrap(fn: Callable[[], str]) -> Callable[[], str]:
        try:
            results.append(("PASS", name, fn()))
        except Exception as exc:  # noqa: BLE001 - every failure is reported, never raised
            status = "FAIL" if required else "WARN"
            results.append((status, name, f"{type(exc).__name__}: {exc}"))
        return fn

    return wrap


def skip(name: str, reason: str) -> None:
    results.append(("SKIP", name, reason))


def require(*names: str) -> None:
    missing = [n for n in names if not os.environ.get(n)]
    if missing:
        raise RuntimeError(f"missing in .env: {', '.join(missing)}")


def verify_round_trip(sign: Callable[[bytes], bytes], public_der: bytes) -> str:
    """Sign a digest the way the dossier seal will, then verify it with the public key."""
    digest = hashlib.sha256(b"securepitch infra check").digest()
    sig = sign(digest)
    pub = serialization.load_der_public_key(public_der)
    if not isinstance(pub, ec.EllipticCurvePublicKey) or pub.curve.name != "secp256r1":
        raise RuntimeError("public key is not ECDSA P-256")
    pub.verify(sig, digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))
    # DER signatures are ~70-72 bytes; the browser verifier converts them to raw 64-byte r||s.
    return f"valid DER signature, {len(sig)} bytes"


def kms_checks(region: str) -> None:
    @check("AWS credentials valid")
    def _identity() -> str:
        require("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY")
        arn = boto3.client("sts", region_name=region).get_caller_identity()["Arn"]
        if arn.endswith(":root"):
            raise RuntimeError("these are root credentials; use the securepitch-engine IAM user")
        return arn

    kms = boto3.client("kms", region_name=region)
    key_id = os.environ.get("KMS_KEY_ID", "")

    @check("KMS key is ECC_NIST_P256, SIGN_VERIFY, enabled")
    def _key() -> str:
        require("KMS_KEY_ID")
        meta = kms.describe_key(KeyId=key_id)["KeyMetadata"]
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
        def sign(digest: bytes) -> bytes:
            return kms.sign(
                KeyId=key_id,
                Message=digest,
                MessageType="DIGEST",
                SigningAlgorithm="ECDSA_SHA_256",
            )["Signature"]

        return verify_round_trip(sign, kms.get_public_key(KeyId=key_id)["PublicKey"])

    @check("IAM user is sign-only (cannot list keys)")
    def _least_privilege() -> str:
        try:
            kms.list_keys(Limit=1)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "AccessDeniedException":
                return "kms:ListKeys denied, as intended"
            raise
        raise RuntimeError(
            "kms:ListKeys was allowed; the IAM policy is broader than "
            "infra/aws/engine-kms-policy.json"
        )


def local_signer_checks() -> None:
    for name in (
        "AWS credentials valid",
        "KMS key is ECC_NIST_P256, SIGN_VERIFY, enabled",
        "IAM user is sign-only (cannot list keys)",
    ):
        skip(name, "SIGNER=local; switch to SIGNER=kms once AWS is ready")

    @check("Local signing key sign -> verify round trip")
    def _local() -> str:
        require("LOCAL_SIGNING_KEY")
        raw = os.environ["LOCAL_SIGNING_KEY"]
        der = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
        key = serialization.load_der_private_key(der, password=None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise RuntimeError("LOCAL_SIGNING_KEY is not an EC private key")

        def sign(digest: bytes) -> bytes:
            return key.sign(digest, ec.ECDSA(utils.Prehashed(hashes.SHA256())))

        public_der = key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        return verify_round_trip(sign, public_der)


# How to turn the Docker VM's swap off on each host OS (docs/INFRA_SETUP.md step 7).
SWAP_FIX = {
    "win32": "add swap=0 under [wsl2] in %UserProfile%\\.wslconfig, run `wsl --shutdown`, "
    "restart Docker Desktop",
    "darwin": "set Docker Desktop > Settings > Resources > Swap to 0, then Apply & restart",
    "linux": "Docker Desktop: set Settings > Resources > Swap to 0; Docker Engine: run "
    "`sudo swapoff -a` and remove the swap entries from /etc/fstab",
}


def run_checks() -> None:
    @check("Docker engine running")
    def _docker() -> str:
        out = subprocess.run(  # noqa: S603 - fixed argument list, no user input
            ["docker", "info", "--format", "{{.ServerVersion}}"],  # noqa: S607 - docker from PATH
            capture_output=True,
            text=True,
            timeout=20,
            check=True,
        )
        return f"server {out.stdout.strip()}"

    # With swap on, the Linux VM can page the engine's in-memory statement data (RAM-backed
    # /tmp, process memory) out to a swap file on disk. docs/INFRA_SETUP.md step 7.
    @check("Docker VM has no swap")
    def _swap() -> str:
        out = subprocess.run(  # noqa: S603 - fixed argument list, no user input
            ["docker", "run", "--rm", "alpine:3.20", "cat", "/proc/meminfo"],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        lines = out.stdout.splitlines()
        swap_kb = next(
            (int(line.split()[1]) for line in lines if line.startswith("SwapTotal:")), None
        )
        if swap_kb is None:  # not 0: an unreadable answer mustn't pass as "swap is off"
            raise RuntimeError("couldn't read SwapTotal from the Docker VM's /proc/meminfo")
        if swap_kb:
            fix = SWAP_FIX.get(sys.platform, SWAP_FIX["linux"])
            raise RuntimeError(f"{swap_kb // 1024} MB of swap: {fix}")
        return "swap is off"

    signer = os.environ.get("SIGNER", "kms").strip().lower()
    if signer == "local":
        local_signer_checks()
    else:
        kms_checks(os.environ.get("AWS_REGION", "af-south-1"))

    @check("Supabase service key has admin rights")
    def _supabase() -> str:
        require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        url = os.environ["SUPABASE_URL"].rstrip("/")
        if not re.fullmatch(r"https://[a-z0-9]+\.supabase\.co", url):
            raise RuntimeError(
                "SUPABASE_URL must be the bare project URL, https://<ref>.supabase.co "
                "(no /rest/v1 or other path)"
            )
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        headers = {"apikey": key}
        if key.startswith("eyJ"):  # legacy service_role JWT also needs the Authorization header
            headers["Authorization"] = f"Bearer {key}"
        # /auth/v1/health accepts any valid key, including the public publishable key, so it
        # can't tell the keys apart. The Auth admin API only answers to a secret/service key.
        r = httpx.get(
            f"{url}/auth/v1/admin/users",
            params={"page": 1, "per_page": 1},
            headers=headers,
            timeout=15,
        )
        if r.status_code in (401, 403):
            raise RuntimeError(
                f"HTTP {r.status_code}: SUPABASE_SERVICE_ROLE_KEY isn't a secret key "
                "(sb_secret_... or legacy service_role); the publishable/anon key won't work here"
            )
        r.raise_for_status()
        return f"{url} admin API accepted the key"

    # Accounts are created by admins (tools/onboard_member.py). With public sign-ups on, anyone
    # holding the publishable key (which ships in the web app) could call /auth/v1/signup.
    @check("Public sign-ups are disabled")
    def _signups() -> str:
        require("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY")
        url = os.environ["SUPABASE_URL"].rstrip("/")
        r = httpx.get(
            f"{url}/auth/v1/settings",
            headers={"apikey": os.environ["SUPABASE_SERVICE_ROLE_KEY"]},
            timeout=15,
        )
        r.raise_for_status()
        if not r.json().get("disable_signup"):
            raise RuntimeError(
                "public sign-ups are ON: Supabase dashboard -> Authentication -> Sign In / "
                "Providers -> turn off 'Allow new users to sign up'"
            )
        return "only admins can create accounts"

    # Only migrations connect to Postgres directly; the engine uses HTTPS (ADR 0002). So a
    # blocked database port is a warning, not a failure.
    @check("Database login (for migrations only)", required=False)
    def _database() -> str:
        require("DATABASE_URL")
        dsn = os.environ["DATABASE_URL"]
        parts = urlsplit(dsn)
        # An unencoded "#", "?" or "/" in the password cuts the URL short: the "host" becomes
        # part of the username and reading the port raises. Catch that before connecting.
        try:
            port = parts.port or 5432
        except ValueError:
            port = None
        if port is None or not parts.hostname or "." not in parts.hostname:
            raise RuntimeError(
                "DATABASE_URL couldn't be parsed. If the password contains special characters "
                "(# ? / : @), URL-encode them (for example # -> %23, ? -> %3F) or reset the "
                "database password to letters and digits"
            )
        where = f"{parts.hostname}:{port}"
        try:
            with psycopg.connect(dsn, connect_timeout=10) as conn:
                version = conn.execute("show server_version").fetchone()[0]
        except psycopg.Error as exc:
            message = str(exc).strip().splitlines()[0]
            if parts.password:
                message = message.replace(parts.password, "***")
            hint = ""
            if parts.hostname and parts.hostname.startswith("db."):
                hint = " (direct connections are IPv6-only; use the Session pooler URL)"
            elif "timeout" in message.lower():
                hint = (
                    " (this network blocks outbound database ports. The engine is unaffected;"
                    " to run migrations, use a phone hotspot or the Supabase SQL editor)"
                )
            raise RuntimeError(f"{where}: {message}{hint}") from None
        if parts.port == 6543:
            raise RuntimeError(
                f"{where}: connected, but 6543 is the transaction pooler; migrations need "
                "the Session pooler (port 5432)"
            )
        return f"{where}, Postgres {version}"

    @check("Engine secrets valid")
    def _secrets() -> str:
        require("ENGINE_INTERNAL_KEY", "ROSTER_PEPPER")
        if len(os.environ["ENGINE_INTERNAL_KEY"]) < 32:
            raise RuntimeError("ENGINE_INTERNAL_KEY is shorter than 32 characters")
        try:
            pepper = base64.b64decode(os.environ["ROSTER_PEPPER"], validate=True)
        except ValueError:
            raise RuntimeError("ROSTER_PEPPER is not valid base64") from None
        if len(pepper) != 32:
            raise RuntimeError(f"ROSTER_PEPPER decodes to {len(pepper)} bytes; it must be 32")
        return "internal key length ok; roster pepper is 32 bytes"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--env-file", default="services/engine/.env")
    args = parser.parse_args()
    if not load_dotenv(args.env_file):
        print(f"note: {args.env_file} not found; using the current environment only\n")

    try:
        run_checks()
    except (BotoCoreError, ClientError) as exc:  # e.g. no region or credentials at all
        results.append(("FAIL", "AWS client setup", str(exc)))

    width = max((len(name) for _, name, _ in results), default=20)
    for status, name, detail in results:
        print(f"{status}  {name.ljust(width)}  {detail}")
    counts = {s: sum(status == s for status, _, _ in results) for s in ("FAIL", "WARN", "SKIP")}
    ran = len(results) - counts["SKIP"]
    passed = ran - counts["FAIL"] - counts["WARN"]
    print(f"\n{passed}/{ran} checks passed, {counts['WARN']} warning(s), {counts['SKIP']} skipped")
    return 1 if counts["FAIL"] else 0


if __name__ == "__main__":
    sys.exit(main())
