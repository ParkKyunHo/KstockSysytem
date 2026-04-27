"""Notification REST endpoints (09_API_SPEC §7)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import CurrentUserDep
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import NotFoundError, V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.notifications import (
    NotificationOut,
    NotificationTestRequest,
    NotificationTestResponse,
    NotificationUnreadOut,
)
from src.database.models_v71 import (
    Notification,
    NotificationChannel,
    NotificationSeverity,
    NotificationStatus,
)

router = APIRouter(prefix="/notifications", tags=["notifications"])


_PRIORITY = {
    NotificationSeverity.CRITICAL: 1,
    NotificationSeverity.HIGH: 2,
    NotificationSeverity.MEDIUM: 3,
    NotificationSeverity.LOW: 4,
}


def _parse_severity(raw: str | None) -> NotificationSeverity | None:
    if raw is None:
        return None
    try:
        return NotificationSeverity(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid severity",
            error_code="INVALID_PARAMETER",
            details={"field": "severity", "value": raw},
        ) from exc


def _parse_status(raw: str | None) -> NotificationStatus | None:
    if raw is None:
        return None
    try:
        return NotificationStatus(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid status",
            error_code="INVALID_PARAMETER",
            details={"field": "status", "value": raw},
        ) from exc


def _decode_cursor(cursor: str | None) -> tuple[datetime | None, UUID | None]:
    if not cursor:
        return None, None
    try:
        c = PaginationCursor.decode(cursor)
        return datetime.fromisoformat(c.sort_value), UUID(c.id)
    except Exception as exc:  # noqa: BLE001
        raise V71Error(
            "Invalid pagination cursor",
            error_code="INVALID_CURSOR",
            details={"cursor": cursor},
        ) from exc


def _encode_cursor(n: Notification) -> str:
    return PaginationCursor(
        id=str(n.id), sort_value=n.created_at.isoformat()
    ).encode()


def _to_out(n: Notification) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        severity=n.severity.value,
        channel=n.channel.value,
        event_type=n.event_type,
        stock_code=n.stock_code,
        title=n.title,
        message=n.message,
        payload=n.payload,
        status=n.status.value,
        sent_at=n.sent_at,
        created_at=n.created_at,
    )


# ---------------------------------------------------------------------
# GET /notifications  (PRD §7.1)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_notifications(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    severity: str | None = Query(default=None),
    status_q: str | None = Query(default=None, alias="status"),
    event_type: str | None = Query(default=None),
    stock_code: str | None = Query(default=None, max_length=10),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    stmt = select(Notification)
    sev = _parse_severity(severity)
    if sev is not None:
        stmt = stmt.where(Notification.severity == sev)
    st = _parse_status(status_q)
    if st is not None:
        stmt = stmt.where(Notification.status == st)
    if event_type is not None:
        stmt = stmt.where(Notification.event_type == event_type)
    if stock_code is not None:
        stmt = stmt.where(Notification.stock_code == stock_code)
    if from_date is not None:
        stmt = stmt.where(Notification.created_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(Notification.created_at <= to_date)

    after_dt, after_id = _decode_cursor(cursor)
    if after_dt is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                Notification.created_at < after_dt,
                (Notification.created_at == after_dt) & (Notification.id < after_id),
            )
        )

    stmt = stmt.order_by(
        Notification.created_at.desc(), Notification.id.desc()
    ).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [_to_out(n).model_dump(mode="json") for n in rows]
    next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None
    meta = build_list_meta(request_id=request_id, limit=limit, next_cursor=next_cursor)
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# GET /notifications/unread  (PRD §7.2)
# ---------------------------------------------------------------------


@router.get("/unread", status_code=status.HTTP_200_OK)
async def unread_notifications(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    stmt = (
        select(Notification)
        .where(
            Notification.severity.in_(
                [NotificationSeverity.CRITICAL, NotificationSeverity.HIGH]
            ),
            Notification.status != NotificationStatus.SENT,
            Notification.channel.in_(
                [NotificationChannel.WEB, NotificationChannel.BOTH]
            ),
        )
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    rows = list((await session.execute(stmt)).scalars().all())
    items = [_to_out(n) for n in rows]
    payload = NotificationUnreadOut(unread_count=len(items), items=items)
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# POST /notifications/{id}/mark_read  (PRD §7.3)
# ---------------------------------------------------------------------


@router.post("/{notification_id}/mark_read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_notification_read(
    notification_id: UUID,
    session: SessionDep,
    _user: CurrentUserDep,
) -> Response:
    n = await session.get(Notification, notification_id)
    if n is None:
        raise NotFoundError(
            f"notification {notification_id} not found",
            error_code="NOT_FOUND",
        )
    n.status = NotificationStatus.SENT
    if n.sent_at is None:
        n.sent_at = datetime.now(timezone.utc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------
# POST /notifications/test  (PRD §7.4)
# ---------------------------------------------------------------------


@router.post("/test", status_code=status.HTTP_200_OK)
async def test_notification(
    body: NotificationTestRequest,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    sev_enum = NotificationSeverity(body.severity)
    chan_enum = NotificationChannel(body.channel)

    n = Notification(
        severity=sev_enum,
        channel=chan_enum,
        event_type="TEST",
        stock_code=None,
        title="[TEST] 알림 테스트",
        message="이것은 테스트 알림입니다.",
        payload={"requested_by": "test"},
        status=NotificationStatus.SENT,  # P5.4.6 wires real Telegram send
        sent_at=datetime.now(timezone.utc),
        retry_count=0,
        priority=_PRIORITY[sev_enum],
    )
    session.add(n)
    await session.commit()

    payload = NotificationTestResponse(
        notification_id=n.id,
        status=n.status.value,  # type: ignore[arg-type]
        sent_at=n.sent_at,
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}
