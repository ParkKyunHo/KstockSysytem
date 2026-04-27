"""FastAPI dependency providers (request-scoped wiring).

Auth-aware deps land here in P5.4.2; this file currently exposes only
infrastructure deps (settings, DB session, request id).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from .config import WebSettings, get_settings
from .db import get_session


def request_id_dep(request: Request) -> str:
    """Pulls the per-request id stamped by the request_id middleware."""
    return getattr(request.state, "request_id", "")


SettingsDep = Annotated[WebSettings, Depends(get_settings)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
RequestIdDep = Annotated[str, Depends(request_id_dep)]
