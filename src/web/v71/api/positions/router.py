"""Positions REST endpoints (09_API_SPEC §5).

Read-only API plus an async ``/reconcile`` trigger. Real reconciliation
runs against the trading engine and is wired in P5.4.6; this module only
records the task placeholder for the moment.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
from ...schemas.positions import (
    EffectiveStopOut,
    PositionDetailOut,
    PositionOut,
    PositionSourceBreakdown,
    PositionStockAtLimit,
    PositionSummaryOut,
    ReconcileTaskOut,
    TradeEventInline,
)
from ..system.tasks import task_registry, TaskType
from src.database.models_v71 import (
    V71Position,
    PositionSource,
    PositionStatus,
    TradeEvent,
)

router = APIRouter(prefix="/positions", tags=["positions"])

_DEFAULT_TOTAL_CAPITAL = Decimal(100_000_000)
_LIMIT_PCT_PER_STOCK = Decimal(30)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _to_out(p: Position) -> PositionOut:
    return PositionOut(
        id=p.id,
        source=p.source.value,
        stock_code=p.stock_code,
        stock_name=p.stock_name,
        tracked_stock_id=p.tracked_stock_id,
        triggered_box_id=p.triggered_box_id,
        initial_avg_price=p.initial_avg_price,
        weighted_avg_price=p.weighted_avg_price,
        total_quantity=p.total_quantity,
        fixed_stop_price=p.fixed_stop_price,
        profit_5_executed=p.profit_5_executed,
        profit_10_executed=p.profit_10_executed,
        ts_activated=p.ts_activated,
        ts_base_price=p.ts_base_price,
        ts_stop_price=p.ts_stop_price,
        ts_active_multiplier=p.ts_active_multiplier,
        actual_capital_invested=p.actual_capital_invested,
        status=p.status.value,
        closed_at=p.closed_at,
        final_pnl=p.final_pnl,
        close_reason=p.close_reason,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


def _parse_source(raw: str | None) -> PositionSource | None:
    if raw is None:
        return None
    try:
        return PositionSource(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid source", error_code="INVALID_PARAMETER",
            details={"field": "source", "value": raw},
        ) from exc


def _parse_status(raw: str | None) -> PositionStatus | None:
    if raw is None:
        return None
    try:
        return PositionStatus(raw)
    except ValueError as exc:
        raise V71Error(
            "Invalid status", error_code="INVALID_PARAMETER",
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


def _encode_cursor(p: V71Position) -> str:
    return PaginationCursor(
        id=str(p.id), sort_value=p.created_at.isoformat()
    ).encode()


def _effective_stop(p: V71Position) -> EffectiveStopOut:
    fixed = p.fixed_stop_price
    ts = p.ts_stop_price if p.ts_activated else None
    effective = max(fixed, ts) if ts is not None else fixed
    # ``should_exit`` requires current_price -- caller may overwrite when
    # WebSocket feeds it. For REST-only consumers we leave it False.
    return EffectiveStopOut(
        fixed_stop=fixed,
        ts_stop=ts,
        effective=effective,
        should_exit=False,
    )


# ---------------------------------------------------------------------
# GET /positions  (PRD §5.1)
# ---------------------------------------------------------------------


@router.get("", status_code=status.HTTP_200_OK)
async def list_positions(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
    source: str | None = Query(default=None),
    status_q: str | None = Query(default=None, alias="status"),
    stock_code: str | None = Query(default=None, max_length=10),
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
    sort: str = Query(default="-created_at"),
) -> dict[str, Any]:
    if sort.lstrip("-") != "created_at":
        raise V71Error(
            "Unsupported sort", error_code="INVALID_PARAMETER",
            details={"field": "sort", "value": sort},
        )
    sort_desc = sort.startswith("-")

    stmt = select(V71Position)
    src_enum = _parse_source(source)
    if src_enum is not None:
        stmt = stmt.where(V71Position.source == src_enum)
    st_enum = _parse_status(status_q)
    if st_enum is not None:
        stmt = stmt.where(V71Position.status == st_enum)
    if stock_code is not None:
        stmt = stmt.where(V71Position.stock_code == stock_code)

    after_dt, after_id = _decode_cursor(cursor)
    if after_dt is not None and after_id is not None:
        if sort_desc:
            stmt = stmt.where(
                or_(
                    V71Position.created_at < after_dt,
                    (V71Position.created_at == after_dt) & (V71Position.id < after_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    V71Position.created_at > after_dt,
                    (V71Position.created_at == after_dt) & (V71Position.id > after_id),
                )
            )

    stmt = stmt.order_by(
        V71Position.created_at.desc() if sort_desc else V71Position.created_at.asc(),
        V71Position.id.desc() if sort_desc else V71Position.id.asc(),
    ).limit(limit + 1)
    rows = list((await session.execute(stmt)).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]

    data = [_to_out(p).model_dump(mode="json") for p in rows]
    next_cursor = _encode_cursor(rows[-1]) if has_more and rows else None
    meta = build_list_meta(request_id=request_id, limit=limit, next_cursor=next_cursor)
    return {"data": data, "meta": meta.model_dump()}


# ---------------------------------------------------------------------
# GET /positions/summary  (PRD §5.3)  -- must come before /{id}
# ---------------------------------------------------------------------


@router.get("/summary", status_code=status.HTTP_200_OK)
async def positions_summary(
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    rows = list(
        (
            await session.execute(
                select(Position).where(V71Position.status != PositionStatus.CLOSED)
            )
        ).scalars().all()
    )

    total_capital_invested = Decimal(0)
    by_source: dict[str, dict[str, Decimal | int]] = {
        s.value: {"count": 0, "capital": Decimal(0)} for s in PositionSource
    }
    by_status_count: dict[str, int] = {s.value: 0 for s in PositionStatus}

    pnls: list[tuple[Decimal, V71Position]] = []
    by_stock_capital: dict[str, Decimal] = {}

    for p in rows:
        total_capital_invested += p.actual_capital_invested
        bs = by_source[p.source.value]
        bs["count"] = int(bs["count"]) + 1  # type: ignore[assignment]
        bs["capital"] = Decimal(bs["capital"]) + p.actual_capital_invested  # type: ignore[arg-type]
        by_status_count[p.status.value] = by_status_count.get(p.status.value, 0) + 1
        # final_pnl unavailable until close -- use placeholder Decimal(0).
        pnls.append((p.final_pnl or Decimal(0), p))
        by_stock_capital[p.stock_code] = (
            by_stock_capital.get(p.stock_code, Decimal(0))
            + p.actual_capital_invested
        )

    total_capital_pct = (
        (total_capital_invested / _DEFAULT_TOTAL_CAPITAL * Decimal(100))
        if _DEFAULT_TOTAL_CAPITAL > 0
        else Decimal(0)
    ).quantize(Decimal("0.01"))
    total_pnl_amount = sum((x[0] for x in pnls), Decimal(0))
    total_pnl_pct = (
        (total_pnl_amount / _DEFAULT_TOTAL_CAPITAL)
        if _DEFAULT_TOTAL_CAPITAL > 0
        else Decimal(0)
    ).quantize(Decimal("0.0001"))

    pnls.sort(key=lambda t: t[0], reverse=True)
    top_pnl = [_to_out(p).model_dump(mode="json") for _, p in pnls[:5]]
    bottom_pnl = [_to_out(p).model_dump(mode="json") for _, p in pnls[-5:][::-1]]

    stocks_at_limit: list[dict[str, Any]] = []
    for code, capital in by_stock_capital.items():
        pct = (
            (capital / _DEFAULT_TOTAL_CAPITAL * Decimal(100))
            if _DEFAULT_TOTAL_CAPITAL > 0
            else Decimal(0)
        ).quantize(Decimal("0.01"))
        if pct >= _LIMIT_PCT_PER_STOCK - Decimal(5):  # within 5% of cap
            stocks_at_limit.append(
                PositionStockAtLimit(
                    stock_code=code,
                    actual_pct=pct,
                    limit_pct=_LIMIT_PCT_PER_STOCK,
                ).model_dump(mode="json")
            )

    payload = PositionSummaryOut(
        total_positions=len(rows),
        total_capital_invested=total_capital_invested,
        total_capital_pct=total_capital_pct,
        total_pnl_amount=total_pnl_amount,
        total_pnl_pct=total_pnl_pct,
        by_source={
            k: PositionSourceBreakdown(count=int(v["count"]), capital=Decimal(v["capital"]))  # type: ignore[arg-type]
            for k, v in by_source.items()
        },
        by_status=by_status_count,
        top_pnl=[PositionOut.model_validate(p) for p in top_pnl],
        bottom_pnl=[PositionOut.model_validate(p) for p in bottom_pnl],
        stocks_at_limit=[PositionStockAtLimit.model_validate(s) for s in stocks_at_limit],
    )
    return {"data": payload.model_dump(mode="json"), "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# POST /positions/reconcile (PRD §5.4) -- async stub for P5.4.6
# ---------------------------------------------------------------------


@router.post("/reconcile", status_code=status.HTTP_202_ACCEPTED)
async def reconcile(
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    task = task_registry.create(TaskType.RECONCILIATION)
    payload = ReconcileTaskOut(
        task_id=task.id,
        started_at=task.started_at or datetime.now(timezone.utc),
        estimated_seconds=30,
    ).model_dump(mode="json")
    return {"data": payload, "meta": build_meta(request_id)}


# ---------------------------------------------------------------------
# GET /positions/{id}  (PRD §5.2)
# ---------------------------------------------------------------------


@router.get("/{position_id}", status_code=status.HTTP_200_OK)
async def get_position(
    position_id: UUID,
    session: SessionDep,
    request_id: RequestIdDep,
    _user: CurrentUserDep,
) -> dict[str, Any]:
    p = await session.get(V71Position, position_id)
    if p is None:
        raise V71Error(
            "Position not found",
            error_code="POSITION_NOT_FOUND",
            status_code=status.HTTP_404_NOT_FOUND,
        )

    events_q = await session.execute(
        select(TradeEvent)
        .where(TradeEvent.position_id == p.id)
        .order_by(TradeEvent.occurred_at.asc())
    )
    events = [
        TradeEventInline(
            id=e.id,
            event_type=e.event_type.value,
            price=e.price,
            quantity=e.quantity,
            occurred_at=e.occurred_at,
        )
        for e in events_q.scalars().all()
    ]

    base = _to_out(p).model_dump(mode="json")
    base["events"] = [ev.model_dump(mode="json") for ev in events]
    base["effective_stop"] = _effective_stop(p).model_dump(mode="json")
    detail = PositionDetailOut.model_validate(base).model_dump(mode="json")
    return {"data": detail, "meta": build_meta(request_id)}
