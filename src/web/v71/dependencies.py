"""FastAPI dependency providers (request-scoped wiring).

Auth-aware deps land here in P5.4.2; this file currently exposes only
infrastructure deps (settings, DB session, request id, box manager).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from .config import WebSettings, get_settings
from .db import get_session

if TYPE_CHECKING:
    from src.core.v71.box.box_manager import V71BoxManager


def request_id_dep(request: Request) -> str:
    """Pulls the per-request id stamped by the request_id middleware."""
    return getattr(request.state, "request_id", "")


def box_manager_dep(request: Request) -> V71BoxManager:
    """Returns the lifespan-built V71BoxManager.

    P-Wire-Box-2: web service create/patch/delete go through the manager
    so DB writes are visible to the trading engine in real time. The
    instance is constructed in :mod:`lifespan` once per process and
    cached in ``app.state.box_manager``.

    Raises 503 if the manager is not available -- typically because
    ``v71.box_system`` is off at boot. This is a fail-loud signal: the
    UI must not silently lose a box write.
    """
    bm = getattr(request.app.state, "box_manager", None)
    if bm is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "V71BoxManager not initialised. Check that "
                "v71.box_system feature flag is true and DB connection "
                "is healthy, then restart the web backend."
            ),
        )
    return bm


SettingsDep = Annotated[WebSettings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RequestIdDep = Annotated[str, Depends(request_id_dep)]
BoxManagerDep = Annotated["V71BoxManager", Depends(box_manager_dep)]
