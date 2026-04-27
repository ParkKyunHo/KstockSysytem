"""Settings REST endpoints (09_API_SPEC §10)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import select

from ...audit import record_audit
from ...auth.dependencies import CurrentUserDep
from ...db_models import AuditAction, UserSettings
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import BusinessRuleError
from ...schemas.common import build_meta
from ...schemas.settings import (
    BrokerSettingsOut,
    FeatureFlagsOut,
    FeatureFlagsPatch,
    TradingSettingsOut,
    UserSettingsOut,
    UserSettingsPatch,
)
from ..system.state import feature_flags

router = APIRouter(prefix="/settings", tags=["settings"])


async def _ensure_settings(session, user_id) -> UserSettings:
    """Lazily create a default user_settings row when missing."""
    settings = await session.get(UserSettings, user_id)
    if settings is None:
        settings = UserSettings(user_id=user_id)
        session.add(settings)
        await session.flush()
    return settings


# ---------------------------------------------------------------------
# GET /settings  (PRD §10.1)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def get_settings(
    session: SessionDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    settings = await _ensure_settings(session, user.id)
    payload = UserSettingsOut.model_validate(settings).model_dump(mode="json")
    payload["telegram_chat_id"] = user.telegram_chat_id
    payload["totp_enabled"] = user.totp_enabled
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# PATCH /settings (PRD §10.2)
# ---------------------------------------------------------------------


@router.patch("", status_code=status.HTTP_200_OK)
async def patch_settings(
    body: UserSettingsPatch,
    session: SessionDep,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    settings = await _ensure_settings(session, user.id)
    before = {
        "total_capital": str(settings.total_capital) if settings.total_capital else None,
        "notify_high": settings.notify_high,
        "theme": settings.theme,
    }

    for field_name, value in body.model_dump(exclude_unset=True).items():
        setattr(settings, field_name, value)
    await session.commit()

    after = {
        "total_capital": str(settings.total_capital) if settings.total_capital else None,
        "notify_high": settings.notify_high,
        "theme": settings.theme,
    }
    await record_audit(
        action=AuditAction.SETTINGS_CHANGED,
        user_id=user.id,
        before_state=before,
        after_state=after,
    )

    payload = UserSettingsOut.model_validate(settings).model_dump(mode="json")
    payload["telegram_chat_id"] = user.telegram_chat_id
    payload["totp_enabled"] = user.totp_enabled
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /settings/feature_flags  (PRD §10.3)
# ---------------------------------------------------------------------


@router.get("/feature_flags", status_code=status.HTTP_200_OK)
async def get_feature_flags(
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    if user.role not in {"OWNER", "ADMIN"}:
        # PRD §10.3 권한: ADMIN/OWNER. Other roles get 403.
        raise BusinessRuleError(
            "Insufficient role",
            error_code="FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    flags = feature_flags.all()
    grouped: dict[str, bool] = {}
    for k, v in flags.items():
        if k.startswith("v71."):
            grouped[k.split(".", 1)[1]] = v
    payload = FeatureFlagsOut(v71=grouped)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# PATCH /settings/feature_flags  (PRD §10.4)
# ---------------------------------------------------------------------


@router.patch("/feature_flags", status_code=status.HTTP_200_OK)
async def patch_feature_flags(
    body: FeatureFlagsPatch,
    user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    if user.role not in {"OWNER", "ADMIN"}:
        raise BusinessRuleError(
            "Insufficient role",
            error_code="FORBIDDEN",
            status_code=status.HTTP_403_FORBIDDEN,
        )
    before = feature_flags.all()
    for key, value in body.flags.items():
        feature_flags.set(key, bool(value))
    after = feature_flags.all()

    await record_audit(
        action=AuditAction.SETTINGS_CHANGED,
        user_id=user.id,
        target_type="feature_flags",
        before_state=before,
        after_state=after,
    )

    grouped: dict[str, bool] = {}
    for k, v in after.items():
        if k.startswith("v71."):
            grouped[k.split(".", 1)[1]] = v
    payload = FeatureFlagsOut(v71=grouped)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /settings/broker (PRD §10.5) — ★ PRD Patch #5: read-only
# ---------------------------------------------------------------------


@router.get("/broker", status_code=status.HTTP_200_OK)
async def get_broker_settings(
    _user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    """PRD Patch #5: 증권사 연동 상태 (read-only -- .env 파일에서 관리).

    See 09_API_SPEC.md §10.5 + 12_SECURITY.md §6.3 (시크릿 노출 금지).
    PATCH endpoint 없음.
    """
    import os

    account_no = os.getenv("KIWOOM_ACCOUNT_NO", "")
    # 마스킹: 앞 7자 노출 + 뒤 마스킹 (예: 1234-56**-**)
    if len(account_no) >= 7:
        masked = account_no[:7] + "**-**"
    elif account_no:
        masked = "****-****"
    else:
        masked = None

    is_paper = os.getenv("IS_PAPER_TRADING", "false").lower() in {"1", "true", "yes"}
    account_type = "MOCK" if is_paper else "REAL"

    payload = BrokerSettingsOut(
        kiwoom_account_no_masked=masked,
        kiwoom_account_type=account_type,
        app_key_configured=bool(os.getenv("KIWOOM_APP_KEY")),
        app_secret_configured=bool(os.getenv("KIWOOM_APP_SECRET")),
        # token_expires_at: token_manager 도입 시점에 채움 (Phase 5 후속)
        token_expires_at=None,
        managed_by=".env file",
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /settings/trading (PRD §10.6) — ★ PRD Patch #5: read-only
# ---------------------------------------------------------------------


@router.get("/trading", status_code=status.HTTP_200_OK)
async def get_trading_settings(
    _user: CurrentUserDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    """PRD Patch #5: 매매 설정 상태 (read-only).

    See 09_API_SPEC.md §10.6 + 02_TRADING_RULES.md.
    safe_mode 변경은 POST /system/safe_mode + /resume 사용.
    PATCH endpoint 없음.
    """
    import os

    from ..system.state import system_state

    is_paper = os.getenv("IS_PAPER_TRADING", "false").lower() in {"1", "true", "yes"}
    auto_trading = os.getenv("V71_AUTO_TRADING", "false").lower() in {"1", "true", "yes"}

    payload = TradingSettingsOut(
        auto_trading_enabled=auto_trading,
        safe_mode=system_state.is_safe_mode if hasattr(system_state, "is_safe_mode") else False,
        is_paper_trading=is_paper,
        max_position_pct_per_stock=30,
        profit_5_take_pct=30,
        profit_10_take_pct=30,
        stop_loss_default_pct=-5,
        managed_by=".env file + 02_TRADING_RULES.md constants",
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}
