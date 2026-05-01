"""V7.1 Web Backend settings (pydantic-settings).

Settings are loaded from environment variables with the ``V71_WEB_``
prefix, falling back to ``.env`` when running locally. Production
deployment passes the secrets through ``shared/.env`` via systemd
``EnvironmentFile`` (see CLAUDE.md §5.1 -- *.env inline comments are
forbidden*).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WebSettings(BaseSettings):
    """Runtime configuration for the V7.1 backend."""

    model_config = SettingsConfigDict(
        env_prefix="V71_WEB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Server -------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8000
    workers: int = 1
    debug: bool = False
    environment: Literal["dev", "staging", "prod"] = "dev"

    # --- CORS ---------------------------------------------------------
    cors_origins: list[str] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"],
    )

    # --- Database -----------------------------------------------------
    # Async DSN. e.g. postgresql+asyncpg://user:pw@host:5432/v71
    # Tests can override with sqlite+aiosqlite:///:memory:.
    database_url: str = "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/v71"
    database_echo: bool = False
    database_pool_size: int = 10
    database_max_overflow: int = 20
    database_pool_timeout_seconds: int = 30

    # --- Auth (JWT) ---------------------------------------------------
    # Override via env in prod -- never commit production secrets.
    jwt_secret: str = "dev-only-do-not-use-in-prod-________________"
    jwt_algorithm: str = "HS256"
    # PRD 12_SECURITY §3.5: 30분 access + sliding refresh.
    # access_token_minutes is also the "session expiry" the user sees in
    # the header SessionExtendButton countdown. Lowering it tightens the
    # window an attacker has if they capture an access token.
    access_token_minutes: int = 30
    # Refresh stays at 24h so an active user can sit idle overnight and
    # still come back without re-entering credentials. Each /auth/refresh
    # call rotates the refresh token (PRD §3.5 sliding) so a leaked
    # refresh is single-use only.
    refresh_token_hours: int = 24
    totp_session_minutes: int = 15  # interim session id between login & totp

    # --- TOTP / Security ---------------------------------------------
    totp_issuer: str = "K-Stock Trading"
    bcrypt_rounds: int = 12

    # --- Rate limit ---------------------------------------------------
    login_rate_limit_per_minute: int = 5
    api_rate_limit_per_minute: int = 120

    # --- Misc ---------------------------------------------------------
    request_id_header: str = "X-Request-ID"

    @property
    def is_prod(self) -> bool:
        return self.environment == "prod"


@lru_cache(maxsize=1)
def get_settings() -> WebSettings:
    """Cached settings accessor (FastAPI dependency-friendly)."""
    return WebSettings()
