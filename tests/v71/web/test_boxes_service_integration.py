"""P-Wire-Box-2 web/service ↔ V71BoxManager integration tests.

Why these tests live here (not under ``tests/v71/box/``):
    The DB-backed manager is already covered by the unit suite at
    ``tests/v71/box/test_box_manager.py``. This file verifies the *web
    service* layer — that ``service.create_box / patch_box / delete_box``
    actually goes through the manager (not the legacy ``repo.insert_box``
    direct call), so a row written by the web is immediately visible to
    the trading engine through the same manager. That visibility is the
    user-reported regression P-Wire-Box-2 closes.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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
from src.web.v71.api.boxes import service
from src.web.v71.exceptions import BusinessRuleError, ConflictError

UTC = timezone.utc
DEFAULT_TOTAL_CAPITAL = Decimal("100000000")
USER_ID = uuid4()


@pytest.fixture(autouse=True)
def _enable_box_flag(monkeypatch):
    monkeypatch.setenv("V71_FF__V71__BOX_SYSTEM", "true")
    from src.utils import feature_flags
    feature_flags.reload()
    yield
    feature_flags.reload()


@pytest.fixture(autouse=True)
def _stub_audit(monkeypatch):
    """``record_audit`` opens its own session via the global DB manager,
    which is not configured in unit tests. Stub it to a no-op so the
    create/patch/delete paths do not blow up after commit."""
    async def _noop(**_kwargs):
        return None

    monkeypatch.setattr(service, "record_audit", _noop)
    yield


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


@pytest_asyncio.fixture
async def box_manager(session_factory):
    from src.core.v71.box.box_manager import V71BoxManager
    return V71BoxManager(session_factory=session_factory)


@pytest_asyncio.fixture
async def session(session_factory) -> AsyncIterator[AsyncSession]:
    async with session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def seeded_tracked(session_factory) -> TrackedStock:
    async with session_factory() as s, s.begin():
        ts = TrackedStock(
            id=uuid4(),
            stock_code="005930",
            stock_name="삼성전자",
            status=TrackedStatus.TRACKING,
        )
        s.add(ts)
    async with session_factory() as s:
        from sqlalchemy import select
        return (
            await s.execute(
                select(TrackedStock).where(TrackedStock.stock_code == "005930"),
            )
        ).scalar_one()


# ============================================================
# Group 1: create_box happy path + manager visibility
# ============================================================


class TestCreateBoxIntegration:
    @pytest.mark.asyncio
    async def test_box_visible_via_manager_after_service_create(
        self, session, box_manager, seeded_tracked,
    ):
        """User-reported regression direct check: a box created by the
        web service must be visible through the same manager the
        trading engine reads from."""
        await service.create_box(
            session,
            box_manager=box_manager,
            tracked_stock_id=seeded_tracked.id,
            path_type=PathType.PATH_A,
            upper_price=Decimal("71000"),
            lower_price=Decimal("70000"),
            position_size_pct=Decimal("10"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=StrategyType.PULLBACK,
            memo="첫 박스",
            user_id=USER_ID,
            total_capital=DEFAULT_TOTAL_CAPITAL,
            ip_address=None,
            user_agent=None,
        )

        # Same manager instance the trading engine uses.
        records = await box_manager.list_all()
        assert len(records) == 1
        assert records[0].path_type == PathType.PATH_A
        assert records[0].upper_price == 71000
        assert records[0].lower_price == 70000

    @pytest.mark.asyncio
    async def test_tracked_stock_transitions_to_box_set(
        self, session, box_manager, seeded_tracked, session_factory,
    ):
        """PRD §4.1 — first box on a TRACKING stock flips it to BOX_SET."""
        await service.create_box(
            session,
            box_manager=box_manager,
            tracked_stock_id=seeded_tracked.id,
            path_type=PathType.PATH_A,
            upper_price=Decimal("71000"),
            lower_price=Decimal("70000"),
            position_size_pct=Decimal("10"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=StrategyType.PULLBACK,
            memo=None,
            user_id=USER_ID,
            total_capital=DEFAULT_TOTAL_CAPITAL,
            ip_address=None,
            user_agent=None,
        )
        # Re-fetch in a fresh session so we see the committed state.
        async with session_factory() as s2:
            ts = await s2.get(TrackedStock, seeded_tracked.id)
            assert ts is not None
            assert ts.status == TrackedStatus.BOX_SET


# ============================================================
# Group 2: 30% per-stock cap (PRD §4.1)
# ============================================================


class TestCapEnforcement:
    @pytest.mark.asyncio
    async def test_create_box_30pct_cap_blocks(
        self, session, box_manager, seeded_tracked, session_factory,
    ):
        # Pre-seed a 25% box so that adding 10% pushes us over 30%.
        async with session_factory() as s, s.begin():
            s.add(SupportBox(
                id=uuid4(),
                tracked_stock_id=seeded_tracked.id,
                path_type=PathType.PATH_A,
                box_tier=1,
                upper_price=Decimal("60000"),
                lower_price=Decimal("59000"),
                position_size_pct=Decimal("25"),
                stop_loss_pct=Decimal("-0.05"),
                strategy_type=StrategyType.PULLBACK,
                status=BoxStatus.WAITING,
            ))

        with pytest.raises(BusinessRuleError, match="30%"):
            await service.create_box(
                session,
                box_manager=box_manager,
                tracked_stock_id=seeded_tracked.id,
                path_type=PathType.PATH_A,
                upper_price=Decimal("71000"),
                lower_price=Decimal("70000"),
                position_size_pct=Decimal("10"),
                stop_loss_pct=Decimal("-0.05"),
                strategy_type=StrategyType.PULLBACK,
                memo=None,
                user_id=USER_ID,
                total_capital=DEFAULT_TOTAL_CAPITAL,
                ip_address=None,
                user_agent=None,
            )


# ============================================================
# Group 3: overlap (delegated to V71BoxManager) — service translates
# ============================================================


class TestOverlapTranslation:
    @pytest.mark.asyncio
    async def test_overlap_returns_conflict_error(
        self, session, box_manager, seeded_tracked,
    ):
        await service.create_box(
            session,
            box_manager=box_manager,
            tracked_stock_id=seeded_tracked.id,
            path_type=PathType.PATH_A,
            upper_price=Decimal("71000"),
            lower_price=Decimal("70000"),
            position_size_pct=Decimal("10"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=StrategyType.PULLBACK,
            memo=None,
            user_id=USER_ID,
            total_capital=DEFAULT_TOTAL_CAPITAL,
            ip_address=None,
            user_agent=None,
        )

        with pytest.raises(ConflictError):
            await service.create_box(
                session,
                box_manager=box_manager,
                tracked_stock_id=seeded_tracked.id,
                path_type=PathType.PATH_A,
                upper_price=Decimal("70500"),
                lower_price=Decimal("69500"),  # overlaps
                position_size_pct=Decimal("5"),
                stop_loss_pct=Decimal("-0.05"),
                strategy_type=StrategyType.PULLBACK,
                memo=None,
                user_id=USER_ID,
                total_capital=DEFAULT_TOTAL_CAPITAL,
                ip_address=None,
                user_agent=None,
            )


# ============================================================
# Group 4: delete_box reverts tracked_stock to TRACKING
# ============================================================


class TestDeleteFlow:
    @pytest.mark.asyncio
    async def test_delete_last_box_returns_to_tracking(
        self, session, box_manager, seeded_tracked, session_factory,
    ):
        await service.create_box(
            session,
            box_manager=box_manager,
            tracked_stock_id=seeded_tracked.id,
            path_type=PathType.PATH_A,
            upper_price=Decimal("71000"),
            lower_price=Decimal("70000"),
            position_size_pct=Decimal("10"),
            stop_loss_pct=Decimal("-0.05"),
            strategy_type=StrategyType.PULLBACK,
            memo=None,
            user_id=USER_ID,
            total_capital=DEFAULT_TOTAL_CAPITAL,
            ip_address=None,
            user_agent=None,
        )
        records = await box_manager.list_all()
        assert len(records) == 1
        box_id = UUID(records[0].id)

        await service.delete_box(
            session,
            box_manager=box_manager,
            box_id=box_id,
            user_id=USER_ID,
            ip_address=None,
            user_agent=None,
        )

        async with session_factory() as s2:
            ts = await s2.get(TrackedStock, seeded_tracked.id)
            assert ts is not None
            assert ts.status == TrackedStatus.TRACKING


# Mark intentional unused imports.
_ = (datetime, timedelta)
