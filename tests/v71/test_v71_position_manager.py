"""Unit tests for ``src/core/v71/position/v71_position_manager.py``.

Spec:
  - 02_TRADING_RULES.md §6   (avg-price + event reset)
  - 02_TRADING_RULES.md §5.4 (stop ladder via stage_after_partial_exit)
  - 02_TRADING_RULES.md §5.9 (CLOSED on zero quantity)
"""

from __future__ import annotations

import os
from datetime import datetime

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__POSITION_V71"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.position.v71_position_manager import (  # noqa: E402
    InvalidEventTypeError,
    PositionNotFoundError,
    V71PositionManager,
)

# ---------------------------------------------------------------------------
# add_position (PositionStore Protocol surface)
# ---------------------------------------------------------------------------


class TestAddPosition:
    @pytest.mark.asyncio
    async def test_add_returns_uuid_and_indexes(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930",
            tracked_stock_id="t1",
            triggered_box_id="b1",
            path_type="PATH_A",
            quantity=100,
            weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28, 10, 0),
        )
        assert pid  # UUID
        state = pm.get(pid)
        assert state.stock_code == "005930"
        assert state.weighted_avg_price == 18_000
        assert state.initial_avg_price == 18_000
        assert state.total_quantity == 100
        # Stage 1 stop = 18_000 * 0.95 = 17_100
        assert state.fixed_stop_price == 17_100
        assert state.status == "OPEN"

    @pytest.mark.asyncio
    async def test_add_logs_buy_executed_event(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930",
            tracked_stock_id="t1",
            triggered_box_id="b1",
            path_type="PATH_A",
            quantity=100,
            weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28, 10, 0),
        )
        events = pm.list_events(position_id=pid)
        assert len(events) == 1
        assert events[0].event_type == "BUY_EXECUTED"
        assert events[0].quantity == 100
        assert events[0].price == 18_000

    @pytest.mark.asyncio
    async def test_add_rejects_invalid_inputs(self):
        pm = V71PositionManager()
        with pytest.raises(ValueError):
            await pm.add_position(
                stock_code="005930",
                tracked_stock_id="t1",
                triggered_box_id="b1",
                path_type="PATH_A",
                quantity=0,
                weighted_avg_price=18_000,
                opened_at=datetime(2026, 4, 28),
            )
        with pytest.raises(ValueError):
            await pm.add_position(
                stock_code="005930",
                tracked_stock_id="t1",
                triggered_box_id="b1",
                path_type="PATH_A",
                quantity=10,
                weighted_avg_price=0,
                opened_at=datetime(2026, 4, 28),
            )


# ---------------------------------------------------------------------------
# apply_buy
# ---------------------------------------------------------------------------


class TestApplyBuy:
    @pytest.mark.asyncio
    async def test_pyramid_buy_recomputes_average_and_resets_events(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28, 10, 0),
        )
        # Pretend +5% partial happened.
        state = pm.get(pid)
        state.profit_5_executed = True
        state.fixed_stop_price = int(180_000 * 0.98)
        state.total_quantity = 70  # after 30 sold

        update = await pm.apply_buy(
            pid, buy_price=175_000, buy_quantity=100,
            when=datetime(2026, 4, 28, 11, 0),
        )
        # Weighted avg of 70@180k + 100@175k = ~177_059
        assert update.weighted_avg_price == round(
            (70 * 180_000 + 100 * 175_000) / 170
        )
        assert update.events_reset is True
        # Events reset
        state = pm.get(pid)
        assert state.profit_5_executed is False
        assert state.profit_10_executed is False
        # Stop fell back to stage 1
        assert state.fixed_stop_price == int(round(state.weighted_avg_price * 0.95))
        # initial_avg preserved
        assert state.initial_avg_price == 180_000

    @pytest.mark.asyncio
    async def test_apply_buy_logs_pyramid_event(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28, 10, 0),
        )
        await pm.apply_buy(
            pid, buy_price=17_500, buy_quantity=50,
            event_type="PYRAMID_BUY",
        )
        events = pm.list_events(position_id=pid)
        # add_position + apply_buy = 2 events
        assert len(events) == 2
        assert events[1].event_type == "PYRAMID_BUY"
        assert events[1].events_reset is True

    @pytest.mark.asyncio
    async def test_apply_buy_supports_manual_pyramid(self):
        """Scenario A: user manually added shares -- distinct event type."""
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28, 10, 0),
        )
        await pm.apply_buy(
            pid, buy_price=18_500, buy_quantity=50,
            event_type="MANUAL_PYRAMID_BUY",
        )
        events = pm.list_events(position_id=pid)
        assert events[1].event_type == "MANUAL_PYRAMID_BUY"

    @pytest.mark.asyncio
    async def test_apply_buy_rejects_unknown_event_type(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28),
        )
        with pytest.raises(InvalidEventTypeError):
            await pm.apply_buy(
                pid, buy_price=17_000, buy_quantity=10,
                event_type="STOP_LOSS",
            )

    @pytest.mark.asyncio
    async def test_apply_buy_unknown_position_raises(self):
        pm = V71PositionManager()
        with pytest.raises(PositionNotFoundError):
            await pm.apply_buy(
                "does-not-exist", buy_price=18_000, buy_quantity=10,
            )


# ---------------------------------------------------------------------------
# apply_sell
# ---------------------------------------------------------------------------


