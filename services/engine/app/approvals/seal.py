"""Sealing an approved dossier (CRYPTO_SPEC section 5).

sealed payload = approval payload + "kid" + "approvals" (both passkey signatures, with their
public keys) + "sealed_at", signed with the platform key (KMS, or the local key for now).

Before signing, the engine re-verifies both passkey signatures against the challenge rebuilt from
the database, and after signing it verifies its own seal. seal_dossier() then checks the root and
signatures against what the database holds.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, decode_credential_public_key

from app.approvals import passkeys, payload
from app.approvals.passkeys import PasskeyError, RelyingParty
from app.crypto.canonical import b64url
from app.crypto.signer import Signer, payload_digest, verify_digest
from app.ingest.parse import EAT

SIGNING_ROLES = ("manager", "treasurer")


class SealError(ValueError):
    """Why a dossier can't be sealed. The message is safe to show the user."""


@dataclass(frozen=True)
class Sealed:
    payload: dict[str, Any]
    signature: str  # DER, base64url
    merkle_root: str
    kid: str


def public_key_jwk(cose_b64url: str) -> dict[str, str]:
    """A passkey's COSE public key -> JWK, so a sponsor's browser can import it (WebCrypto)."""
    key = decode_credential_public_key(base64url_to_bytes(cose_b64url))
    if hasattr(key, "x") and hasattr(key, "y"):  # EC2, P-256
        return {"kty": "EC", "crv": "P-256", "alg": "ES256", "x": b64url(key.x), "y": b64url(key.y)}
    if hasattr(key, "n") and hasattr(key, "e"):
        return {"kty": "RSA", "alg": "RS256", "n": b64url(key.n), "e": b64url(key.e)}
    raise SealError("A passkey uses an algorithm the verifier can't check")


def _approval_entry(rp: RelyingParty, c: bytes, s: dict[str, Any]) -> dict[str, Any]:
    if s.get("challenge") != c.hex():
        raise SealError(f"The {s['role']}'s signature is over a different version of this dossier")
    if not s.get("public_key"):
        raise SealError(f"The {s['role']}'s passkey is no longer registered")
    credential = {
        "id": s["cred_id"],
        "rawId": s["cred_id"],
        "type": "public-key",
        "response": {
            "authenticatorData": s["authenticator_data"],
            "clientDataJSON": s["client_data_json"],
            "signature": s["signature"],
        },
        "clientExtensionResults": {},
    }
    try:
        # Counter 0: the counter was checked when the signature arrived; here only the
        # signature itself, the challenge, origin, RP ID and user verification are re-checked.
        passkeys.verify_approval(rp, c, credential, s["public_key"], 0)
    except PasskeyError:
        raise SealError(f"The {s['role']}'s passkey signature doesn't verify") from None
    return {
        "role": s["role"],
        "signed_at": datetime.fromisoformat(s["created_at"])
        .astimezone(EAT)
        .isoformat(timespec="seconds"),
        "cred_id": s["cred_id"],
        "pubkey": public_key_jwk(s["public_key"]),
        "authenticatorData": s["authenticator_data"],
        "clientDataJSON": s["client_data_json"],
        "signature": s["signature"],
    }


def seal(
    snapshot: dict[str, Any], rp: RelyingParty, signer: Signer, now: datetime | None = None
) -> Sealed:
    """Build and sign the sealed payload for a seal_snapshot() result."""
    if snapshot["status"] != "approved":
        raise SealError(
            f"Only an approved dossier can be sealed (this one is {snapshot['status']})"
        )
    approval, _ = payload.build(snapshot)
    c = payload.challenge(approval)

    signatures = {s["role"]: s for s in snapshot["signatures"]}
    if sorted(signatures) != sorted(SIGNING_ROLES) or len(snapshot["signatures"]) != len(
        SIGNING_ROLES
    ):
        raise SealError("Both the manager's and the treasurer's passkey signatures are needed")
    approvals = [_approval_entry(rp, c, signatures[role]) for role in SIGNING_ROLES]

    sealed = {
        **approval,
        "kid": signer.kid,
        "approvals": approvals,
        "sealed_at": (now or datetime.now(EAT)).astimezone(EAT).isoformat(timespec="seconds"),
    }
    d = payload_digest(sealed)
    signature = signer.sign_digest(d)
    if not verify_digest(signer.public_key_der(), d, signature):  # never publish a bad seal
        raise SealError("The platform signature didn't verify; nothing was sealed")
    return Sealed(sealed, bytes_to_base64url(signature), approval["merkle_root"], signer.kid)


def approval_payload_of(sealed: dict[str, Any]) -> dict[str, Any]:
    """What the approvers signed: the sealed payload without the three fields sealing adds."""
    return {k: v for k, v in sealed.items() if k not in ("kid", "approvals", "sealed_at")}
