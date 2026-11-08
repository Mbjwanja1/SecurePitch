"""Engine settings, read once from the environment (services/engine/.env via docker compose)."""

import json
import os
import re
from dataclasses import dataclass

# Statements are capped at 5 MB (plan section 09). Saving a draft sends the PDF base64-encoded
# inside JSON (+33%), so allow 8 MB.
MAX_STATEMENT_BYTES = 5 * 1024 * 1024
DEFAULT_MAX_BODY_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    env: str
    internal_key: str
    max_body_bytes: int
    supabase_url: str = ""
    supabase_key: str = ""
    roster_pepper: str = ""
    # Passkeys (ADR 0003): the web app's domain and the exact origins pages are served from.
    webauthn_rp_id: str = "localhost"
    webauthn_rp_name: str = "SecurePitch"
    webauthn_origins: tuple[str, ...] = ("http://localhost:3000",)
    # Public keys of platform signing keys no longer in use. They stay published so dossiers
    # sealed with them still verify (CRYPTO_SPEC section 5).
    retired_keys: tuple[dict[str, str], ...] = ()
    # Printed under the QR code of every sealed PDF, permanently: <verify_base>/<dossier id>.
    verify_base: str = "http://localhost:3000/v"

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


_B64URL_32 = re.compile(r"^[A-Za-z0-9_-]{43}$")


def parse_retired_keys(text: str) -> tuple[dict[str, str], ...]:
    """RETIRED_PUBLIC_KEYS: a JSON array of the JWKs /v1/keys published for retired keys.
    Anything malformed stops the engine starting: dropping a key silently would make every
    dossier sealed with it fail verification."""
    if not text.strip():
        return ()
    keys = json.loads(text)
    if not isinstance(keys, list):
        raise ValueError("RETIRED_PUBLIC_KEYS must be a JSON array of JWKs")
    out = []
    for k in keys:
        if not (
            isinstance(k, dict)
            and isinstance(k.get("kid"), str)
            and k["kid"]
            and (k.get("kty"), k.get("crv"), k.get("alg")) == ("EC", "P-256", "ES256")
            and all(isinstance(k.get(c), str) and _B64URL_32.match(k[c]) for c in ("x", "y"))
        ):
            raise ValueError(f"RETIRED_PUBLIC_KEYS: not a P-256 public JWK: {k!r}")
        out.append({f: k[f] for f in ("kid", "kty", "crv", "alg", "x", "y")})
    if len({k["kid"] for k in out}) != len(out):
        raise ValueError("RETIRED_PUBLIC_KEYS: duplicate kid")
    return tuple(out)


def verify_base_from(explicit: str, origins: tuple[str, ...]) -> str:
    """PUBLIC_VERIFY_BASE, or the web app's first passkey origin + /v. The origin has to be right
    already for approvals to work, so the QR code can't quietly point at a different site."""
    base = explicit.strip() or (f"{origins[0]}/v" if origins else "")
    if not re.match(r"^https?://[^/\s]+(/[^\s]*)?$", base):
        raise ValueError(f"PUBLIC_VERIFY_BASE must be an http(s) URL, not {base!r}")
    return base.rstrip("/")


def load_settings() -> Settings:
    origins = tuple(
        o.strip()
        for o in os.environ.get("WEBAUTHN_ORIGINS", "http://localhost:3000").split(",")
        if o.strip()
    )
    return Settings(
        env=os.environ.get("ENGINE_ENV", "prod"),
        internal_key=os.environ.get("ENGINE_INTERNAL_KEY", ""),
        max_body_bytes=int(os.environ.get("ENGINE_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)),
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        roster_pepper=os.environ.get("ROSTER_PEPPER", ""),
        webauthn_rp_id=os.environ.get("WEBAUTHN_RP_ID", "localhost"),
        webauthn_origins=origins,
        retired_keys=parse_retired_keys(os.environ.get("RETIRED_PUBLIC_KEYS", "")),
        verify_base=verify_base_from(os.environ.get("PUBLIC_VERIFY_BASE", ""), origins),
    )
