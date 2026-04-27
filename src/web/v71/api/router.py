"""Mounted under ``/api/v71``. Sub-routers are added here."""

from __future__ import annotations

from fastapi import APIRouter

from ..auth.router import me_router as auth_me_router
from ..auth.router import router as auth_router
from . import health
from .boxes import router as boxes_router
from .notifications import router as notifications_router
from .orders import router as orders_router  # ★ PRD Patch #5
from .positions import router as positions_router
from .reports import router as reports_router
from .settings import router as settings_router
from .system import router as system_router
from .trade_events import router as trade_events_router
from .tracked_stocks import router as tracked_stocks_router
from .tracked_stocks import stocks_search_router

api_router = APIRouter(prefix="/api/v71")
api_router.include_router(health.router)
api_router.include_router(auth_router)
api_router.include_router(auth_me_router)
api_router.include_router(tracked_stocks_router)
api_router.include_router(stocks_search_router)
api_router.include_router(boxes_router)
api_router.include_router(positions_router)
api_router.include_router(orders_router)  # ★ PRD Patch #5 §13
api_router.include_router(trade_events_router)
api_router.include_router(notifications_router)
api_router.include_router(reports_router)
api_router.include_router(settings_router)
api_router.include_router(system_router)
