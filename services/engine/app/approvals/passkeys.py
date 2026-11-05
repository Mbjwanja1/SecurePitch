"""WebAuthn (passkeys) for approvals, using py_webauthn. ADR 0003.

The engine verifies every passkey response itself because only it can write approvals. The
relying party ID and allowed origins come from configuration, never from the request.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, generate_challenge
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

# ES256 first; RS256 for older Windows Hello. Both verify with WebCrypto in the sponsor's browser.
ALGORITHMS = [
    COSEAlgorithmIdentifier.ECDSA_SHA_256,
    COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
]
REGISTRATION_TTL_SECONDS = 300


class PasskeyError(ValueError):
    """A passkey response that doesn't verify. The message is safe to show the user."""


@dataclass(frozen=True)
class RelyingParty:
    rp_id: str
    name: str
    origins: tuple[str, ...]


@dataclass(frozen=True)
class NewPasskey:
    cred_id: str  # base64url
    public_key: str  # COSE key, base64url
    sign_count: int
    transports: list[str]


# Registration ---------------------------------------------------------------------------------
#
# The challenge must come back unchanged, but the engine keeps no sessions: it hands the browser
# a state token, HMAC-signed with a key derived from the internal key and bound to the user and
# an expiry, and checks it on the way back.


def _state_key(internal_key: str) -> bytes:
    return hmac.new(
        internal_key.encode(), b"securepitch/passkey-registration/v1", hashlib.sha256
    ).digest()


def _sign_state(internal_key: str, body: bytes) -> str:
    return bytes_to_base64url(hmac.new(_state_key(internal_key), body, hashlib.sha256).digest())


def registration_options(
    rp: RelyingParty, internal_key: str, actor: str, user_name: str, existing: list[str]
) -> tuple[dict[str, Any], str]:
    challenge = generate_challenge()
    options = generate_registration_options(
        rp_id=rp.rp_id,
        rp_name=rp.name,
        user_id=UUID(actor).bytes,
        user_name=user_name,
        user_display_name=user_name,
        challenge=challenge,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.PREFERRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in existing
        ],
        supported_pub_key_algs=ALGORITHMS,
    )
    body = json.dumps(
        {
            "u": actor,
            "c": bytes_to_base64url(challenge),
            "exp": int(time.time()) + REGISTRATION_TTL_SECONDS,
        },
        separators=(",", ":"),
    ).encode()
    state = f"{bytes_to_base64url(body)}.{_sign_state(internal_key, body)}"
    return json.loads(options_to_json(options)), state


def _open_state(internal_key: str, actor: str, state: str) -> bytes:
    try:
        body_b64, mac = state.split(".")
        body = base64url_to_bytes(body_b64)
        data = json.loads(body)
    except (ValueError, TypeError) as exc:
        raise PasskeyError("That passkey request isn't valid. Start again.") from exc
    if not hmac.compare_digest(mac, _sign_state(internal_key, body)) or data.get("u") != actor:
        raise PasskeyError("That passkey request isn't valid. Start again.")
    if data.get("exp", 0) < time.time():
        raise PasskeyError("That passkey request expired. Start again.")
    return base64url_to_bytes(data["c"])


def verify_registration(
    rp: RelyingParty, internal_key: str, actor: str, state: str, credential: dict[str, Any]
) -> NewPasskey:
    challenge = _open_state(internal_key, actor, state)
    try:
        v = verify_registration_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=list(rp.origins),
            require_user_verification=True,
            supported_pub_key_algs=ALGORITHMS,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        raise PasskeyError("The passkey couldn't be verified. Try again.") from exc
    transports = credential.get("response", {}).get("transports") or []
    return NewPasskey(
        cred_id=bytes_to_base64url(v.credential_id),
        public_key=bytes_to_base64url(v.credential_public_key),
        sign_count=v.sign_count,
        transports=[t for t in transports if isinstance(t, str)][:8],
    )


# Approval signatures ----------------------------------------------------------------------------


def approval_options(rp: RelyingParty, challenge: bytes, cred_ids: list[str]) -> dict[str, Any]:
    options = generate_authentication_options(
        rp_id=rp.rp_id,
        challenge=challenge,
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(c)) for c in cred_ids
        ],
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return json.loads(options_to_json(options))


@dataclass(frozen=True)
class Assertion:
    cred_id: str
    authenticator_data: str
    client_data_json: str
    signature: str
    new_sign_count: int


def verify_approval(
    rp: RelyingParty,
    challenge: bytes,
    credential: dict[str, Any],
    public_key: str,
    sign_count: int,
) -> Assertion:
    """Check the assertion signs exactly `challenge`, from an allowed origin, with the user
    verified (fingerprint, face or PIN) by this credential's key."""
    try:
        v = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.rp_id,
            expected_origin=list(rp.origins),
            credential_public_key=base64url_to_bytes(public_key),
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
        response = credential["response"]
        return Assertion(
            cred_id=bytes_to_base64url(v.credential_id),
            authenticator_data=response["authenticatorData"],
            client_data_json=response["clientDataJSON"],
            signature=response["signature"],
            new_sign_count=v.new_sign_count,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        raise PasskeyError(
            "The passkey signature didn't match this dossier. Reload the page and sign again."
        ) from exc
