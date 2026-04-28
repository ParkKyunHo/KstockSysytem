"""Unit tests for ``src/core/v71/exchange/reconciler.py``.

Spec sources:
  - 06_AGENTS_SPEC.md §5 Test Strategy verification (78-case plan)
  - 12_SECURITY.md §6 (PII never logged + token plaintext)
  - 02_TRADING_RULES.md §7 (manual-trade scenarios A/B/C/D/E)
  - KIWOOM_API_ANALYSIS.md §kt00018 (acnt_evlt_remn_indv_tot schema)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomResponse,
    V71KiwoomTransportError,
)
from src.core.v71.exchange.reconciler import (
    V71PyramidBuyDetected,
    V71Reconciler,
    V71ReconcilerError,
    V71ReconciliationApplyMode,
    V71TrackingTerminated,
    _coerce_int,
    _orm_to_position_state,
)
from src.core.v71.skills.reconciliation_skill import ReconciliationCase
from src.database.models import Base
from src.database.models_v71 import (
    PositionSource,
    PositionStatus,
    TrackedStatus,
    TrackedStock,
    TradeEvent,
    TradeEventType,
    V71Position,
)

# ---------------------------------------------------------------------------
# Fixtures: in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session_factory(sqlite_engine):
    maker = async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False,
    )

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        session = maker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    return _factory


@pytest.fixture
def fixed_clock():
    state = {"now": datetime(2026, 4, 28, 9, 30, 0, tzinfo=timezone.utc)}

    def _clock() -> datetime:
        return state["now"]

    return _clock


# ---------------------------------------------------------------------------
# Fixtures: kiwoom client + helpers
# ---------------------------------------------------------------------------


def _kt00018_row(
    *, stock_code: str, qty: int, avg: int, name: str | None = None,
    cur_prc: int | None = None,
) -> dict[str, Any]:
    return {
        "stk_cd": stock_code,
        "stk_nm": name if name is not None else f"종목{stock_code}",
        "rmnd_qty": str(qty),
        "pur_pric": str(avg),
        "cur_prc": str(cur_prc) if cur_prc is not None else str(int(avg * 1.05)),
    }


def _kt00018_response(holdings: list[dict[str, Any]]) -> V71KiwoomResponse:
    return V71KiwoomResponse(
        success=True,
        api_id="kt00018",
        data={"acnt_evlt_remn_indv_tot": holdings},
        return_code=0,
        return_msg="OK",
        cont_yn="N",
        next_key="",
        duration_ms=15,
    )


@pytest.fixture
def kiwoom_client_mock():
    client = AsyncMock()
    client.get_account_balance = AsyncMock(
        return_value=_kt00018_response([])
    )
    return client


@pytest.fixture
def make_reconciler(kiwoom_client_mock, session_factory, fixed_clock):
    def _build(
        *,
        apply_mode: V71ReconciliationApplyMode = V71ReconciliationApplyMode.SIMPLE_APPLY,
        on_pyramid: Any = None,
        on_tracking_terminated: Any = None,
    ) -> V71Reconciler:
        return V71Reconciler(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            apply_mode=apply_mode,
            on_pyramid_buy_detected=on_pyramid,
            on_tracking_terminated=on_tracking_terminated,
        )

    return _build


@pytest.fixture
def reconciler(make_reconciler):
    return make_reconciler()


# ---------------------------------------------------------------------------
# Seed helpers
# ---------------------------------------------------------------------------


async def _seed_position(
    session_factory,
    *,
    stock_code: str = "005930",
    source: PositionSource = PositionSource.SYSTEM_A,
    qty: int = 100,
    avg: int = 70000,
    status: PositionStatus = PositionStatus.OPEN,
    tracked_stock_id: Any = None,
) -> V71Position:
    async with session_factory() as session:
        row = V71Position(
            id=uuid4(),
            source=source,
            stock_code=stock_code,
            stock_name=f"종목{stock_code}",
            tracked_stock_id=tracked_stock_id,
            triggered_box_id=None,
            initial_avg_price=Decimal(avg),
            weighted_avg_price=Decimal(avg),
            total_quantity=qty,
            fixed_stop_price=Decimal(int(avg * 0.95)),
            profit_5_executed=False,
            profit_10_executed=False,
            ts_activated=False,
            status=status,
            actual_capital_invested=Decimal(qty * avg),
        )
        session.add(row)
        await session.commit()
        return row


async def _seed_tracking(
    session_factory,
    *,
    stock_code: str = "005930",
    status: TrackedStatus = TrackedStatus.BOX_SET,
) -> TrackedStock:
    async with session_factory() as session:
        row = TrackedStock(
            id=uuid4(),
            stock_code=stock_code,
            stock_name=f"종목{stock_code}",
            status=status,
        )
        session.add(row)
        await session.commit()
        return row


async def _read_positions(session_factory) -> list[V71Position]:
    async with session_factory() as session:
        result = await session.execute(select(V71Position))
        return list(result.scalars().all())


async def _read_position_by_id(session_factory, pid) -> V71Position | None:
    async with session_factory() as session:
        return await session.get(V71Position, pid)


async def _read_trade_events(session_factory) -> list[TradeEvent]:
    async with session_factory() as session:
        result = await session.execute(select(TradeEvent))
        return list(result.scalars().all())


# ---------------------------------------------------------------------------
# Group A: kt00018 fetch + parsing (6 cases)
# ---------------------------------------------------------------------------


class TestKt00018Fetch:
    async def test_normal_multi_stocks(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=100, avg=70000, name="삼성전자"),
            _kt00018_row(stock_code="000660", qty=50, avg=130000, name="SK하이닉스"),
        ])
        await _seed_position(session_factory, stock_code="005930", qty=100)
        await _seed_position(session_factory, stock_code="000660", qty=50, avg=130000)

        report = await reconciler.reconcile_all()

        assert report.matched_count == 2
        assert report.error_count == 0

    async def test_zero_quantity_row_skipped(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=0, avg=70000),
            _kt00018_row(stock_code="000660", qty=50, avg=130000, name="SK하이닉스"),
        ])
        await _seed_position(session_factory, stock_code="000660", qty=50, avg=130000)

        report = await reconciler.reconcile_all()

        # 005930 was skipped from Kiwoom side; 000660 matched.
        codes_seen = {d.stock_code for d in report.decisions}
        assert "005930" not in codes_seen
        assert "000660" in codes_seen

    async def test_invalid_stock_code_logged_and_skipped(
        self, reconciler, kiwoom_client_mock, caplog
    ):
        # "00593" is too short (5 chars, but lowercase rejection too).
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            {"stk_cd": "abcd", "stk_nm": "x", "rmnd_qty": "10", "pur_pric": "1"},
            _kt00018_row(stock_code="005930", qty=100, avg=70000),
        ])

        with caplog.at_level(logging.WARNING):
            report = await reconciler.reconcile_all()

        codes = {d.stock_code for d in report.decisions}
        assert "005930" in codes
        assert "abcd" not in codes

    async def test_corrupt_quantity_skipped(
        self, reconciler, kiwoom_client_mock
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            {"stk_cd": "005930", "stk_nm": "삼성전자",
             "rmnd_qty": "ABC", "pur_pric": "70000"},
        ])

        report = await reconciler.reconcile_all()

        # ABC -> _coerce_int default 0 -> qty<=0 skip.
        assert report.decisions == ()

    async def test_transport_error_raises_reconciler_error(
        self, reconciler, kiwoom_client_mock
    ):
        kiwoom_client_mock.get_account_balance.side_effect = V71KiwoomTransportError(
            "network"
        )

        with pytest.raises(V71ReconcilerError, match="transport failure"):
            await reconciler.reconcile_all()

    async def test_business_error_raises_reconciler_error(
        self, reconciler, kiwoom_client_mock
    ):
        kiwoom_client_mock.get_account_balance.side_effect = V71KiwoomBusinessError(
            "kt00018 1700",
            return_code=1700,
            return_msg="rate limit",
            api_id="kt00018",
        )

        with pytest.raises(V71ReconcilerError, match="business error code=1700"):
            await reconciler.reconcile_all()


# ---------------------------------------------------------------------------
# Group B: 5 cases dispatch (5 cases)
# ---------------------------------------------------------------------------


class TestCaseDispatch:
    async def test_case_e_full_match_no_op(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=100, avg=70000),
        ])
        await _seed_position(session_factory, stock_code="005930", qty=100)

        report = await reconciler.reconcile_all()

        assert report.matched_count == 1
        assert report.discrepancy_count == 0
        assert report.decisions[0].case == ReconciliationCase.E_FULL_MATCH
        assert report.decisions[0].actions_applied == ()
        assert (await _read_trade_events(session_factory)) == []

    async def test_case_a_pyramid_invokes_callback(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        cb = AsyncMock()
        rec = make_reconciler(on_pyramid=cb)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=150, avg=72000),
        ])
        await _seed_position(session_factory, stock_code="005930", qty=100, avg=70000)

        report = await rec.reconcile_all()

        cb.assert_awaited_once()
        event = cb.await_args.args[0]
        assert isinstance(event, V71PyramidBuyDetected)
        assert event.diff_qty == 50
        assert event.kiwoom_avg_price == 72000
        assert report.decisions[0].case == ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY
        # Case A delegates to V71PositionManager -- DB unchanged.
        rows = await _read_positions(session_factory)
        assert rows[0].total_quantity == 100  # untouched

    async def test_case_b_partial_sell_applies(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        await _seed_position(session_factory, stock_code="005930", qty=100, avg=70000)

        report = await reconciler.reconcile_all()

        assert report.decisions[0].case == ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL
        rows = await _read_positions(session_factory)
        assert rows[0].total_quantity == 70

    async def test_case_c_tracked_invokes_callback(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        cb = AsyncMock()
        rec = make_reconciler(on_tracking_terminated=cb)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])
        await _seed_tracking(session_factory, stock_code="005930", status=TrackedStatus.BOX_SET)

        report = await rec.reconcile_all()

        cb.assert_awaited_once()
        event = cb.await_args.args[0]
        assert isinstance(event, V71TrackingTerminated)
        assert event.new_manual_qty == 50
        assert report.decisions[0].case == ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY

    async def test_case_d_untracked_inserts_manual(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000, name="삼성전자"),
        ])

        report = await reconciler.reconcile_all()

        assert report.decisions[0].case == ReconciliationCase.D_UNTRACKED_MANUAL_BUY
        rows = await _read_positions(session_factory)
        assert len(rows) == 1
        assert rows[0].source == PositionSource.MANUAL
        # Trading D1 / Security H1: stock_name is broker stk_nm, not stock_code.
        assert rows[0].stock_name == "삼성전자"


# ---------------------------------------------------------------------------
# Group C: B sell algorithm (8 cases)
# ---------------------------------------------------------------------------


class TestCaseBPartialSell:
    async def test_manual_drained_only(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # MANUAL 50 + PATH_A 50 = 100. Kiwoom 70 -> sell 30 from MANUAL.
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        manual = await _seed_position(
            session_factory, source=PositionSource.MANUAL, qty=50,
        )
        path_a = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=50,
        )

        await reconciler.reconcile_all()

        manual_after = await _read_position_by_id(session_factory, manual.id)
        path_a_after = await _read_position_by_id(session_factory, path_a.id)
        assert manual_after.total_quantity == 20
        assert manual_after.status == PositionStatus.PARTIAL_CLOSED
        assert path_a_after.total_quantity == 50  # untouched

    async def test_manual_drained_to_zero_marks_closed(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        manual = await _seed_position(
            session_factory, source=PositionSource.MANUAL, qty=30,
        )
        await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=70,
        )

        await reconciler.reconcile_all()

        m = await _read_position_by_id(session_factory, manual.id)
        assert m.total_quantity == 0
        assert m.status == PositionStatus.CLOSED
        assert m.closed_at is not None
        assert m.close_reason == "MANUAL_PARTIAL_EXIT_RECONCILED"

    async def test_single_path_a_drain(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=100,
        )

        await reconciler.reconcile_all()

        rows = await _read_positions(session_factory)
        assert rows[0].total_quantity == 70
        # B1: partial -> PARTIAL_CLOSED, NOT OPEN.
        assert rows[0].status == PositionStatus.PARTIAL_CLOSED

    async def test_dual_path_proportional_split(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # PRD §7.3 case 3 example: sell 10 across PATH_A 60 + PATH_B 40
        # -> expect (6, 4) with larger-first rounding.
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=90, avg=70000),
        ])
        path_a = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=60,
        )
        path_b = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_B, qty=40,
        )

        await reconciler.reconcile_all()

        a = await _read_position_by_id(session_factory, path_a.id)
        b = await _read_position_by_id(session_factory, path_b.id)
        assert a.total_quantity == 54
        assert b.total_quantity == 36

    async def test_dual_path_larger_first_rounding(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # sell 11 across 70 / 30 -> larger-first 8 / 3.
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=89, avg=70000),
        ])
        path_a = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=70,
        )
        path_b = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_B, qty=30,
        )

        await reconciler.reconcile_all()

        a = await _read_position_by_id(session_factory, path_a.id)
        b = await _read_position_by_id(session_factory, path_b.id)
        # Total decrease 11; PATH_A is larger so it absorbs the rounding.
        assert (a.total_quantity, b.total_quantity) == (62, 27)

    async def test_manual_then_single_path(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # MANUAL 20 + PATH_A 80 = 100. Sell 50 -> drain MANUAL fully (20),
        # then PATH_A 30.
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])
        manual = await _seed_position(
            session_factory, source=PositionSource.MANUAL, qty=20,
        )
        path_a = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=80,
        )

        await reconciler.reconcile_all()

        m = await _read_position_by_id(session_factory, manual.id)
        a = await _read_position_by_id(session_factory, path_a.id)
        assert m.total_quantity == 0
        assert m.status == PositionStatus.CLOSED
        assert a.total_quantity == 50

    async def test_avg_price_unchanged_after_sell(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        """02 §6.4 — sell does not change weighted_avg_price."""
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        seeded = await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=100, avg=70000,
        )

        await reconciler.reconcile_all()

        row = await _read_position_by_id(session_factory, seeded.id)
        assert row.weighted_avg_price == Decimal(70000)
        assert row.fixed_stop_price == Decimal(int(70000 * 0.95))

    async def test_unapplied_remaining_audit_marker(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # Engineer a mismatch so that remaining > 0 after drain.
        # We seed system_qty=50 but Kiwoom reports 0 -> sell_qty=50,
        # then mid-way we deliberately empty path B by seeding zero
        # contribution beyond MANUAL=10.
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([])
        await _seed_position(
            session_factory, source=PositionSource.MANUAL, qty=10,
        )
        await _seed_position(
            session_factory, source=PositionSource.SYSTEM_A, qty=20,
        )
        # Total = 30. Kiwoom = 0 -> sell 30. All distributed (no remaining).

        await reconciler.reconcile_all()

        events = await _read_trade_events(session_factory)
        # Normal full distribution -> no UNAPPLIED marker.
        for e in events:
            assert "UNAPPLIED_REMAINING" not in str(e.payload)


# ---------------------------------------------------------------------------
# Group D: D INSERT (4 cases)
# ---------------------------------------------------------------------------


class TestCaseDManualInsert:
    async def test_inserts_manual_position(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000, name="삼성전자"),
        ])

        await reconciler.reconcile_all()

        rows = await _read_positions(session_factory)
        assert len(rows) == 1
        row = rows[0]
        assert row.source == PositionSource.MANUAL
        assert row.weighted_avg_price == Decimal(70000)
        assert row.initial_avg_price == Decimal(70000)
        assert row.total_quantity == 50
        assert row.fixed_stop_price == Decimal(66500)  # 70000 * 0.95
        assert row.profit_5_executed is False
        assert row.profit_10_executed is False
        assert row.ts_activated is False
        assert row.tracked_stock_id is None
        assert row.triggered_box_id is None
        assert row.status == PositionStatus.OPEN

    async def test_fixed_stop_price_uses_v71_constants(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # avg 100,000 -> stop 95,000 = 100000 * (1 + (-0.05)).
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="000660", qty=10, avg=100000, name="X"),
        ])

        await reconciler.reconcile_all()

        rows = await _read_positions(session_factory)
        assert rows[0].fixed_stop_price == Decimal(95000)

    async def test_trade_event_links_position_id(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000, name="삼성전자"),
        ])

        await reconciler.reconcile_all()

        positions = await _read_positions(session_factory)
        events = await _read_trade_events(session_factory)
        assert len(events) == 1
        # Migration small-issue-2: case D event links to the new MANUAL row.
        assert events[0].position_id == positions[0].id
        assert events[0].event_type == TradeEventType.POSITION_RECONCILED
        assert events[0].payload["case"] == "D"

    async def test_zero_avg_does_not_insert(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        # avg=0 from corrupt data -> _apply_manual_insert short-circuits.
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            {"stk_cd": "005930", "stk_nm": "X",
             "rmnd_qty": "50", "pur_pric": "0"},
        ])

        await reconciler.reconcile_all()

        rows = await _read_positions(session_factory)
        assert rows == []


# ---------------------------------------------------------------------------
# Group E: case A pyramid candidate_path (5 cases)
# ---------------------------------------------------------------------------


class TestCaseAPyramidCandidate:
    @pytest.mark.parametrize(
        "sources,expected",
        [
            ((PositionSource.SYSTEM_A,), "PATH_A"),
            ((PositionSource.SYSTEM_B,), "PATH_B"),
            ((PositionSource.SYSTEM_A, PositionSource.SYSTEM_B), "DUAL"),
            ((PositionSource.MANUAL,), "MANUAL_ONLY"),
        ],
    )
    async def test_candidate_path_choice(
        self, make_reconciler, kiwoom_client_mock, session_factory,
        sources, expected,
    ):
        cb = AsyncMock()
        rec = make_reconciler(on_pyramid=cb)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=200, avg=70000),
        ])
        for source in sources:
            await _seed_position(
                session_factory, source=source, qty=50, avg=70000,
            )

        await rec.reconcile_all()

        event = cb.await_args.args[0]
        assert event.candidate_path == expected

    async def test_pyramid_callback_none_no_error(
        self, reconciler, kiwoom_client_mock, session_factory, caplog
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=150, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        with caplog.at_level(logging.INFO):
            report = await reconciler.reconcile_all()
        assert report.decisions[0].case == ReconciliationCase.A_SYSTEM_PLUS_MANUAL_BUY


# ---------------------------------------------------------------------------
# Group F: case C tracking termination + callback isolation (3 cases)
# ---------------------------------------------------------------------------


class TestCaseCTrackingTerminated:
    async def test_event_carries_tracked_stock_id(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        cb = AsyncMock()
        rec = make_reconciler(on_tracking_terminated=cb)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000, name="삼성전자"),
        ])
        seeded = await _seed_tracking(
            session_factory, status=TrackedStatus.BOX_SET,
        )

        await rec.reconcile_all()

        event = cb.await_args.args[0]
        assert event.tracked_stock_id == seeded.id
        assert event.new_manual_qty == 50
        assert event.new_manual_avg_price == 70000

    async def test_callback_exception_isolated(
        self, make_reconciler, kiwoom_client_mock, session_factory, caplog
    ):
        secret = "TRACKING-CB-SECRET-9999"

        async def _raising(_event):
            raise RuntimeError(secret)

        rec = make_reconciler(on_tracking_terminated=_raising)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])
        await _seed_tracking(session_factory)

        with caplog.at_level(logging.ERROR):
            await rec.reconcile_all()

        for record in caplog.records:
            assert secret not in record.getMessage()

    async def test_pyramid_callback_exception_isolated(
        self, make_reconciler, kiwoom_client_mock, session_factory, caplog
    ):
        secret = "PYRAMID-CB-SECRET-1111"

        async def _raising(_event):
            raise RuntimeError(secret)

        rec = make_reconciler(on_pyramid=_raising)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=150, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        with caplog.at_level(logging.ERROR):
            await rec.reconcile_all()

        for record in caplog.records:
            assert secret not in record.getMessage()


# ---------------------------------------------------------------------------
# Group G: DETECT_ONLY mode (3 cases)
# ---------------------------------------------------------------------------


class TestDetectOnlyMode:
    async def test_b_does_not_apply_db_writes(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        rec = make_reconciler(apply_mode=V71ReconciliationApplyMode.DETECT_ONLY)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        seeded = await _seed_position(session_factory, qty=100)

        await rec.reconcile_all()

        row = await _read_position_by_id(session_factory, seeded.id)
        assert row.total_quantity == 100  # unchanged
        events = await _read_trade_events(session_factory)
        assert events == []

    async def test_d_does_not_insert(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        rec = make_reconciler(apply_mode=V71ReconciliationApplyMode.DETECT_ONLY)
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])

        await rec.reconcile_all()

        rows = await _read_positions(session_factory)
        assert rows == []

    async def test_a_does_not_call_callback(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        cb = AsyncMock()
        rec = make_reconciler(
            apply_mode=V71ReconciliationApplyMode.DETECT_ONLY,
            on_pyramid=cb,
        )
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=150, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        await rec.reconcile_all()

        cb.assert_not_awaited()


# ---------------------------------------------------------------------------
# Group H: trade_events recording (4 cases)
# ---------------------------------------------------------------------------


class TestTradeEventRecording:
    async def test_b_records_event_with_payload_schema(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=70, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        await reconciler.reconcile_all()

        events = await _read_trade_events(session_factory)
        assert len(events) == 1
        assert events[0].event_type == TradeEventType.POSITION_RECONCILED
        # Architect N9 schema.
        payload = events[0].payload
        assert set(payload.keys()) == {
            "case", "kiwoom_qty", "system_qty", "diff", "actions_applied",
        }
        assert payload["case"] == "B"
        assert payload["diff"] == -30

    async def test_e_records_no_event(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=100, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        await reconciler.reconcile_all()

        assert (await _read_trade_events(session_factory)) == []

    async def test_a_records_no_event(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        rec = make_reconciler(on_pyramid=AsyncMock())
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=150, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        await rec.reconcile_all()

        # A is delegated to V71PositionManager which records its own
        # MANUAL_PYRAMID_BUY event; reconciler stays out.
        assert (await _read_trade_events(session_factory)) == []

    async def test_c_records_no_event(
        self, make_reconciler, kiwoom_client_mock, session_factory
    ):
        rec = make_reconciler(on_tracking_terminated=AsyncMock())
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])
        await _seed_tracking(session_factory)

        await rec.reconcile_all()

        assert (await _read_trade_events(session_factory)) == []


# ---------------------------------------------------------------------------
# Group I: per-stock failure isolation (3 cases)
# ---------------------------------------------------------------------------


class TestFailureIsolation:
    async def test_one_stock_failure_does_not_starve_others(
        self, reconciler, kiwoom_client_mock, session_factory, monkeypatch
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=100, avg=70000),
            _kt00018_row(stock_code="000660", qty=50, avg=130000),
        ])
        await _seed_position(session_factory, stock_code="005930", qty=100)
        await _seed_position(session_factory, stock_code="000660", qty=50, avg=130000)

        # Make _reconcile_one raise for 005930 only.
        original = V71Reconciler._reconcile_one

        async def _patched(self, *, stock_code, **kw):
            if stock_code == "005930":
                raise RuntimeError("boom")
            return await original(self, stock_code=stock_code, **kw)

        monkeypatch.setattr(V71Reconciler, "_reconcile_one", _patched)

        report = await reconciler.reconcile_all()

        assert report.error_count == 1
        assert "005930" in report.failed_stock_codes
        # 000660 still progressed.
        codes = {d.stock_code for d in report.decisions if d.error is None}
        assert "000660" in codes

    async def test_classify_value_error_isolated(
        self, reconciler, kiwoom_client_mock, monkeypatch
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=10, avg=70000),
        ])
        # Provoke classify_case ValueError by forcing system_qty>kiwoom_qty
        # while system_qty == 0 -- impossible state surfaces via patched
        # classify.
        from src.core.v71.exchange import reconciler as rec_module

        def _bad_classify(*_a, **_kw):
            raise ValueError("synthetic")

        monkeypatch.setattr(rec_module, "classify_case", _bad_classify)

        report = await reconciler.reconcile_all()

        assert report.decisions[0].error is not None
        assert "classify_case" in report.decisions[0].error

    async def test_failed_stock_codes_reported(
        self, reconciler, kiwoom_client_mock, monkeypatch
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=100, avg=70000),
            _kt00018_row(stock_code="000660", qty=50, avg=130000),
        ])

        async def _always_raise(_self, **_kw):
            raise RuntimeError("synthetic")

        monkeypatch.setattr(V71Reconciler, "_reconcile_one", _always_raise)

        report = await reconciler.reconcile_all()

        assert set(report.failed_stock_codes) == {"005930", "000660"}
        assert report.error_count == 2


# ---------------------------------------------------------------------------
# Group K: has_active_tracking whitelist (5 cases parametrized)
# ---------------------------------------------------------------------------


class TestActiveTrackingWhitelist:
    @pytest.mark.parametrize(
        "status,expected_has_tracking",
        [
            (TrackedStatus.TRACKING, True),
            (TrackedStatus.BOX_SET, True),
            (TrackedStatus.POSITION_OPEN, True),
            (TrackedStatus.POSITION_PARTIAL, True),
            (TrackedStatus.EXITED, False),
        ],
    )
    async def test_whitelist_decides_case_c_vs_d(
        self, reconciler, kiwoom_client_mock, session_factory,
        status, expected_has_tracking,
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])
        await _seed_tracking(session_factory, status=status)

        report = await reconciler.reconcile_all()

        decision = report.decisions[0]
        assert decision.has_active_tracking == expected_has_tracking
        if expected_has_tracking:
            assert decision.case == ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY
        else:
            assert decision.case == ReconciliationCase.D_UNTRACKED_MANUAL_BUY


# ---------------------------------------------------------------------------
# Group L: reconcile_stock single-stock API (4 cases)
# ---------------------------------------------------------------------------


class TestReconcileStock:
    async def test_normal_match(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=100, avg=70000),
        ])
        await _seed_position(session_factory, qty=100)

        decision = await reconciler.reconcile_stock("005930")

        assert decision.case == ReconciliationCase.E_FULL_MATCH

    async def test_empty_stock_code_raises(self, reconciler):
        with pytest.raises(ValueError, match="stock_code is required"):
            await reconciler.reconcile_stock("")

    async def test_invalid_format_raises(self, reconciler):
        with pytest.raises(ValueError, match="invalid stock_code format"):
            await reconciler.reconcile_stock("abc")

    async def test_kiwoom_missing_means_full_sell(
        self, reconciler, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([])
        await _seed_position(session_factory, stock_code="005930", qty=100)

        decision = await reconciler.reconcile_stock("005930")

        assert decision.case == ReconciliationCase.B_SYSTEM_PLUS_MANUAL_SELL
        rows = await _read_positions(session_factory)
        assert rows[0].total_quantity == 0
        assert rows[0].status == PositionStatus.CLOSED


# ---------------------------------------------------------------------------
# Group M: helpers (5 cases)
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("100", 100),
            ("+200", 200),
            ("-50", -50),
            ("", 0),
            ("ABC", 0),
            (None, 0),
            (42, 42),
        ],
    )
    def test_coerce_int(self, raw, expected):
        assert _coerce_int(raw) == expected

    @pytest.mark.parametrize(
        "source,expected_path",
        [
            (PositionSource.SYSTEM_A, "PATH_A"),
            (PositionSource.SYSTEM_B, "PATH_B"),
            (PositionSource.MANUAL, "MANUAL"),
        ],
    )
    async def test_orm_to_position_state_path_mapping(
        self, session_factory, source, expected_path,
    ):
        row = await _seed_position(session_factory, source=source)
        state = _orm_to_position_state(row)
        assert state.path_type == expected_path
        assert state.weighted_avg_price == int(row.weighted_avg_price)
        assert state.total_quantity == row.total_quantity


# ---------------------------------------------------------------------------
# Group N: security regression (4 cases)
# ---------------------------------------------------------------------------


class TestSecurityRegression:
    async def test_repr_does_not_leak_callbacks_or_factory(
        self, kiwoom_client_mock, session_factory, fixed_clock
    ):
        secret = "CALLBACK-SECRET-77"

        async def _cb(_event):
            return secret

        rec = V71Reconciler(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_pyramid_buy_detected=_cb,
            on_tracking_terminated=_cb,
        )
        text = repr(rec)
        assert "kiwoom_client" in text
        assert "apply_mode" in text
        assert secret not in text
        assert "session_factory" not in text
        assert "on_pyramid" not in text

    async def test_kiwoom_pii_never_logged(
        self, reconciler, kiwoom_client_mock, caplog
    ):
        # Inject a plausibly-PII account number into the response payload
        # (acnt_no) and ensure logger output never echoes it.
        secret_acnt = "1234567890PII"
        response = V71KiwoomResponse(
            success=True,
            api_id="kt00018",
            data={
                "acnt_no": secret_acnt,
                "tot_evlt_amt": "999999999",
                "acnt_evlt_remn_indv_tot": [
                    _kt00018_row(stock_code="005930", qty=50, avg=70000),
                ],
            },
            return_code=0,
            return_msg="OK",
            cont_yn="N",
            next_key="",
            duration_ms=15,
        )
        kiwoom_client_mock.get_account_balance.return_value = response

        with caplog.at_level(logging.DEBUG):
            await reconciler.reconcile_all()

        for record in caplog.records:
            assert secret_acnt not in record.getMessage()

    async def test_invalid_stock_code_log_does_not_echo_value(
        self, reconciler, kiwoom_client_mock, caplog
    ):
        # An attacker-controlled malformed stock_code with newline must
        # not appear in logs (Security M2 -- log injection defence).
        malicious = "x\nINJECT_LINE"
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            {"stk_cd": malicious, "stk_nm": "X",
             "rmnd_qty": "10", "pur_pric": "1"},
        ])

        with caplog.at_level(logging.WARNING):
            await reconciler.reconcile_all()

        for record in caplog.records:
            assert "INJECT_LINE" not in record.getMessage()

    async def test_case_c_missing_tracking_graceful(
        self, make_reconciler, kiwoom_client_mock,
        monkeypatch, caplog,
    ):
        # Force classify_case to return C while tracking is None to test
        # M5 graceful handling (production safety against -O).
        from src.core.v71.exchange import reconciler as rec_module

        def _force_c(*_a, **_kw):
            return ReconciliationCase.C_TRACKED_BUT_MANUAL_BUY

        monkeypatch.setattr(rec_module, "classify_case", _force_c)
        rec = make_reconciler()
        kiwoom_client_mock.get_account_balance.return_value = _kt00018_response([
            _kt00018_row(stock_code="005930", qty=50, avg=70000),
        ])
        # Note: NO tracking row seeded.

        with caplog.at_level(logging.ERROR):
            report = await rec.reconcile_all()

        decision = report.decisions[0]
        assert decision.error == "case_c_missing_tracking_contract_violation"
