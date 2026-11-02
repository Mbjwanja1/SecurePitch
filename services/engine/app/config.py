"""Engine settings, read once from the environment (services/engine/.env via docker compose)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    env: str
    internal_key: str

    @property
    def is_dev(self) -> bool:
        return self.env == "dev"


def load_settings() -> Settings:
    return Settings(
        env=os.environ.get("ENGINE_ENV", "prod"),
        internal_key=os.environ.get("ENGINE_INTERNAL_KEY", ""),
    )
