"""FastAPI lifespan -- startup/shutdown hooks.

Boots the shared :class:`~src.database.connection.DatabaseManager`
(SQLAlchemy engine + session factory) once per process, then disposes
it on shutdown. When ``V71_WEB_BOOT_TRADING_ENGINE=true`` the V7.1
trading engine entry point is also attached so its publishers reach
the WebSocket bus through ``trading_bridge``.

The trading engine attachment is best-effort -- a missing or failing
engine must not prevent the web backend from serving REST traffic.
"""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import get_settings
from .db import shutdown_db, startup_db

logger = logging.getLogger(__name__)


def _trading_engine_enabled() -> bool:
    raw = os.getenv("V71_WEB_BOOT_TRADING_ENGINE", "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info("V7.1 web backend starting (env=%s)", settings.environment)
    await startup_db()

    engine_handle = None
    if _trading_engine_enabled():
        try:
            from .trading_bridge import attach_trading_engine

            engine_handle = await attach_trading_engine()
            logger.info("V7.1 trading engine attached")
        except Exception:  # pragma: no cover - defensive
            logger.exception(
                "V7.1 trading engine attach failed -- web continues without it",
            )
            engine_handle = None

    try:
        yield
    finally:
        if engine_handle is not None:
            try:
                from .trading_bridge import detach_trading_engine

                await detach_trading_engine(engine_handle)
            except Exception:  # pragma: no cover - defensive
                logger.exception("V7.1 trading engine detach failed")
        logger.info("V7.1 web backend shutting down")
        await shutdown_db()
