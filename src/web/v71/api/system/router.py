"""System REST endpoints (09_API_SPEC §9)."""

from __future__ import annotations

from datetime import datetime, time as dtime, timezone
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import CurrentUserDep
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import NotFoundError, V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.system import (
    AsyncTaskOut,
    BoxEntryMissResponse,
    DatabaseStatus,
    KiwoomApiStatus,
    MarketStatus,
    SafeModeRequest,
    SafeModeResponse,
    SystemHealthOut,
    SystemRestartOut,
    SystemStatusOut,
    TelegramBotStatus,
    WebsocketStatus,
)
from src.database.models_v71 import SystemRestart

from .state import feature_flags, system_state
from .tasks import TaskStatus, TaskType, task_registry

router = APIRouter(prefix="/system", tags=["system"])


# ---------------------------------------------------------------------
# /system/status (PRD §9.1)
# ---------------------------------------------------------------------


def _market_status() -> MarketStatus:
    """Best-effort market status derived from KST trading hours.

    P5.4.6 hooks the real ``market_calendar`` table.
    """
    now = datetime.now(timezone.utc)
    # KST = UTC + 9
    kst_hour = (now.hour + 9) % 24
    kst_minute = now.minute
    is_open = (kst_hour > 9 or (kst_hour == 9 and kst_minute >= 0)) and (
        kst_hour < 15 or (kst_hour == 15 and kst_minute <= 30)
    )
    session_kind: str | None = None
    if is_open:
        session_kind = "REGULAR"
    return MarketStatus(
        is_open=is_open,
        session=session_kind,  # type: ignore[arg-type]
        next_open_at=None,
        next_close_at=None,
    )


@router.get("/status", status_code=status.HTTP_200_OK)
async def system_status(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    db_ok = True
    db_latency = 0
    try:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        db_ok = False

    if system_state.safe_mode:
        sys_status = "SAFE_MODE"
    else:
        sys_status = "RUNNING"

    payload = SystemStatusOut(
        status=sys_status,  # type: ignore[arg-type]
        uptime_seconds=system_state.uptime_seconds(),
        websocket=WebsocketStatus(
            connected=system_state.websocket_connected,
            last_disconnect_at=system_state.last_websocket_disconnect_at,
            reconnect_count_today=system_state.websocket_reconnect_count_today,
        ),
        kiwoom_api=KiwoomApiStatus(
            available=system_state.kiwoom_available,
        ),
        telegram_bot=TelegramBotStatus(active=system_state.telegram_active),
        database=DatabaseStatus(connected=db_ok, latency_ms=db_latency),
        feature_flags=feature_flags.all(),
        market=_market_status(),
        current_time=datetime.now(timezone.utc),
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# /system/health (PRD §9.2)
# ---------------------------------------------------------------------


@router.get("/health", status_code=status.HTTP_200_OK)
async def system_health(
    session: SessionDep,
    request_id: RequestIdDep,
    response: Response,
) -> dict[str, Any]:
    checks: dict[str, str] = {}
    details: dict[str, str] = {}

    try:
        from sqlalchemy import text

        await session.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["db"] = "fail"
        details["db"] = str(exc)[:200]

    checks["kiwoom"] = "ok" if system_state.kiwoom_available else "fail"
    checks["websocket"] = "ok" if system_state.websocket_connected else "fail"
    checks["telegram"] = "ok" if system_state.telegram_active else "fail"

    overall = "healthy" if all(v == "ok" for v in checks.values()) else "degraded"
    if overall == "degraded":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    payload = SystemHealthOut(
        status=overall,  # type: ignore[arg-type]
        checks=checks,  # type: ignore[arg-type]
        details=details or None,
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# /system/safe_mode (PRD §9.3) + /system/resume (PRD §9.4)
# ---------------------------------------------------------------------


@router.post("/safe_mode", status_code=status.HTTP_200_OK)
async def enter_safe_mode(
    body: SafeModeRequest,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    system_state.safe_mode = True
    system_state.safe_mode_reason = body.reason
    system_state.safe_mode_entered_at = now
    payload = SafeModeResponse(safe_mode=True, entered_at=now)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


@router.post("/resume", status_code=status.HTTP_200_OK)
async def resume_from_safe_mode(
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    system_state.safe_mode = False
    system_state.safe_mode_resumed_at = now
    payload = SafeModeResponse(safe_mode=False, resumed_at=now)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# /system/restarts (PRD §9.5)
# ---------------------------------------------------------------------


@router.get("/restarts", status_code=status.HTTP_200_OK)
async def list_restarts(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    limit: int = Query(default=20, ge=1, le=200),
    cursor: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
) -> dict[str, Any]:
    stmt = select(SystemRestart)
    if from_date is not None:
        stmt = stmt.where(SystemRestart.restart_at >= from_date)

    after_dt: datetime | None = None
    after_id: UUID | None = None
    if cursor:
        try:
            c = PaginationCursor.decode(cursor)
            after_dt = datetime.fromisoformat(c.sort_value)
            after_id = UUID(c.id)
        except Exception as exc:  # noqa: BLE001
            raise V71Error(
                "Invalid pagination cursor",
                error_code="INVALID_CURSOR",
            ) from exc

    if after_dt is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                SystemRestart.restart_at < after_dt,
                (SystemRestart.restart_at == after_dt) & (SystemRestart.id < after_id),
            )
        )

    stmt = stmt.order_by(
        SystemRestart.restart_at.desc(), SystemRestart.id.desc()
    ).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [SystemRestartOut.model_validate(r).model_dump(mode="json") for r in rows]
    next_cursor: str | None = None
    if has_more and rows:
        next_cursor = PaginationCursor(
            id=str(rows[-1].id), sort_value=rows[-1].restart_at.isoformat()
        ).encode()
    meta = build_list_meta(request_id=request_id, limit=limit, next_cursor=next_cursor)
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# /system/tasks/{id} (PRD §9.6)
# ---------------------------------------------------------------------


@router.get("/tasks/{task_id}", status_code=status.HTTP_200_OK)
async def get_task(
    task_id: UUID,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    rec = task_registry.get(task_id)
    if rec is None:
        raise NotFoundError(f"task {task_id} not found", error_code="NOT_FOUND")
    payload = AsyncTaskOut(
        task_id=rec.id,
        type=rec.type.value,
        status=rec.status.value,  # type: ignore[arg-type]
        progress=rec.progress,
        started_at=rec.started_at,
        completed_at=rec.completed_at,
        result=rec.result,
        error=rec.error,
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# /system/audit/box_entry_miss (PRD §9.7)
# ---------------------------------------------------------------------


@router.post("/audit/box_entry_miss", status_code=status.HTTP_202_ACCEPTED)
async def trigger_box_entry_miss(
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    rec = task_registry.create(TaskType.BOX_ENTRY_MISS_AUDIT)
    payload = BoxEntryMissResponse(task_id=rec.id, checked_stocks=0, found_misses=0)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}
