"""Auth use-cases -- orchestrates security primitives + repo + audit + cache.

The router delegates *all* business logic to this service so the HTTP
layer remains thin. The TOTP intermediate session is held in an in-process
cache; in production this should move to Redis (P5.4 follow-up).

Side effects mandated by ``09_API_SPEC §1.2``:

* LOGIN succeeds → ``audit_logs`` LOGIN
* LOGIN fails    → ``audit_logs`` LOGIN_FAILED  (success=False)
* New IP         → ``audit_logs`` NEW_IP_DETECTED + Telegram CRITICAL (P5.4.6)
* LOGOUT         → ``audit_logs`` LOGOUT
* TOTP ENABLE    → ``audit_logs`` TOTP_ENABLED
"""

from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from ..audit import record_audit
from ..config import WebSettings
from ..db_models import AuditAction, User
from ..exceptions import V71AuthenticationError
from . import repo
from .security import create_token, decode_token, hash_token, verify_password
from .totp import verify as verify_totp

if TYPE_CHECKING:  # pragma: no cover
    pass


def _ensure_utc(dt: datetime) -> datetime:
    """SQLite drops tzinfo on round-trip; coerce naive UTC → aware UTC.

    PostgreSQL preserves the offset, but the dev SQLite (data/dev.db)
    returns naive datetimes which crash ``<`` against ``datetime.now
    (timezone.utc)``. Treating naive as UTC is correct because
    ``security.create_token`` always writes UTC-aware via
    ``datetime.now(timezone.utc) + delta``.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------
# In-process TOTP session store (replace with Redis in prod)
# ---------------------------------------------------------------------


@dataclass
class _TotpSession:
    user_id: UUID
    expires_at: datetime
    ip_address: str | None
    user_agent: str | None


class _TotpSessionCache:
    def __init__(self) -> None:
        self._items: dict[str, _TotpSession] = {}
        self._lock = asyncio.Lock()

    async def put(
        self,
        user_id: UUID,
        *,
        ttl: timedelta,
        ip_address: str | None,
        user_agent: str | None,
    ) -> str:
        sid = uuid4().hex
        async with self._lock:
            self._items[sid] = _TotpSession(
                user_id=user_id,
                expires_at=datetime.now(timezone.utc) + ttl,
                ip_address=ip_address,
                user_agent=user_agent,
            )
        return sid

    async def consume(self, sid: str) -> _TotpSession | None:
        async with self._lock:
            item = self._items.pop(sid, None)
        if item is None:
            return None
        if item.expires_at < datetime.now(timezone.utc):
            return None
        return item


_totp_sessions = _TotpSessionCache()


# ---------------------------------------------------------------------
# Login flow (step 1)
# ---------------------------------------------------------------------


@dataclass
class LoginResult:
    requires_totp: bool
    user: User
    totp_session_id: str | None = None


# Pre-computed bcrypt(12) hash (never matches a real password) used for
# constant-time username probing defence. Generated once at import.
_DUMMY_HASH = "$2b$12$abcdefghijklmnopqrstuu3JlA/h41Q2hn3UajGNZOM6bw9RnPF.W"


async def login_step_one(
    session: AsyncSession,
    *,
    username: str,
    password: str,
    settings: WebSettings,
    ip_address: str | None,
    user_agent: str | None,
) -> LoginResult:
    user = await repo.get_user_by_username(session, username)

    if user is None:
        # Constant-ish time path: still hash compare a dummy value.
        verify_password(password, _DUMMY_HASH, settings)
        await record_audit(
            action=AuditAction.LOGIN_FAILED,
            user_id=None,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message=f"unknown username: {username[:32]}",
        )
        raise V71AuthenticationError(
            "Invalid credentials", error_code="INVALID_CREDENTIALS",
        )
    if not user.is_active:
        await record_audit(
            action=AuditAction.LOGIN_FAILED,
            user_id=user.id,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message="user is disabled",
        )
        raise V71AuthenticationError(
            "Invalid credentials", error_code="INVALID_CREDENTIALS",
        )
    if not verify_password(password, user.password_hash, settings):
        await record_audit(
            action=AuditAction.LOGIN_FAILED,
            user_id=user.id,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message="bad password",
        )
        raise V71AuthenticationError(
            "Invalid credentials", error_code="INVALID_CREDENTIALS",
        )

    if not user.totp_enabled or settings.environment == "dev":
        # No TOTP, or dev mode (TOTP intentionally bypassed for fast
        # iteration on the local SQLite). Production must always set
        # V71_WEB_ENVIRONMENT=prod so this branch never fires there.
        return LoginResult(requires_totp=False, user=user)

    sid = await _totp_sessions.put(
        user.id,
        ttl=timedelta(minutes=settings.totp_session_minutes),
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return LoginResult(requires_totp=True, user=user, totp_session_id=sid)


# ---------------------------------------------------------------------
# Login flow (step 2 -- TOTP)
# ---------------------------------------------------------------------


@dataclass
class IssuedTokens:
    access_token: str
    refresh_token: str
    access_expires_at: datetime
    refresh_expires_at: datetime
    user: User


async def verify_totp_and_issue_tokens(
    session: AsyncSession,
    *,
    session_id: str,
    totp_code: str,
    settings: WebSettings,
    ip_address: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    pending = await _totp_sessions.consume(session_id)
    if pending is None:
        await record_audit(
            action=AuditAction.LOGIN_FAILED,
            user_id=None,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message="totp session expired",
        )
        raise V71AuthenticationError(
            "TOTP session expired or invalid",
            error_code="SESSION_EXPIRED",
        )

    user = await repo.get_user_by_id(session, pending.user_id)
    if user is None or not user.is_active:
        raise V71AuthenticationError(
            "User not found or disabled", error_code="UNAUTHORIZED",
        )
    if not user.totp_secret:
        raise V71AuthenticationError(
            "TOTP not configured", error_code="UNAUTHORIZED",
        )

    if not verify_totp(user.totp_secret, totp_code):
        await record_audit(
            action=AuditAction.LOGIN_FAILED,
            user_id=user.id,
            success=False,
            ip_address=ip_address,
            user_agent=user_agent,
            error_message="invalid totp",
        )
        raise V71AuthenticationError(
            "Invalid TOTP code", error_code="INVALID_TOTP",
        )

    return await _issue_tokens(
        session,
        user=user,
        settings=settings,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------
# Refresh
# ---------------------------------------------------------------------


async def refresh_access_token(
    session: AsyncSession,
    *,
    refresh_token: str,
    settings: WebSettings,
) -> IssuedTokens:
    """Sliding refresh — 새 access + 새 refresh 발급 + 같은 row 갱신.

    PRD 12_SECURITY §3.5 (sliding session): 매 refresh 시 refresh token
    도 회전(rotation)시킨다. 효과:

    * 활동 중인 사용자: 새 refresh가 24h 더 살아있어 무한 연장.
    * 누군가 refresh를 탈취해도 한 번 사용하면 즉시 무효 (다음 정상
      요청에서 401 → 사용자 재로그인 강제).
    * 단일 device 모델: 같은 row를 갱신하므로 추가 storage cost 0.

    Returns the same ``IssuedTokens`` shape as the login flow so the
    router can produce a uniform ``TokenPair`` envelope.
    """
    claims = decode_token(refresh_token, settings=settings, expected_kind="refresh")
    rfh = hash_token(refresh_token)
    db_session = await repo.get_active_session_by_refresh_hash(session, rfh)
    if db_session is None:
        raise V71AuthenticationError(
            "Refresh token revoked or unknown",
            error_code="REFRESH_EXPIRED",
        )
    if _ensure_utc(db_session.refresh_expires_at) < datetime.now(timezone.utc):
        raise V71AuthenticationError(
            "Refresh token expired", error_code="REFRESH_EXPIRED",
        )

    user_id = UUID(claims["sub"])
    user = await repo.get_user_by_id(session, user_id)
    if user is None or not user.is_active:
        raise V71AuthenticationError(
            "User not found or disabled",
            error_code="UNAUTHORIZED",
        )

    new_access, new_access_exp = create_token(
        user_id=user_id, kind="access", settings=settings,
    )
    new_refresh, new_refresh_exp = create_token(
        user_id=user_id, kind="refresh", settings=settings,
    )

    db_session.access_token_hash = hash_token(new_access)
    db_session.refresh_token_hash = hash_token(new_refresh)
    db_session.access_expires_at = new_access_exp
    db_session.refresh_expires_at = new_refresh_exp
    await repo.touch_session_activity(session, db_session.id)

    return IssuedTokens(
        access_token=new_access,
        refresh_token=new_refresh,
        access_expires_at=new_access_exp,
        refresh_expires_at=new_refresh_exp,
        user=user,
    )


# ---------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------


async def logout(
    session: AsyncSession,
    *,
    user_id: UUID,
    access_token: str,
    ip_address: str | None,
    user_agent: str | None,
) -> None:
    await repo.revoke_session_by_access_hash(
        session, access_token_hash=hash_token(access_token),
    )
    await record_audit(
        action=AuditAction.LOGOUT,
        user_id=user_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


async def _issue_tokens(
    session: AsyncSession,
    *,
    user: User,
    settings: WebSettings,
    ip_address: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    is_new_ip = (
        ip_address is not None
        and user.last_login_ip is not None
        and str(user.last_login_ip) != ip_address
    )

    access_token, access_expires_at = create_token(
        user_id=user.id, kind="access", settings=settings,
    )
    refresh_token, refresh_expires_at = create_token(
        user_id=user.id, kind="refresh", settings=settings,
    )
    await repo.create_session(
        session,
        user_id=user.id,
        access_token_hash=hash_token(access_token),
        refresh_token_hash=hash_token(refresh_token),
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await repo.update_last_login(session, user.id, ip_address=ip_address)
    await session.commit()

    await record_audit(
        action=AuditAction.LOGIN,
        user_id=user.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    if is_new_ip:
        await record_audit(
            action=AuditAction.NEW_IP_DETECTED,
            user_id=user.id,
            ip_address=ip_address,
            user_agent=user_agent,
            before_state={"last_login_ip": str(user.last_login_ip)},
            after_state={"login_ip": ip_address},
        )
        # P5.4.6: Telegram CRITICAL alert hook will be added when the
        # trading-engine notification bus is wired.

    return IssuedTokens(
        access_token=access_token,
        refresh_token=refresh_token,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        user=user,
    )


async def issue_tokens_without_totp(
    session: AsyncSession,
    *,
    user: User,
    settings: WebSettings,
    ip_address: str | None,
    user_agent: str | None,
) -> IssuedTokens:
    return await _issue_tokens(
        session,
        user=user,
        settings=settings,
        ip_address=ip_address,
        user_agent=user_agent,
    )


# ---------------------------------------------------------------------
# Random helpers (used by router-level rate limit jitter)
# ---------------------------------------------------------------------


def random_jitter_seconds(low_ms: int = 100, high_ms: int = 300) -> float:
    """Random delay to defeat timing-attack username probes (PRD §1.2)."""
    raw = secrets.randbelow(high_ms - low_ms) + low_ms
    return raw / 1000.0
