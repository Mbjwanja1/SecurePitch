"""Engine settings, read once from the environment (services/engine/.env via docker compose)."""

import os
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

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


def load_settings() -> Settings:
    return Settings(
        env=os.environ.get("ENGINE_ENV", "prod"),
        internal_key=os.environ.get("ENGINE_INTERNAL_KEY", ""),
        max_body_bytes=int(os.environ.get("ENGINE_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)),
        supabase_url=os.environ.get("SUPABASE_URL", ""),
        supabase_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY", ""),
        roster_pepper=os.environ.get("ROSTER_PEPPER", ""),
    )
