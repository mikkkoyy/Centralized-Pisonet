"""Typed application configuration loaded from environment variables.

All settings are explicit: there are no default passwords and no
default secrets. The application refuses to start when required
secrets are missing or malformed, except for ``ENROLLMENT_SECRET``
which is auto-generated once on first boot and surfaced to the
operator (never logged).
"""

from __future__ import annotations

import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Server configuration. Mirrors ``.env.example``."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_DIR / ".env"),
        env_file_encoding="utf-8",
        env_prefix="",
        extra="ignore",
    )

    # --- Server ---
    environment: str = "development"
    server_host: str = "127.0.0.1"
    server_port: int = 8000

    # --- Secrets ---
    secret_key: str = ""
    enrollment_secret: str = ""

    # --- Station policy ---
    station_heartbeat_timeout: int = 30

    # --- Database ---
    database_url: str = "sqlite:///./pisonet.db"

    @field_validator("environment")
    @classmethod
    def _check_environment(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in ("development", "production"):
            raise ValueError("environment must be 'development' or 'production'")
        return value

    @field_validator("server_port", "station_heartbeat_timeout")
    @classmethod
    def _check_positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("value must be a positive integer")
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    def validate_or_generate_secrets(self) -> list[str]:
        """Validate configured secrets, generating the enrollment secret
        on first boot when unset. Returns operator-facing notices."""
        notices: list[str] = []
        if not self.secret_key:
            raise ValueError(
                "SECRET_KEY is not set. Generate one with: "
                "python -c \"import secrets; print(secrets.token_hex(32))\" "
                "and set it in the environment or .env file."
            )
        if len(self.secret_key) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters.")
        if not self.enrollment_secret:
            self.enrollment_secret = secrets.token_hex(32)
            notices.append(
                "ENROLLMENT_SECRET was not set; a random enrollment secret "
                "was generated for this server. Stations cannot register "
                "until the operator retrieves it."
            )
        return notices


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached settings. Cache is cleared in tests via
    ``get_settings.cache_clear()``."""
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