class TestApplySell:
    @pytest.mark.asyncio
    async def test_profit_5_advances_stop_and_sets_flag(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await pm.apply_sell(
            pid, sell_quantity=30, sell_price=189_000,
            event_type="PROFIT_TAKE_5",
        )
        state = pm.get(pid)
        assert state.profit_5_executed is True
        assert state.profit_10_executed is False
        assert state.total_quantity == 70
        assert state.weighted_avg_price == 180_000  # avg unchanged (§6.4)
        # Stage 2: avg * 0.98
        assert state.fixed_stop_price == int(round(180_000 * 0.98))
        assert state.status == "PARTIAL_CLOSED"

    @pytest.mark.asyncio
    async def test_profit_10_advances_to_stage_3(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        # Simulate +5% already happened.
        await pm.apply_sell(
            pid, sell_quantity=30, sell_price=189_000,
            event_type="PROFIT_TAKE_5",
        )
        await pm.apply_sell(
            pid, sell_quantity=21, sell_price=198_000,
            event_type="PROFIT_TAKE_10",
        )
        state = pm.get(pid)
        assert state.profit_10_executed is True
        # Stage 3: avg * 1.04
        assert state.fixed_stop_price == int(round(180_000 * 1.04))
        assert state.total_quantity == 49

    @pytest.mark.asyncio
    async def test_stop_loss_does_not_advance_ladder(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        original_stop = pm.get(pid).fixed_stop_price
        await pm.apply_sell(
            pid, sell_quantity=100, sell_price=171_000,
            event_type="STOP_LOSS",
        )
        state = pm.get(pid)
        # full sell -> CLOSED
        assert state.status == "CLOSED"
        assert state.total_quantity == 0
        assert state.closed_at is not None
        # Ladder unchanged on stop loss (no advancement).
        assert state.fixed_stop_price == original_stop

    @pytest.mark.asyncio
    async def test_ts_exit_does_not_advance_ladder(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=49, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        original_stop = pm.get(pid).fixed_stop_price
        await pm.apply_sell(
            pid, sell_quantity=49, sell_price=210_000,
            event_type="TS_EXIT",
        )
        state = pm.get(pid)
        assert state.status == "CLOSED"
        assert state.fixed_stop_price == original_stop

    @pytest.mark.asyncio
    async def test_apply_sell_rejects_unknown_event_type(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28),
        )
        with pytest.raises(InvalidEventTypeError):
            await pm.apply_sell(
                pid, sell_quantity=10, sell_price=18_500,
                event_type="PYRAMID_BUY",
            )

    @pytest.mark.asyncio
    async def test_partial_to_open_status_progression(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        assert pm.get(pid).status == "OPEN"
        await pm.apply_sell(
            pid, sell_quantity=30, sell_price=189_000,
            event_type="PROFIT_TAKE_5",
        )
        assert pm.get(pid).status == "PARTIAL_CLOSED"
        await pm.apply_sell(
            pid, sell_quantity=70, sell_price=198_000,
            event_type="STOP_LOSS",
        )
        assert pm.get(pid).status == "CLOSED"


# ---------------------------------------------------------------------------
# close_position
# ---------------------------------------------------------------------------


class TestClosePosition:
    @pytest.mark.asyncio
    async def test_close_zero_qty_marks_closed(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await pm.apply_sell(
            pid, sell_quantity=100, sell_price=170_000,
            event_type="STOP_LOSS",
        )
        # apply_sell already closed it, but close_position should be idempotent.
        state = pm.close_position(pid)
        assert state.status == "CLOSED"

    @pytest.mark.asyncio
    async def test_close_with_nonzero_qty_raises(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        with pytest.raises(ValueError, match="non-zero quantity"):
            pm.close_position(pid)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


class TestQueries:
    @pytest.mark.asyncio
    async def test_get_by_stock_returns_active_only(self):
        pm = V71PositionManager()
        pid_a = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        # Different path on same stock.
        pid_b = await pm.add_position(
            stock_code="005930", tracked_stock_id="t2", triggered_box_id="b2",
            path_type="PATH_B", quantity=50, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        a = pm.get_by_stock("005930", "PATH_A")
        b = pm.get_by_stock("005930", "PATH_B")
        assert a is not None and a.position_id == pid_a
        assert b is not None and b.position_id == pid_b

    @pytest.mark.asyncio
    async def test_get_by_stock_skips_closed(self):
        pm = V71PositionManager()
        pid = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        await pm.apply_sell(
            pid, sell_quantity=100, sell_price=170_000,
            event_type="STOP_LOSS",
        )
        assert pm.get_by_stock("005930", "PATH_A") is None

    @pytest.mark.asyncio
    async def test_list_open_excludes_closed(self):
        pm = V71PositionManager()
        pid_open = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=180_000,
            opened_at=datetime(2026, 4, 28),
        )
        pid_closed = await pm.add_position(
            stock_code="000660", tracked_stock_id="t2", triggered_box_id="b2",
            path_type="PATH_A", quantity=50, weighted_avg_price=120_000,
            opened_at=datetime(2026, 4, 28),
        )
        await pm.apply_sell(
            pid_closed, sell_quantity=50, sell_price=114_000,
            event_type="STOP_LOSS",
        )
        open_list = pm.list_open()
        assert len(open_list) == 1
        assert open_list[0].position_id == pid_open

    @pytest.mark.asyncio
    async def test_list_events_filter(self):
        pm = V71PositionManager()
        pid_a = await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=datetime(2026, 4, 28),
        )
        await pm.add_position(
            stock_code="000660", tracked_stock_id="t2", triggered_box_id="b2",
            path_type="PATH_A", quantity=50, weighted_avg_price=120_000,
            opened_at=datetime(2026, 4, 28),
        )
        all_events = pm.list_events()
        assert len(all_events) == 2
        a_events = pm.list_events(position_id=pid_a)
        assert len(a_events) == 1
        assert a_events[0].position_id == pid_a


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_runtime_error_when_disabled(self):
        os.environ["V71_FF__V71__POSITION_V71"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.position_v71"):
                V71PositionManager()
        finally:
            os.environ["V71_FF__V71__POSITION_V71"] = "true"
            ff.reload()
