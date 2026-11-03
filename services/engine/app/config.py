"""Engine settings, read once from the environment (services/engine/.env via docker compose)."""

import os
from dataclasses import dataclass

# Statements are capped at 5 MB (plan section 09); allow 1 MB for multipart overhead.
DEFAULT_MAX_BODY_BYTES = 6 * 1024 * 1024


@dataclass(frozen=True)
class Settings:
    env: str
    internal_key: str
    max_body_bytes: int

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


def load_settings() -> Settings:
    return Settings(
        env=os.environ.get("ENGINE_ENV", "prod"),
        internal_key=os.environ.get("ENGINE_INTERNAL_KEY", ""),
        max_body_bytes=int(os.environ.get("ENGINE_MAX_BODY_BYTES", DEFAULT_MAX_BODY_BYTES)),
    )
