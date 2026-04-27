"""tracked_stocks DB access (09_API_SPEC §3)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.database.models_v71 import (
    PathType,
    V71Position,
    PositionStatus,
    Stock,
    SupportBox,
    BoxStatus,
    TrackedStatus,
    TrackedStock,
)


# ---------------------------------------------------------------------
# Query helpers
# ---------------------------------------------------------------------


async def list_tracked(
    session: AsyncSession,
    *,
    status: TrackedStatus | None,
    stock_code: str | None,
    q: str | None,
    limit: int,
    sort_desc: bool,
    after_created_at: datetime | None = None,
    after_id: UUID | None = None,
) -> list[TrackedStock]:
    stmt = select(TrackedStock)
    if status is not None:
        stmt = stmt.where(TrackedStock.status == status)
    if stock_code is not None:
        stmt = stmt.where(TrackedStock.stock_code == stock_code)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                TrackedStock.stock_name.ilike(like),
                TrackedStock.stock_code.ilike(like),
            )
        )
    if after_created_at is not None and after_id is not None:
        if sort_desc:
            stmt = stmt.where(
                or_(
                    TrackedStock.created_at < after_created_at,
                    (TrackedStock.created_at == after_created_at)
                    & (TrackedStock.id < after_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    TrackedStock.created_at > after_created_at,
                    (TrackedStock.created_at == after_created_at)
                    & (TrackedStock.id > after_id),
                )
            )

    order_col = TrackedStock.created_at
    stmt = stmt.order_by(
        order_col.desc() if sort_desc else order_col.asc(),
        TrackedStock.id.desc() if sort_desc else TrackedStock.id.asc(),
    ).limit(limit + 1)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_by_id(session: AsyncSession, ts_id: UUID) -> TrackedStock | None:
    return await session.get(
        TrackedStock,
        ts_id,
        options=[
            selectinload(TrackedStock.boxes),
            selectinload(TrackedStock.positions),
        ],
    )


async def get_active_by_code(
    session: AsyncSession, stock_code: str,
) -> TrackedStock | None:
    """PRD §3.2: active tracking is unique per stock_code (Patch #3)."""
    result = await session.execute(
        select(TrackedStock).where(
            TrackedStock.stock_code == stock_code,
            TrackedStock.status != TrackedStatus.EXITED,
        )
    )
    return result.scalars().first()


async def get_stock_master(
    session: AsyncSession, stock_code: str,
) -> Stock | None:
    return await session.get(Stock, stock_code)


async def search_stocks(
    session: AsyncSession, q: str, limit: int = 8,
) -> list[Stock]:
    like = f"%{q}%"
    stmt = (
        select(Stock)
        .where(
            or_(
                Stock.code.ilike(like),
                Stock.name.ilike(like),
                Stock.name_normalized.ilike(like),
            )
        )
        .order_by(Stock.code)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------
# Summary calculation (09_API_SPEC §3.1 Patch #3)
# ---------------------------------------------------------------------


async def build_summary(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    total_capital: Decimal | None,
) -> dict[str, Any]:
    """Aggregate boxes + positions for a single tracked_stock row."""
    box_rows = await session.execute(
        select(
            SupportBox.path_type,
            SupportBox.status,
            func.count(SupportBox.id),
            func.coalesce(func.sum(SupportBox.position_size_pct), 0),
        )
        .where(SupportBox.tracked_stock_id == tracked_stock_id)
        .group_by(SupportBox.path_type, SupportBox.status)
    )

    active_box_count = 0
    triggered_box_count = 0
    path_a = 0
    path_b = 0
    waiting_pct_total = Decimal(0)
    for path, status, count, size_sum in box_rows:
        if status == BoxStatus.WAITING:
            active_box_count += count
            waiting_pct_total += Decimal(size_sum or 0)
            if path == PathType.PATH_A:
                path_a += count
            elif path == PathType.PATH_B:
                path_b += count
        if status == BoxStatus.TRIGGERED:
            triggered_box_count += count

    pos_rows = await session.execute(
        select(
            func.coalesce(func.sum(V71Position.total_quantity), 0),
            func.coalesce(func.sum(V71Position.actual_capital_invested), 0),
            func.coalesce(
                func.sum(V71Position.weighted_avg_price * V71Position.total_quantity),
                0,
            ),
        ).where(
            V71Position.tracked_stock_id == tracked_stock_id,
            V71Position.status != PositionStatus.CLOSED,
        )
    )
    qty_sum, capital_sum, value_sum = pos_rows.one()
    qty_sum = int(qty_sum or 0)
    capital_sum = Decimal(capital_sum or 0)
    avg_price: Decimal | None = None
    if qty_sum > 0:
        avg_price = (Decimal(value_sum or 0) / Decimal(qty_sum)).quantize(
            Decimal("1")
        )

    if total_capital and total_capital > 0:
        positions_pct = (capital_sum / total_capital * Decimal(100)).quantize(
            Decimal("0.01")
        )
    else:
        positions_pct = Decimal(0)

    total_position_pct = (waiting_pct_total + positions_pct).quantize(
        Decimal("0.01")
    )

    return {
        "active_box_count": active_box_count,
        "path_a_box_count": path_a,
        "path_b_box_count": path_b,
        "triggered_box_count": triggered_box_count,
        "current_position_qty": qty_sum,
        "current_position_avg_price": avg_price,
        "total_position_pct": total_position_pct,
    }


# ---------------------------------------------------------------------
# Mutations
# ---------------------------------------------------------------------


def insert_new(
    session: AsyncSession,
    *,
    stock_code: str,
    stock_name: str,
    market: str | None,
    user_memo: str | None,
    source: str | None,
) -> TrackedStock:
    obj = TrackedStock(
        stock_code=stock_code,
        stock_name=stock_name,
        market=market,
        status=TrackedStatus.TRACKING,
        user_memo=user_memo,
        source=source,
    )
    session.add(obj)
    return obj


def has_active_position(positions: list[V71Position]) -> tuple[int, int]:
    """Returns ``(count, total_quantity)`` for non-CLOSED positions."""
    count = 0
    total_qty = 0
    for p in positions:
        if p.status != PositionStatus.CLOSED:
            count += 1
            total_qty += p.total_quantity
    return count, total_qty


def mark_exited(ts: TrackedStock, *, reason: str | None = None) -> None:
    ts.status = TrackedStatus.EXITED
    ts.last_status_changed_at = datetime.now(timezone.utc)
    if reason is not None:
        ts.auto_exit_reason = reason
        ts.auto_exit_at = datetime.now(timezone.utc)
