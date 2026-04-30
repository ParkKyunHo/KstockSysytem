"""Repository helpers for the ``positions`` + ``trade_events`` tables.

P-Wire-Box-4 split: previously the manager held an in-memory dict.
The DB-backed manager now calls into this module under explicit
transaction contexts. All functions take an open ``AsyncSession``;
transactional boundaries are the caller's responsibility (typically
V71PositionManager opens a sessionmaker context per top-level
operation, except for atomic add_position+mark_triggered which
shares the BuyExecutor outer transaction — Q3).

Spec:
  - 03_DATA_MODEL.md §2.3 (positions schema + indexes)
  - 03_DATA_MODEL.md §2.4 (trade_events schema)
  - 02_TRADING_RULES.md §6 (avg_price + events_reset)
  - 02_TRADING_RULES.md §11 (position lifecycle)
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models_v71 import (
    PositionSource,
    PositionStatus,
    TradeEventType,
    V71Position,
)
from src.database.models_v71 import (
    TradeEvent as TradeEventORM,
)

if TYPE_CHECKING:
    pass


def _as_uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        return value
    return UUID(value)


def _opt_uuid(value: str | UUID | None) -> UUID | None:
    if value is None or value == "":
        return None
    if isinstance(value, UUID):
        return value
    return UUID(value)


# ---------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------


async def fetch_position(
    session: AsyncSession,
    position_id: str | UUID,
    *,
    for_update: bool = False,
) -> V71Position | None:
    """Return the row or ``None``. ``for_update`` adds ``SELECT ... FOR UPDATE``."""
    stmt = select(V71Position).where(V71Position.id == _as_uuid(position_id))
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def fetch_active_for_stock(
    session: AsyncSession,
    stock_code: str,
    *,
    for_update: bool = False,
) -> list[V71Position]:
    """Active (non-CLOSED) positions for a stock. Hot path for Reconciler
    Scenario B (이중 경로 비례 차감) — ``for_update=True`` locks the
    full set so allocation is race-free."""
    stmt = select(V71Position).where(
        V71Position.stock_code == stock_code,
        V71Position.status != PositionStatus.CLOSED,
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def fetch_active_for_stock_path(
    session: AsyncSession,
    stock_code: str,
    path_type: str,
) -> V71Position | None:
    """Active position for a (stock, path) pair. PRD §11 invariant:
    at most one active position per (stock, path) — caller can rely on
    scalar_one_or_none()."""
    try:
        source = PositionSource(path_type)
    except ValueError:
        return None
    stmt = select(V71Position).where(
        V71Position.stock_code == stock_code,
        V71Position.source == source,
        V71Position.status != PositionStatus.CLOSED,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_open(
    session: AsyncSession, *, limit: int = 1000,
) -> list[V71Position]:
    """All non-CLOSED positions. Default ``limit=1000`` (security M4)."""
    stmt = (
        select(V71Position)
        .where(V71Position.status != PositionStatus.CLOSED)
        .order_by(V71Position.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_for_stock(
    session: AsyncSession,
    stock_code: str,
    *,
    include_closed: bool = False,
    limit: int = 1000,
) -> list[V71Position]:
    stmt = select(V71Position).where(V71Position.stock_code == stock_code)
    if not include_closed:
        stmt = stmt.where(V71Position.status != PositionStatus.CLOSED)
    stmt = stmt.order_by(V71Position.created_at.desc()).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------
# trade_events queries
# ---------------------------------------------------------------------


async def list_events_for_position(
    session: AsyncSession, position_id: str | UUID,
) -> list[TradeEventORM]:
    stmt = (
        select(TradeEventORM)
        .where(TradeEventORM.position_id == _as_uuid(position_id))
        .order_by(TradeEventORM.occurred_at.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def list_events_since(
    session: AsyncSession,
    *,
    since: datetime,
    limit: int = 1000,
) -> list[TradeEventORM]:
    """trade_events emitted on or after ``since`` (Telegram /today,
    /recent, DailySummary). ``since`` must be tz-aware (TIMESTAMPTZ
    column)."""
    if since.tzinfo is None:
        raise ValueError(
            "list_events_since: since must be tz-aware "
            "(PRD §2.4 columns are TIMESTAMPTZ)"
        )
    stmt = (
        select(TradeEventORM)
        .where(TradeEventORM.occurred_at >= since)
        .order_by(TradeEventORM.occurred_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ---------------------------------------------------------------------
# Mutation helpers (caller manages session.commit)
# ---------------------------------------------------------------------


def insert_position(
    session: AsyncSession,
    *,
    stock_code: str,
    stock_name: str,
    tracked_stock_id: str | UUID | None,
    triggered_box_id: str | UUID | None,
    source: PositionSource,
    weighted_avg_price: int,
    total_quantity: int,
    fixed_stop_price: int,
    actual_capital_invested: int,
    status: PositionStatus = PositionStatus.OPEN,
) -> V71Position:
    """Build + add a V71Position row (caller flushes / commits)."""
    pos_id = uuid4()
    orm = V71Position(
        id=pos_id,
        source=source,
        stock_code=stock_code,
        stock_name=stock_name,
        tracked_stock_id=_opt_uuid(tracked_stock_id),
        triggered_box_id=_opt_uuid(triggered_box_id),
        initial_avg_price=Decimal(weighted_avg_price),
        weighted_avg_price=Decimal(weighted_avg_price),
        total_quantity=int(total_quantity),
        fixed_stop_price=Decimal(fixed_stop_price),
        actual_capital_invested=Decimal(actual_capital_invested),
        status=status,
    )
    session.add(orm)
    return orm


def insert_event(
    session: AsyncSession,
    *,
    event_type: TradeEventType,
    position_id: str | UUID,
    stock_code: str,
    quantity: int,
    price: int,
    occurred_at: datetime,
    events_reset: bool = False,
    avg_price_before: int | None = None,
    avg_price_after: int | None = None,
) -> TradeEventORM:
    """Build + add a TradeEvent row in the same session (Q4 — same-tx
    INSERT). Caller flushes / commits.

    The ORM has no dedicated ``events_reset`` column; the flag is
    persisted in ``payload`` (JSONB) so the audit trail keeps the
    §6.2 events-reset signal alongside avg_price_before / after.
    """
    payload = {"events_reset": bool(events_reset)} if events_reset else None
    evt = TradeEventORM(
        id=uuid4(),
        event_type=event_type,
        position_id=_as_uuid(position_id),
        stock_code=stock_code,
        quantity=int(quantity),
        price=Decimal(price) if price else None,
        occurred_at=occurred_at,
        avg_price_before=Decimal(avg_price_before) if avg_price_before is not None else None,
        avg_price_after=Decimal(avg_price_after) if avg_price_after is not None else None,
        payload=payload,
    )
    session.add(evt)
    return evt


__all__ = [
    "fetch_position",
    "fetch_active_for_stock",
    "fetch_active_for_stock_path",
    "list_open",
    "list_for_stock",
    "list_events_for_position",
    "list_events_since",
    "insert_position",
    "insert_event",
]
