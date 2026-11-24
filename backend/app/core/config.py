"""Application settings.

Secrets can be provided either directly (``SCHNAEPPLI_FOO``) or as a path to a file
(``SCHNAEPPLI_FOO_FILE``), which is the recommended way with Docker secrets so the
values never appear in ``docker inspect`` or process environments.
"""

from __future__ import annotations

import base64
import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _read_secret(name: str) -> str | None:
    file_path = os.environ.get(f"SCHNAEPPLI_{name}_FILE")
    if file_path:
        return Path(file_path).read_text().strip()
    return os.environ.get(f"SCHNAEPPLI_{name}")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SCHNAEPPLI_", env_file=None, extra="ignore")

    env: str = Field(default="production", description="production | development | test")
    public_url: str = "http://localhost:8080"
    database_url: str = "postgresql+asyncpg://schnaeppli:schnaeppli@db:5432/schnaeppli"
    redis_url: str | None = "redis://redis:6379/0"

    # Comma separated CIDRs that may reach the app. Defence in depth on top of the
    # reverse proxy / VPN. Empty = no in-app restriction.
    allowed_networks: str = ""
    # Reverse proxies whose X-Forwarded-For header is trusted.
    trusted_proxies: str = "127.0.0.1/32"

    session_days: int = 30
    session_idle_days: int = 14
    registration_mode: str = "invite"  # invite | open | closed (first user can always register)

    default_timezone: str = "Europe/Zurich"
    default_currency: str = "CHF"

    # Telegram
    telegram_bot_username: str | None = None

    # eBay Browse API (application credentials, admin configured)
    ebay_marketplace: str = "EBAY_CH"
    ebay_environment: str = "production"

    # Shared AI provider configured by the administrator (optional).
    shared_ai_provider: str | None = None  # anthropic | openai | gemini
    shared_ai_model: str | None = None

    # Claude Code bridge on the administrator's own machine (bridge/claude_code_bridge.py).
    # When set, the admin can connect it with one click in Settings → AI.
    claude_code_bridge_url: str = ""
    log_level: str = "INFO"
    # Added to the User-Agent of outbound fetches (some sites, e.g. Wikimedia,
    # require a contact URL from automated clients). Use your project/repo URL.
    bot_contact_url: str = ""

    @field_validator("env")
    @classmethod
    def _env(cls, v: str) -> str:
        if v not in {"production", "development", "test"}:
            raise ValueError("env must be production, development or test")
        return v

    # ---- secrets (never part of repr) ----
    @property
    def encryption_keys(self) -> dict[str, bytes]:
        """Key id -> 32 byte key. ``SCHNAEPPLI_ENCRYPTION_KEYS`` = "k1:base64,k2:base64".

        The first key is used for new encryptions; older ones remain readable so keys
        can be rotated.
        """
        raw = _read_secret("ENCRYPTION_KEYS")
        if not raw:
            if self.env == "production":
                raise RuntimeError("SCHNAEPPLI_ENCRYPTION_KEYS(_FILE) is required in production")
            return {"dev": b"\x00" * 32}
        keys: dict[str, bytes] = {}
        for part in raw.split(","):
            kid, _, b64 = part.strip().partition(":")
            key = base64.b64decode(b64)
            if len(key) != 32:
                raise RuntimeError(f"encryption key {kid!r} must be 32 bytes")
            keys[kid] = key
        return keys

    @property
    def setup_token(self) -> str | None:
        """If set, creating the very first (admin) account requires it. Protects a
        fresh instance from whoever opens it first."""
        return _read_secret("SETUP_TOKEN") or None

    @property
    def claude_code_bridge_secret(self) -> str | None:
        return _read_secret("CLAUDE_CODE_BRIDGE_SECRET") or None

    @property
    def telegram_bot_token(self) -> str | None:
        return _read_secret("TELEGRAM_BOT_TOKEN")

    @property
    def telegram_webhook_secret(self) -> str | None:
        return _read_secret("TELEGRAM_WEBHOOK_SECRET")

    @property
    def ebay_client_id(self) -> str | None:
        return _read_secret("EBAY_CLIENT_ID")

    @property
    def ebay_client_secret(self) -> str | None:
        return _read_secret("EBAY_CLIENT_SECRET")

    @property
    def shared_ai_api_key(self) -> str | None:
        return _read_secret("SHARED_AI_API_KEY")

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
