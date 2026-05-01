"""V7.1 외부 통신 + 로깅 설정.

V7.0 (Purple-ReAbs) 시절 ``RiskSettings`` / ``StrategySettings`` /
``KiwoomSettings`` / ``AppConfig`` 등 거래 룰 + 키움 분기 로직이 함께
있었으나, V7.0 폐기 (commit 33ee3ee, 2026-04-28) + V7.1 단독 운영 land
(2026-05-01)와 함께 모두 제거됨.

V7.1은
* 거래 룰 → ``src/core/v71/skills/*`` (per PRD §7)
* 키움 REST/WebSocket → ``src/core/v71/exchange/`` (P5-Kiwoom-1..6)
* 웹/auth 설정 → ``src/web/v71/config.py``

에서 직접 관리하므로 이 모듈은 V7.1 공통 인프라 설정만 보존:

* :class:`DatabaseSettings` / :func:`get_database_settings` — DB 풀
  (V7.1 backend + V7.0 호환 SQLAlchemy ``Base``)
* :class:`TelegramSettings` / :func:`get_telegram_settings` — V7.1
  P-Wire-3 fail-secure send callable
* :class:`Settings` / :func:`get_settings` — 로거가 environment 메타 +
  log 레벨/포맷 읽는 용도

Pydantic Settings 기반 — 타입 안전 + ``.env`` 자동 로드 + 환경변수 override.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TelegramSettings(BaseSettings):
    """텔레그램 봇 설정 (V7.1 P-Wire-3 fail-secure send)."""

    bot_token: str = Field(..., alias="TELEGRAM_BOT_TOKEN")
    chat_id: str = Field(..., alias="TELEGRAM_CHAT_ID")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


class DatabaseSettings(BaseSettings):
    """데이터베이스 설정 (PostgreSQL/Supabase + SQLite 폴백).

    V7.1 backend는 ``DATABASE_URL`` (Supabase Pooler) → SQLite 순서로
    fallback. 개별 ``POSTGRES_*`` 필드는 ``DATABASE_URL`` 미설정 시 사용.
    """

    # DATABASE_URL (Supabase Pooler, 기타 PostgreSQL 호환)
    # 예: postgresql://postgres.<ref>:<pwd>@aws-N-<region>.pooler.supabase.com:6543/postgres?sslmode=require
    database_url: str | None = Field(default=None, alias="DATABASE_URL")

    # PostgreSQL 개별 필드 (DATABASE_URL 미설정 시 사용)
    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT")
    postgres_db: str = Field(default="k_stock_trading", alias="POSTGRES_DB")
    postgres_user: str | None = Field(default=None, alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, alias="POSTGRES_PASSWORD")

    # SQLite 폴백 경로
    sqlite_path_str: str = Field(
        default="data/k_stock_trading.db",
        alias="SQLITE_PATH"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def sqlite_path(self):
        from pathlib import Path
        return Path(self.sqlite_path_str)

    @property
    def postgres_url(self) -> str | None:
        """PostgreSQL 연결 URL (동기)."""
        if self.database_url:
            return self.database_url
        if not self.postgres_host or not self.postgres_user:
            return None
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def postgres_async_url(self) -> str | None:
        """PostgreSQL 연결 URL (비동기, psycopg3 드라이버)."""
        if self.database_url:
            url = self.database_url
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+psycopg://", 1)
            elif url.startswith("postgres://"):
                return url.replace("postgres://", "postgresql+psycopg://", 1)
            return url
        if not self.postgres_host or not self.postgres_user:
            return None
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class Settings(BaseSettings):
    """V7.1 로거 + 환경 메타 설정.

    ``src/utils/logger.py`` 가 environment / is_paper_trading / log_level /
    log_format 4개 attr을 읽는다. V7.1 web/api/exchange 모두 자체 설정
    모듈을 사용하므로 이 클래스에 다른 영역을 추가하지 말 것.
    """

    environment: str = Field(default="development", alias="ENVIRONMENT")
    is_paper_trading: bool = Field(default=False, alias="IS_PAPER_TRADING")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: str = Field(default="json", alias="LOG_FORMAT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@lru_cache(maxsize=1)
def get_telegram_settings() -> TelegramSettings:
    return TelegramSettings()


@lru_cache(maxsize=1)
def get_database_settings() -> DatabaseSettings:
    return DatabaseSettings()
