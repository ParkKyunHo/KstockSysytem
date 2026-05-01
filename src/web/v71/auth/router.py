"""Auth endpoints -- ``/api/v71/auth/*`` (09_API_SPEC §1)."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, Request, Response, status

from ..audit import record_audit
from ..db_models import AuditAction
from ..dependencies import RequestIdDep, SessionDep, SettingsDep
from ..exceptions import V71AuthenticationError
from ..rate_limit import (
    LOGIN_LIMIT,  # noqa: F401 -- kept for slowapi reactivation path
    limiter,  # noqa: F401
    login_rate_limit,
    refresh_rate_limit,
    totp_rate_limit,
)
from ..schemas.common import build_meta
from . import service, totp
from .dependencies import AccessTokenDep, CurrentUserDep
from .schemas import (
    CurrentUserOut,
    LoginPendingTotp,
    LoginRequest,
    RefreshRequest,
    TokenPair,
    TotpConfirmRequest,
    TotpConfirmResponse,
    TotpSetupResponse,
    TotpVerifyRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _client_ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else None


def _user_agent(request: Request) -> str | None:
    return request.headers.get("user-agent")


def _envelope(payload: Any, request_id: str) -> dict[str, Any]:
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# POST /auth/login (PRD §1.2 step 1) -- IP당 5회/분
# ---------------------------------------------------------------------


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(login_rate_limit)],
)
# Note: slowapi 의 @limiter.limit 는 fastapi 0.115 signature introspection
# 을 깨뜨려 query/body validation 실패. D (2026-04-29) 자체 sliding-window
# limiter (rate_limit.py) 로 교체. PRD §1.2 = 5/분/IP.
async def login(
    body: LoginRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    # PRD §1.2 보안: 실패 시 timing attack 방어 (랜덤 0.1~0.3초).
    await asyncio.sleep(service.random_jitter_seconds())

    ip = _client_ip(request)
    ua = _user_agent(request)

    result = await service.login_step_one(
        session,
        username=body.username,
        password=body.password,
        settings=settings,
        ip_address=ip,
        user_agent=ua,
    )

    if result.requires_totp:
        payload = LoginPendingTotp(session_id=result.totp_session_id or "")
        return _envelope(payload.model_dump(), request_id)

    issued = await service.issue_tokens_without_totp(
        session,
        user=result.user,
        settings=settings,
        ip_address=ip,
        user_agent=ua,
    )
    payload = TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=settings.access_token_minutes * 60,
    )
    return _envelope(payload.model_dump(), request_id)


# ---------------------------------------------------------------------
# POST /auth/totp/verify (PRD §1.2 step 2)
# ---------------------------------------------------------------------


@router.post(
    "/totp/verify",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(totp_rate_limit)],
)
async def totp_verify(
    body: TotpVerifyRequest,
    request: Request,
    session: SessionDep,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    issued = await service.verify_totp_and_issue_tokens(
        session,
        session_id=body.session_id,
        totp_code=body.totp_code,
        settings=settings,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    payload = TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=settings.access_token_minutes * 60,
    )
    return _envelope(payload.model_dump(), request_id)


# ---------------------------------------------------------------------
# POST /auth/refresh (PRD §1.2 refresh)
# ---------------------------------------------------------------------


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    dependencies=[Depends(refresh_rate_limit)],
)
async def refresh(
    body: RefreshRequest,
    session: SessionDep,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    """Sliding refresh — 새 access + 새 refresh 회전(PRD §3.5).

    Response shape changed from ``AccessTokenResponse`` (access only) to
    ``TokenPair`` so the client can store the rotated refresh token.
    Old clients that ignore the ``refresh_token`` field still work but
    will hit 401 once their cached refresh expires (24h max).
    """
    issued = await service.refresh_access_token(
        session,
        refresh_token=body.refresh_token,
        settings=settings,
    )
    await session.commit()
    payload = TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=settings.access_token_minutes * 60,
    )
    return _envelope(payload.model_dump(), request_id)


# ---------------------------------------------------------------------
# POST /auth/logout (PRD §1.2 logout) -- 204 + audit_logs
# ---------------------------------------------------------------------


@router.post("/logout")
async def logout(
    request: Request,
    session: SessionDep,
    user: CurrentUserDep,
    access_token: AccessTokenDep,
) -> Response:
    await service.logout(
        session,
        user_id=user.id,
        access_token=access_token,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# POST /auth/totp/setup (PRD §1.2 totp/setup)
# ---------------------------------------------------------------------


@router.post("/totp/setup", status_code=status.HTTP_200_OK)
async def totp_setup(
    user: CurrentUserDep,
    session: SessionDep,
    settings: SettingsDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    secret = totp.generate_secret()
    backup_codes = totp.generate_backup_codes()
    user.totp_secret = secret
    user.backup_codes = backup_codes
    user.totp_enabled = False  # not enabled until /confirm
    await session.commit()

    payload = TotpSetupResponse(
        totp_secret=secret,
        qr_code_url=totp.provisioning_uri(secret, user.username, settings),
        backup_codes=backup_codes,
    )
    return _envelope(payload.model_dump(), request_id)


# ---------------------------------------------------------------------
# POST /auth/totp/confirm (PRD §1.2 totp/confirm) -- audit_logs TOTP_ENABLED
# ---------------------------------------------------------------------


@router.post("/totp/confirm", status_code=status.HTTP_200_OK)
async def totp_confirm(
    body: TotpConfirmRequest,
    request: Request,
    user: CurrentUserDep,
    session: SessionDep,
    request_id: RequestIdDep,
) -> dict[str, Any]:
    if not user.totp_secret:
        raise V71AuthenticationError(
            "TOTP setup not initiated",
            error_code="UNAUTHORIZED",
        )
    if not totp.verify(user.totp_secret, body.totp_code):
        raise V71AuthenticationError("Invalid TOTP code", error_code="INVALID_TOTP")
    user.totp_enabled = True
    await session.commit()
    await record_audit(
        action=AuditAction.TOTP_ENABLED,
        user_id=user.id,
        ip_address=_client_ip(request),
        user_agent=_user_agent(request),
    )
    payload = TotpConfirmResponse(totp_enabled=True)
    return _envelope(payload.model_dump(), request_id)


# ---------------------------------------------------------------------
# GET /api/v71/users/me (사용자 본인 정보)
# ---------------------------------------------------------------------


me_router = APIRouter(prefix="/users", tags=["auth"])


@me_router.get("/me", status_code=status.HTTP_200_OK)
async def me(user: CurrentUserDep, request_id: RequestIdDep) -> dict[str, Any]:
    payload = CurrentUserOut(
        id=str(user.id),
        username=user.username,
        role=user.role,
        totp_enabled=user.totp_enabled,
        telegram_chat_id=user.telegram_chat_id,
    )
    return _envelope(payload.model_dump(), request_id)
