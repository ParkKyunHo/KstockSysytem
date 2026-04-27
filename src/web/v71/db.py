"""DB session adapter for the V7.1 web backend.

The legacy :class:`~src.database.connection.DatabaseManager` already
handles PostgreSQL/SQLite fallback, Windows event-loop quirks, PgBouncer
``prepare_threshold=None``, and ``REPEATABLE READ`` isolation. This
module exposes a thin FastAPI-shaped adapter over that singleton so
tests can reuse the same session machinery as the trading engine.

V7.1 ORM models (User, UserSession, UserSettings, AuditLog, ...) live in
``src.database.models_v71`` and share the legacy ``Base.metadata``; that
keeps ``DatabaseManager.create_all`` registering both schemas.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

# Importing the V7.1 models registers them on the shared metadata before
# DatabaseManager calls ``Base.metadata.create_all``.
from src.database import models_v71 as _v71_models  # noqa: F401  (side-effect)
from src.database.connection import (
    DatabaseManager,
    close_database,
    get_db_manager,
    init_database,
)


async def startup_db() -> None:
    """Initialise the shared ``DatabaseManager`` (idempotent)."""
    await init_database()


async def shutdown_db() -> None:
    await close_database()


def get_manager() -> DatabaseManager:
    return get_db_manager()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that yields one ``AsyncSession`` per request.

    Routes (or service-layer code they call) are responsible for
    ``await session.commit()``. This dependency only rolls back when an
    exception bubbles out, mirroring SQLAlchemy's recommended pattern.
    """
    manager = get_db_manager()
    if not manager.is_initialized:
        await manager.initialize()
    factory = manager._session_factory  # type: ignore[attr-defined]
    if factory is None:
        raise RuntimeError("DatabaseManager session factory not ready")
    async with factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
