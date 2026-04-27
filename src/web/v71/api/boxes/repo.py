"""support_boxes DB access (09_API_SPEC §4)."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models_v71 import (
    BoxStatus,
    PathType,
    V71Position,
    PositionStatus,
    StrategyType,
    SupportBox,
    TrackedStatus,
    TrackedStock,
)


# ---------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------


async def get_by_id(session: AsyncSession, box_id: UUID) -> SupportBox | None:
    return await session.get(SupportBox, box_id)


async def list_boxes(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID | None,
    path_type: PathType | None,
    status: BoxStatus | None,
    strategy_type: StrategyType | None,
    limit: int,
    sort_desc: bool,
    after_created_at: datetime | None = None,
    after_id: UUID | None = None,
) -> list[SupportBox]:
    stmt = select(SupportBox)
    if tracked_stock_id is not None:
        stmt = stmt.where(SupportBox.tracked_stock_id == tracked_stock_id)
    if path_type is not None:
        stmt = stmt.where(SupportBox.path_type == path_type)
    if status is not None:
        stmt = stmt.where(SupportBox.status == status)
    if strategy_type is not None:
        stmt = stmt.where(SupportBox.strategy_type == strategy_type)
    if after_created_at is not None and after_id is not None:
        if sort_desc:
            stmt = stmt.where(
                or_(
                    SupportBox.created_at < after_created_at,
                    (SupportBox.created_at == after_created_at)
                    & (SupportBox.id < after_id),
                )
            )
        else:
            stmt = stmt.where(
                or_(
                    SupportBox.created_at > after_created_at,
                    (SupportBox.created_at == after_created_at)
                    & (SupportBox.id > after_id),
                )
            )
    order_col = SupportBox.created_at
    stmt = stmt.order_by(
        order_col.desc() if sort_desc else order_col.asc(),
        SupportBox.id.desc() if sort_desc else SupportBox.id.asc(),
    ).limit(limit + 1)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_active_boxes_for_stock_path(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    path_type: PathType,
) -> list[SupportBox]:
    """Used by overlap detection (PRD §4.1 -- 같은 종목 + 같은 path)."""
    stmt = select(SupportBox).where(
        SupportBox.tracked_stock_id == tracked_stock_id,
        SupportBox.path_type == path_type,
        SupportBox.status.in_([BoxStatus.WAITING, BoxStatus.TRIGGERED]),
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def next_box_tier(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
) -> int:
    """Returns the next ``box_tier`` value (max + 1) for the stock."""
    stmt = select(func.coalesce(func.max(SupportBox.box_tier), 0)).where(
        SupportBox.tracked_stock_id == tracked_stock_id,
    )
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0) + 1


async def stock_capital_usage(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    total_capital: Decimal,
) -> Decimal:
    """Active position % + active box %, expressed as percentage of capital."""
    pos_q = await session.execute(
        select(func.coalesce(func.sum(V71Position.actual_capital_invested), 0)).where(
            V71Position.tracked_stock_id == tracked_stock_id,
            V71Position.status != PositionStatus.CLOSED,
        )
    )
    capital = Decimal(pos_q.scalar_one() or 0)
    pos_pct = (
        (capital / total_capital * Decimal(100)) if total_capital > 0 else Decimal(0)
    )

    box_q = await session.execute(
        select(func.coalesce(func.sum(SupportBox.position_size_pct), 0)).where(
            SupportBox.tracked_stock_id == tracked_stock_id,
            SupportBox.status == BoxStatus.WAITING,
        )
    )
    box_pct = Decimal(box_q.scalar_one() or 0)
    return (pos_pct + box_pct).quantize(Decimal("0.01"))


async def has_active_boxes_in_stock(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
) -> bool:
    stmt = select(func.count()).select_from(SupportBox).where(
        SupportBox.tracked_stock_id == tracked_stock_id,
        SupportBox.status == BoxStatus.WAITING,
    )
    res = await session.execute(stmt)
    return (res.scalar_one() or 0) > 0


async def parent_tracked_stock(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
) -> TrackedStock | None:
    return await session.get(TrackedStock, tracked_stock_id)


# ---------------------------------------------------------------------
# Mutation helpers
# ---------------------------------------------------------------------


def insert_box(
    session: AsyncSession,
    *,
    tracked_stock_id: UUID,
    path_type: PathType,
    box_tier: int,
    upper_price: Decimal,
    lower_price: Decimal,
    position_size_pct: Decimal,
    stop_loss_pct: Decimal,
    strategy_type: StrategyType,
    memo: str | None,
) -> SupportBox:
    box = SupportBox(
        tracked_stock_id=tracked_stock_id,
        path_type=path_type,
        box_tier=box_tier,
        upper_price=upper_price,
        lower_price=lower_price,
        position_size_pct=position_size_pct,
        stop_loss_pct=stop_loss_pct,
        strategy_type=strategy_type,
        status=BoxStatus.WAITING,
        memo=memo,
    )
    session.add(box)
    return box


def cancel_box(box: SupportBox, *, reason: str) -> None:
    box.status = BoxStatus.CANCELLED
    box.invalidated_at = datetime.utcnow().replace(tzinfo=__import__("datetime").timezone.utc)
    box.invalidation_reason = reason
