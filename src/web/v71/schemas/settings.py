"""Settings schemas (09_API_SPEC §10)."""

from __future__ import annotations

from datetime import datetime, time
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class UserSettingsOut(BaseModel):
    """09_API_SPEC §10.1."""

    model_config = ConfigDict(from_attributes=True)

    total_capital: Decimal | None
    notify_critical: bool
    notify_high: bool
    notify_medium: bool
    notify_low: bool
    quiet_hours_enabled: bool
    quiet_hours_start: time | None
    quiet_hours_end: time | None
    theme: str
    language: str
    preferences: dict[str, Any] | None
    telegram_chat_id: str | None = None
    totp_enabled: bool = False
    updated_at: datetime


class UserSettingsPatch(BaseModel):
    """09_API_SPEC §10.2 -- notify_critical=False is rejected (CRITICAL_NOTIFICATION_REQUIRED)."""

    total_capital: Decimal | None = Field(default=None, gt=0)
    notify_critical: bool | None = None
    notify_high: bool | None = None
    notify_medium: bool | None = None
    notify_low: bool | None = None
    quiet_hours_enabled: bool | None = None
    quiet_hours_start: time | None = None
    quiet_hours_end: time | None = None
    theme: str | None = Field(default=None, max_length=20)
    language: str | None = Field(default=None, max_length=5)
    preferences: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _critical_required(self) -> "UserSettingsPatch":
        if self.notify_critical is False:
            from ..exceptions import BusinessRuleError

            raise BusinessRuleError(
                "CRITICAL 알림은 비활성화할 수 없습니다",
                error_code="CRITICAL_NOTIFICATION_REQUIRED",
            )
        return self


class FeatureFlagsOut(BaseModel):
    v71: dict[str, bool]


class FeatureFlagsPatch(BaseModel):
    """09_API_SPEC §10.4 -- runtime feature flag toggles."""

    flags: dict[str, bool] = Field(default_factory=dict)


# ---------------------------------------------------------------------
# ★ PRD Patch #5 (V7.1.0d, 2026-04-27)
#
# Read-only broker / trading settings. PATCH endpoints intentionally absent:
# all values are managed by the .env file and 02_TRADING_RULES.md constants.
# See 09_API_SPEC.md §10.5, §10.6 + 13_APPENDIX.md §6.2.Z.
# ---------------------------------------------------------------------


class BrokerSettingsOut(BaseModel):
    """09_API_SPEC §10.5 GET /api/v71/settings/broker (read-only)."""

    kiwoom_account_no_masked: str | None = None      # 예: "1234-56**-**"
    kiwoom_account_type: str | None = None           # REAL | MOCK
    app_key_configured: bool = False
    app_secret_configured: bool = False
    token_expires_at: datetime | None = None
    managed_by: str = ".env file"


class TradingSettingsOut(BaseModel):
    """09_API_SPEC §10.6 GET /api/v71/settings/trading (read-only)."""

    auto_trading_enabled: bool = False
    safe_mode: bool = False
    is_paper_trading: bool = False

    # 거래 룰 상수 (02_TRADING_RULES.md, V71Constants 잠금)
    max_position_pct_per_stock: int = 30
    profit_5_take_pct: int = 30
    profit_10_take_pct: int = 30
    stop_loss_default_pct: int = -5

    managed_by: str = ".env file + 02_TRADING_RULES.md constants"
