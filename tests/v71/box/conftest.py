"""Fixtures for V71BoxManager DB-backed tests (P-Wire-Box-1).

Strategy:
  - sqlite + aiosqlite for fast unit coverage (tests/v71/exchange/* mirror).
  - V7.1 ORM (``Base.metadata``) creates the schema on every fixture so
    each test starts from a clean DB.
  - One ``async_sessionmaker`` per test session, injected into the
    manager. Tests that exercise the manager's internal transactions
    let the manager open its own; tests that exercise the optional
    ``session=`` injection drive the session themselves.
  - Time is fixed at KST 2026-05-15 09:00 (chosen because architect
    Q5 picked it for the 30-day reminder boundary tests).

NOTE: SQLite does not honour ``SELECT ... FOR UPDATE`` or partial
indexes the same way Postgres does. Race + index-strategy tests live
in ``tests/v71/box/db/`` (postgres mark) and are out of scope for the
P-Wire-Box-1 fast-unit suite.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID, uuid4

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
    StrategyType,
    SupportBox,
    TrackedStatus,
    TrackedStock,
)

KST = timezone(timedelta(hours=9))
UTC = timezone.utc
FIXED_NOW_KST = datetime(2026, 5, 15, 9, 0, 0, tzinfo=KST)


@pytest_asyncio.fixture
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True,
    )
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


@pytest.fixture
def fixed_clock() -> Callable[[], datetime]:
    state = {"now": FIXED_NOW_KST}

    def _now() -> datetime:
        return state["now"]

    return _now


@pytest.fixture
def make_box_manager(session_factory, fixed_clock):
    """V71BoxManager builder. ``v71.box_system`` flag must be on at
    test time (set by autouse fixture below)."""
    from src.core.v71.box.box_manager import V71BoxManager

    def _build(*, clock=None):
        return V71BoxManager(
            session_factory=session_factory,
            clock=clock or fixed_clock,
        )

    return _build


@pytest.fixture(autouse=True)
def enable_box_flag(monkeypatch):
    """``V71BoxManager.__init__`` requires ``v71.box_system`` true."""
    monkeypatch.setenv("V71_FF__V71__BOX_SYSTEM", "true")
    # Reload feature_flags module cache so the env override applies.
    from src.utils import feature_flags
    feature_flags.reload()
    yield
    feature_flags.reload()


@pytest_asyncio.fixture
async def seeded_tracked(session_factory) -> AsyncIterator[TrackedStock]:
    """One TRACKING-status tracked_stocks row, ready for box creation."""
    async with session_factory() as session, session.begin():
        ts = TrackedStock(
            id=uuid4(),
            stock_code="005930",
            stock_name="삼성전자",
            status=TrackedStatus.TRACKING,
        )
        session.add(ts)
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(TrackedStock).where(TrackedStock.stock_code == "005930")
        )
        yield result.scalar_one()


async def _seed_box(
    session_factory,
    *,
    tracked_id: UUID,
    upper: int = 71000,
    lower: int = 70000,
    status: BoxStatus = BoxStatus.WAITING,
    path_type: PathType = PathType.PATH_A,
    box_tier: int = 1,
    strategy_type: StrategyType = StrategyType.PULLBACK,
    created_at: datetime | None = None,
    last_reminder_at: datetime | None = None,
) -> SupportBox:
    box_id = uuid4()
    async with session_factory() as session, session.begin():
        row = SupportBox(
            id=box_id,
            tracked_stock_id=tracked_id,
            path_type=path_type,
            box_tier=box_tier,
            upper_price=Decimal(upper),
            lower_price=Decimal(lower),
            position_size_pct=Decimal("10.00"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=strategy_type,
            status=status,
            created_at=created_at,
            last_reminder_at=last_reminder_at,
        )
        session.add(row)
    async with session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(SupportBox).where(SupportBox.id == box_id)
        )
        return result.scalar_one()


# Helper exposed via fixture so tests do not import _seed_box directly.
@pytest.fixture
def seed_box(session_factory):
    async def _impl(**kwargs):
        return await _seed_box(session_factory, **kwargs)
    return _impl
