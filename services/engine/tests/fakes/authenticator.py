"""A software passkey for tests: produces the same JSON a browser's navigator.credentials does.

Real P-256 keys and real signatures, so py_webauthn verifies them exactly as it would a phone's.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, encode_cbor

UP, UV, AT = 0x01, 0x04, 0x40


@dataclass
class SoftPasskey:
    rp_id: str = "localhost"
    origin: str = "http://localhost:3000"
    cred_id: bytes = field(default_factory=lambda: os.urandom(16))
    key: ec.EllipticCurvePrivateKey = field(
        default_factory=lambda: ec.generate_private_key(ec.SECP256R1())
    )
    counter: int = 0

    @property
    def id(self) -> str:
        return bytes_to_base64url(self.cred_id)

    def _cose(self) -> bytes:
        n = self.key.public_key().public_numbers()
        return encode_cbor(
            {1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")}
        )

    def _client_data(self, kind: str, challenge_b64: str, origin: str | None) -> bytes:
        return json.dumps(
            {
                "type": kind,
                "challenge": challenge_b64,
                "origin": origin or self.origin,
                "crossOrigin": False,
            }
        ).encode()

    def register(
        self, options: dict, *, origin: str | None = None, flags: int = UP | UV | AT
    ) -> dict:
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + self.counter.to_bytes(4, "big")
            + bytes(16)  # AAGUID
            + len(self.cred_id).to_bytes(2, "big")
            + self.cred_id
            + self._cose()
        )
        attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def sign(
        self,
        options: dict,
        *,
        challenge: bytes | None = None,
        origin: str | None = None,
        flags: int = UP | UV,
        counter_step: int = 1,
    ) -> dict:
        """Sign options["challenge"] (or another challenge, to simulate tampering)."""
        self.counter += counter_step
        c = bytes_to_base64url(challenge) if challenge is not None else options["challenge"]
        client_data = self._client_data("webauthn.get", c, origin)
        auth_data = (
            hashlib.sha256(self.rp_id.encode()).digest()
            + bytes([flags])
            + self.counter.to_bytes(4, "big")
        )
        signature = self.key.sign(
            auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256())
        )
        return {
            "id": self.id,
            "rawId": self.id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": None,
            },
            "clientExtensionResults": {},
        }


def challenge_of(options: dict) -> bytes:
    return base64url_to_bytes(options["challenge"])
