"""Health + readiness probes (09_API_SPEC §9).

``/health`` returns liveness only -- no external dependencies are
checked. ``/ready`` exercises the database round-trip; deployment
orchestrators can hit it before sending real traffic.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, status
from sqlalchemy import text

from ..dependencies import RequestIdDep, SessionDep
from ..schemas.common import build_meta

router = APIRouter(tags=["system"])


@router.get("/health", status_code=status.HTTP_200_OK)
async def health(request_id: RequestIdDep) -> dict[str, Any]:
    return {
        "data": {"status": "ok"},
        "meta": build_meta(request_id),
    }


@router.get("/ready", status_code=status.HTTP_200_OK)
async def ready(session: SessionDep, request_id: RequestIdDep) -> dict[str, Any]:
    db_ok = False
    try:
        result = await session.execute(text("SELECT 1"))
        db_ok = result.scalar_one() == 1
    except Exception:
        db_ok = False
    return {
        "data": {
            "status": "ready" if db_ok else "degraded",
            "database": db_ok,
        },
        "meta": build_meta(request_id),
    }
