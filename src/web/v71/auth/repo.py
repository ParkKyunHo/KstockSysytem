"""Auth-related DB access (users + sessions).

Repository layer keeps SQL out of the router. Sessions are passed in
explicitly so unit tests can wire a SQLite ``async_sessionmaker``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..db_models import User, UserSession


async def get_user_by_username(
    session: AsyncSession,
    username: str,
) -> User | None:
    result = await session.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(
    session: AsyncSession,
    user_id: UUID,
) -> User | None:
    return await session.get(User, user_id)


async def update_last_login(
    session: AsyncSession,
    user_id: UUID,
    *,
    ip_address: str | None,
) -> None:
    await session.execute(
        update(User)
        .where(User.id == user_id)
        .values(
            last_login_at=datetime.now(timezone.utc),
            last_login_ip=ip_address,
        )
    )


async def create_session(
    session: AsyncSession,
    *,
    user_id: UUID,
    access_token_hash: str,
    refresh_token_hash: str,
    access_expires_at: datetime,
    refresh_expires_at: datetime,
    ip_address: str | None,
    user_agent: str | None,
) -> UserSession:
    obj = UserSession(
        user_id=user_id,
        access_token_hash=access_token_hash,
        refresh_token_hash=refresh_token_hash,
        access_expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    session.add(obj)
    await session.flush()
    return obj


async def revoke_session(
    session: AsyncSession,
    *,
    refresh_token_hash: str,
) -> int:
    """Revoke by refresh hash. Returns rows affected."""
    result = await session.execute(
        update(UserSession)
        .where(
            UserSession.refresh_token_hash == refresh_token_hash,
            UserSession.revoked.is_(False),
        )
        .values(revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    return result.rowcount or 0


async def revoke_session_by_access_hash(
    session: AsyncSession,
    *,
    access_token_hash: str,
) -> int:
    result = await session.execute(
        update(UserSession)
        .where(
            UserSession.access_token_hash == access_token_hash,
            UserSession.revoked.is_(False),
        )
        .values(revoked=True, revoked_at=datetime.now(timezone.utc))
    )
    return result.rowcount or 0


async def get_active_session_by_refresh_hash(
    session: AsyncSession,
    refresh_token_hash: str,
) -> UserSession | None:
    result = await session.execute(
        select(UserSession).where(
            UserSession.refresh_token_hash == refresh_token_hash,
            UserSession.revoked.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def touch_session_activity(
    session: AsyncSession,
    session_id: UUID,
) -> None:
    await session.execute(
        update(UserSession)
        .where(UserSession.id == session_id)
        .values(last_activity_at=datetime.now(timezone.utc))
    )
