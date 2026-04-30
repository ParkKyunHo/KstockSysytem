"""P-Wire-Box-3 build_tracked_summaries integration tests.

Replaces the pre-P-Wire-Box-3 stub `_list_tracked() -> []` with a DB
JOIN — so /tracking and DailySummary actually report what is in the
DB. Tests cover the user-reported regression directly: a stock that
was registered + has a WAITING box must show up under /tracking.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.database.models import Base
from src.database.models_v71 import (
    BoxStatus,
    PathType,
    PositionSource,
    PositionStatus,
    StrategyType,
    SupportBox,
    TrackedStatus,
    TrackedStock,
    V71Position,
)
from src.web.v71.tracked_summary import build_tracked_summaries

UTC = timezone.utc


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(sqlite_engine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False,
    )


async def _seed_tracked(
    session_factory, *, stock_code: str, status: TrackedStatus,
):
    async with session_factory() as s, s.begin():
        ts = TrackedStock(
            id=uuid4(),
            stock_code=stock_code,
            stock_name=f"종목{stock_code}",
            status=status,
        )
        s.add(ts)
        await s.flush()
        ts_id = ts.id
    return ts_id


async def _seed_box(
    session_factory, *, tracked_id, path_type: PathType, status: BoxStatus,
):
    async with session_factory() as s, s.begin():
        s.add(SupportBox(
            id=uuid4(),
            tracked_stock_id=tracked_id,
            path_type=path_type,
            box_tier=1,
            upper_price=Decimal("71000"),
            lower_price=Decimal("70000"),
            position_size_pct=Decimal("10"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=StrategyType.PULLBACK,
            status=status,
        ))


async def _seed_position(
    session_factory, *, tracked_id, source: PositionSource = PositionSource.SYSTEM_A,
    status: PositionStatus = PositionStatus.OPEN,
):
    async with session_factory() as s, s.begin():
        s.add(V71Position(
            id=uuid4(),
            source=source,
            stock_code="005930",
            stock_name="삼성전자",
            tracked_stock_id=tracked_id,
            initial_avg_price=Decimal("70000"),
            weighted_avg_price=Decimal("70000"),
            total_quantity=10,
            fixed_stop_price=Decimal("66500"),
            actual_capital_invested=Decimal("700000"),
            status=status,
        ))


@pytest.mark.asyncio
async def test_empty_db_returns_empty(session_factory):
    summaries = await build_tracked_summaries(session_factory)
    assert summaries == []


@pytest.mark.asyncio
async def test_tracked_stock_with_path_a_box_emits_one_row(session_factory):
    """User-reported regression direct check."""
    tid = await _seed_tracked(
        session_factory, stock_code="005930", status=TrackedStatus.BOX_SET,
    )
    await _seed_box(
        session_factory, tracked_id=tid, path_type=PathType.PATH_A,
        status=BoxStatus.WAITING,
    )

    summaries = await build_tracked_summaries(session_factory)
    assert len(summaries) == 1
    assert summaries[0].stock_code == "005930"
    assert summaries[0].path_type == "PATH_A"
    assert summaries[0].box_count == 1
    assert summaries[0].has_position is False


@pytest.mark.asyncio
async def test_dual_path_emits_two_rows(session_factory):
    tid = await _seed_tracked(
        session_factory, stock_code="000660", status=TrackedStatus.BOX_SET,
    )
    await _seed_box(
        session_factory, tracked_id=tid, path_type=PathType.PATH_A,
        status=BoxStatus.WAITING,
    )
    await _seed_box(
        session_factory, tracked_id=tid, path_type=PathType.PATH_B,
        status=BoxStatus.WAITING,
    )

    summaries = await build_tracked_summaries(session_factory)
    assert len(summaries) == 2
    paths = {s.path_type for s in summaries}
    assert paths == {"PATH_A", "PATH_B"}


@pytest.mark.asyncio
async def test_exited_tracked_excluded(session_factory):
    tid = await _seed_tracked(
        session_factory, stock_code="005935", status=TrackedStatus.EXITED,
    )
    await _seed_box(
        session_factory, tracked_id=tid, path_type=PathType.PATH_A,
        status=BoxStatus.WAITING,
    )

    summaries = await build_tracked_summaries(session_factory)
    assert summaries == []


@pytest.mark.asyncio
async def test_position_without_active_boxes_emits_manual_row(session_factory):
    tid = await _seed_tracked(
        session_factory, stock_code="005380", status=TrackedStatus.POSITION_OPEN,
    )
    await _seed_position(
        session_factory, tracked_id=tid, source=PositionSource.MANUAL,
    )

    summaries = await build_tracked_summaries(session_factory)
    assert len(summaries) == 1
    assert summaries[0].path_type == "MANUAL"
    assert summaries[0].has_position is True


@pytest.mark.asyncio
async def test_invalidated_box_excluded_from_count(session_factory):
    tid = await _seed_tracked(
        session_factory, stock_code="005930", status=TrackedStatus.BOX_SET,
    )
    await _seed_box(
        session_factory, tracked_id=tid, path_type=PathType.PATH_A,
        status=BoxStatus.WAITING,
    )
    await _seed_box(
        session_factory, tracked_id=tid, path_type=PathType.PATH_A,
        status=BoxStatus.INVALIDATED,
    )

    summaries = await build_tracked_summaries(session_factory)
    assert len(summaries) == 1
    assert summaries[0].box_count == 1  # only WAITING


_ = (datetime,)
