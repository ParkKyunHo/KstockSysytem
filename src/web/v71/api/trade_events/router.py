"""Trade event REST endpoints (09_API_SPEC §6)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import CurrentUserDep
from ...dependencies import RequestIdDep, SessionDep
from ...exceptions import V71Error
from ...schemas.common import PaginationCursor, build_list_meta, build_meta
from ...schemas.trade_events import (
    TradeEventOut,
    TradeEventTodayBuy,
    TradeEventTodayOut,
    TradeEventTodaySell,
)
from src.database.models_v71 import TradeEvent, TradeEventType, TrackedStock

router = APIRouter(prefix="/trade_events", tags=["trade_events"])


_BUY_TYPES = {
    TradeEventType.BUY_EXECUTED,
    TradeEventType.PYRAMID_BUY,
    TradeEventType.MANUAL_BUY,
    TradeEventType.MANUAL_PYRAMID_BUY,
}
_SELL_TYPES = {
    TradeEventType.PROFIT_TAKE_5,
    TradeEventType.PROFIT_TAKE_10,
    TradeEventType.STOP_LOSS,
    TradeEventType.TS_EXIT,
    TradeEventType.MANUAL_PARTIAL_EXIT,
    TradeEventType.MANUAL_FULL_EXIT,
    TradeEventType.AUTO_EXIT,
}
_AUTO_EXIT_TYPES = {TradeEventType.AUTO_EXIT}
_MANUAL_TYPES = {
    TradeEventType.MANUAL_BUY,
    TradeEventType.MANUAL_PYRAMID_BUY,
    TradeEventType.MANUAL_PARTIAL_EXIT,
    TradeEventType.MANUAL_FULL_EXIT,
}


def _parse_event_type(raw: str | None) -> TradeEventType | None:
    if raw is None:
        return None
    try:
        return TradeEventType(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid event_type",
            error_code="INVALID_PARAMETER",
            details={"field": "event_type", "value": raw},
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


def _encode_cursor(e: TradeEvent) -> str:
    return PaginationCursor(
        id=str(e.id), sort_value=e.occurred_at.isoformat()
    ).encode()


# ---------------------------------------------------------------------
# GET /trade_events (PRD §6.1)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_trade_events(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    position_id: UUID | None = Query(default=None),
    tracked_stock_id: UUID | None = Query(default=None),
    event_type: str | None = Query(default=None),
    stock_code: str | None = Query(default=None, max_length=10),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict[str, Any]:
    stmt = select(TradeEvent)
    if position_id is not None:
        stmt = stmt.where(TradeEvent.position_id == position_id)
    if tracked_stock_id is not None:
        stmt = stmt.where(TradeEvent.tracked_stock_id == tracked_stock_id)
    et = _parse_event_type(event_type)
    if et is not None:
        stmt = stmt.where(TradeEvent.event_type == et)
    if stock_code is not None:
        stmt = stmt.where(TradeEvent.stock_code == stock_code)
    if from_date is not None:
        stmt = stmt.where(TradeEvent.occurred_at >= from_date)
    if to_date is not None:
        stmt = stmt.where(TradeEvent.occurred_at <= to_date)

    after_dt, after_id = _decode_cursor(cursor)
    if after_dt is not None and after_id is not None:
        stmt = stmt.where(
            or_(
                TradeEvent.occurred_at < after_dt,
                (TradeEvent.occurred_at == after_dt) & (TradeEvent.id < after_id),
            )
        )

    stmt = stmt.order_by(
        TradeEvent.occurred_at.desc(), TradeEvent.id.desc()
    ).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    # Resolve stock_name via tracked_stocks join lookup (cheap N).
    name_cache: dict[str, str] = {}
    if rows:
        codes = list({e.stock_code for e in rows})
        ts_rows = await session.execute(
            select(TrackedStock.stock_code, TrackedStock.stock_name).where(
                TrackedStock.stock_code.in_(codes)
            )
        )
        for code, name in ts_rows:
            name_cache[code] = name

    data: list[dict[str, Any]] = []
    for e in rows:
        out = TradeEventOut.model_validate(e).model_dump(mode="json")
        out["stock_name"] = name_cache.get(e.stock_code)
        out["event_type"] = e.event_type.value
        data.append(out)

    next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None
    meta = build_list_meta(request_id=request_id, limit=limit, next_cursor=next_cursor)
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# GET /trade_events/today (PRD §6.2)
# ---------------------------------------------------------------------


@router.get("/today", status_code=status.HTTP_200_OK)
async def trade_events_today(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    # KST 자정 ~ 다음 자정 UTC 변환.
    now_kst = datetime.now(timezone.utc) + timedelta(hours=9)
    kst_midnight = now_kst.replace(hour=0, minute=0, second=0, microsecond=0)
    start = kst_midnight - timedelta(hours=9)  # back to UTC
    end = start + timedelta(days=1)

    rows = list(
        (
            await session.execute(
                select(TradeEvent)
                .where(TradeEvent.occurred_at >= start)
                .where(TradeEvent.occurred_at < end)
                .order_by(TradeEvent.occurred_at.asc())
            )
        ).scalars().all()
    )

    buys: list[TradeEventTodayBuy] = []
    sells: list[TradeEventTodaySell] = []
    auto_exits: list[TradeEventTodaySell] = []
    manual_trades: list[TradeEventTodaySell] = []
    total_pnl = Decimal(0)

    for e in rows:
        if e.event_type in _BUY_TYPES:
            buys.append(
                TradeEventTodayBuy(
                    stock_code=e.stock_code,
                    quantity=e.quantity,
                    price=e.price,
                    occurred_at=e.occurred_at,
                )
            )
        elif e.event_type in _SELL_TYPES:
            sell = TradeEventTodaySell(
                stock_code=e.stock_code,
                quantity=e.quantity,
                price=e.price,
                pnl=e.pnl_amount,
                pnl_pct=e.pnl_pct,
                reason=e.event_type.value,
                occurred_at=e.occurred_at,
            )
            sells.append(sell)
            if e.pnl_amount is not None:
                total_pnl += e.pnl_amount
            if e.event_type in _AUTO_EXIT_TYPES:
                auto_exits.append(sell)
        if e.event_type in _MANUAL_TYPES:
            manual_trades.append(
                TradeEventTodaySell(
                    stock_code=e.stock_code,
                    quantity=e.quantity,
                    price=e.price,
                    pnl=e.pnl_amount,
                    pnl_pct=e.pnl_pct,
                    reason=e.event_type.value,
                    occurred_at=e.occurred_at,
                )
            )

    payload = TradeEventTodayOut(
        date=date.fromisoformat(kst_midnight.date().isoformat()),
        total_pnl=total_pnl,
        total_pnl_pct=None,
        buys=buys,
        sells=sells,
        auto_exits=auto_exits,
        manual_trades=manual_trades,
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}
