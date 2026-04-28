"""Unit tests for V71ExitOrchestrator (P-Wire-6)."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_exit_flag():
    saved = os.environ.get("V71_FF__V71__EXIT_V71")
    os.environ["V71_FF__V71__EXIT_V71"] = "true"
    ff.reload()
    yield
    if saved is None:
        os.environ.pop("V71_FF__V71__EXIT_V71", None)
    else:
        os.environ["V71_FF__V71__EXIT_V71"] = saved
    ff.reload()


def _make_position(
    *,
    stock_code="005930",
    total_qty=10,
    avg_price=70_000,
    fixed_stop=66_500,
    profit_5=False,
    profit_10=False,
    ts_active=False,
    ts_stop=None,
    status="OPEN",
):
    from src.core.v71.position.state import PositionState

    return PositionState(
        position_id=f"pos-{stock_code}-{total_qty}",
        stock_code=stock_code,
        tracked_stock_id=f"track-{stock_code}",
        triggered_box_id=f"box-{stock_code}",
        path_type="PATH_A",
        weighted_avg_price=avg_price,
        initial_avg_price=avg_price,
        total_quantity=total_qty,
        fixed_stop_price=fixed_stop,
        profit_5_executed=profit_5,
        profit_10_executed=profit_10,
        ts_activated=ts_active,
        ts_base_price=None,
        ts_stop_price=ts_stop,
        ts_active_multiplier=None,
        status=status,
    )


def _make_message(stock_code, values):
    from src.core.v71.exchange.kiwoom_websocket import (
        V71KiwoomChannelType,
        V71WebSocketMessage,
    )

    return V71WebSocketMessage(
        channel=V71KiwoomChannelType.PRICE_TICK,
        item=stock_code, name="체결",
        values=values,
        received_at=datetime.now(timezone.utc),
        raw={"type": "0B", "item": stock_code, "values": values},
    )


@pytest.fixture
def orchestrator_factory():
    from src.core.v71.exchange.kiwoom_websocket import V71KiwoomChannelType
    from src.core.v71.exit.exit_calculator import V71ExitCalculator
    from src.core.v71.strategies.exit_orchestrator import V71ExitOrchestrator

    def _build(*, positions=None, atr=None):
        pm = MagicMock()
        pm.list_for_stock.return_value = positions or []
        executor = MagicMock()
        executor.execute_stop_loss = AsyncMock()
        executor.execute_ts_exit = AsyncMock()
        executor.execute_profit_take = AsyncMock()
        ws = MagicMock()
        ws.register_handler = MagicMock()
        ws.subscribe = AsyncMock()
        ws.unsubscribe = AsyncMock()
        calc = V71ExitCalculator()
        orch = V71ExitOrchestrator(
            position_manager=pm,
            exit_calculator=calc,
            exit_executor=executor,
            websocket=ws,
            atr_cache=atr or {},
        )
        return orch, pm, executor, ws, V71KiwoomChannelType
    return _build


# ---------------------------------------------------------------------------
# start / stop / subscribe
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_registers_price_tick_handler(orchestrator_factory):
    orch, _pm, _ex, ws, ChannelType = orchestrator_factory()
    await orch.start()
    ws.register_handler.assert_called_once()
    args = ws.register_handler.call_args.args
    assert args[0] == ChannelType.PRICE_TICK


@pytest.mark.asyncio
async def test_start_is_idempotent(orchestrator_factory):
    orch, _pm, _ex, ws, _Ch = orchestrator_factory()
    await orch.start()
    await orch.start()
    assert ws.register_handler.call_count == 1


@pytest.mark.asyncio
async def test_subscribe_calls_ws_once(orchestrator_factory):
    orch, _pm, _ex, ws, ChannelType = orchestrator_factory()
    await orch.subscribe("005930")
    await orch.subscribe("005930")  # second call no-op
    ws.subscribe.assert_awaited_once_with(ChannelType.PRICE_TICK, "005930")


@pytest.mark.asyncio
async def test_unsubscribe_drops_state(orchestrator_factory):
    orch, _pm, _ex, ws, ChannelType = orchestrator_factory()
    await orch.subscribe("005930")
    await orch.unsubscribe("005930")
    ws.unsubscribe.assert_awaited_once_with(ChannelType.PRICE_TICK, "005930")
    # Subsequent subscribe attempts go through again
    await orch.subscribe("005930")
    assert ws.subscribe.await_count == 2


# ---------------------------------------------------------------------------
# Price tick → exit decision routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_loss_triggers_when_price_below_fixed_stop(orchestrator_factory):
    pos = _make_position(fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    msg = _make_message("005930", {"10": "0000066400"})
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_awaited_once_with(pos)
    executor.execute_ts_exit.assert_not_awaited()
    executor.execute_profit_take.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_exit_when_price_above_stop_and_no_profit(orchestrator_factory):
    pos = _make_position(avg_price=70_000, fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    msg = _make_message("005930", {"10": "0000071000"})  # +1.4% only
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()
    executor.execute_profit_take.assert_not_awaited()


@pytest.mark.asyncio
async def test_profit_take_5_pct_triggers(orchestrator_factory):
    # +5% from 70_000 = 73_500
    pos = _make_position(avg_price=70_000)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    msg = _make_message("005930", {"10": "0000074000"})  # +5.7%
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()
    executor.execute_profit_take.assert_awaited_once()
    call_args = executor.execute_profit_take.call_args
    assert call_args.args[0] is pos


@pytest.mark.asyncio
async def test_ts_exit_triggers_when_ts_binding_and_price_below_ts_stop(
    orchestrator_factory,
):
    # TS binding requires profit_10_executed True + ts_activated + ts_stop_price
    pos = _make_position(
        avg_price=70_000,
        fixed_stop=66_500,
        profit_5=True,
        profit_10=True,
        ts_active=True,
        ts_stop=72_000,  # higher than fixed → binding
    )
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    msg = _make_message("005930", {"10": "0000071500"})  # below TS stop
    await orch._handle_price_message(msg)
    executor.execute_ts_exit.assert_awaited_once_with(pos)


@pytest.mark.asyncio
async def test_closed_position_skipped(orchestrator_factory):
    pos = _make_position(fixed_stop=66_500, status="CLOSED")
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    msg = _make_message("005930", {"10": "0000060000"})  # well below stop
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()


@pytest.mark.asyncio
async def test_zero_quantity_position_skipped(orchestrator_factory):
    pos = _make_position(total_qty=0, fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    msg = _make_message("005930", {"10": "0000060000"})
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()


# ---------------------------------------------------------------------------
# Message parsing edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_price_field_logs_warning(orchestrator_factory, caplog):
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[_make_position()])
    msg = _make_message("005930", {})  # no recognized key
    with caplog.at_level("WARNING"):
        await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()
    assert any("price_field_missing" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_unparsable_price_logs_warning(orchestrator_factory, caplog):
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[_make_position()])
    msg = _make_message("005930", {"10": "abc"})
    with caplog.at_level("WARNING"):
        await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()
    assert any("price_parse_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_empty_item_returns_silently(orchestrator_factory):
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[_make_position()])
    msg = _make_message("", {"10": "70000"})
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_not_awaited()


@pytest.mark.asyncio
async def test_alternative_price_field_aliases(orchestrator_factory):
    pos = _make_position(fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    # Use "stck_prpr" alias (3rd in alias list)
    msg = _make_message("005930", {"stck_prpr": "60000"})
    await orch._handle_price_message(msg)
    executor.execute_stop_loss.assert_awaited_once()


# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_on_position_closed_unsubscribes_when_no_positions(
    orchestrator_factory,
):
    orch, pm, _ex, ws, ChannelType = orchestrator_factory(positions=[])
    await orch.subscribe("005930")
    pm.list_for_stock.return_value = []  # no positions → unsubscribe
    await orch.on_position_closed("005930", "pid-1")
    ws.unsubscribe.assert_awaited_once_with(ChannelType.PRICE_TICK, "005930")


@pytest.mark.asyncio
async def test_on_position_closed_keeps_feed_when_other_positions_open(
    orchestrator_factory,
):
    other_pos = _make_position()
    orch, pm, _ex, ws, _Ch = orchestrator_factory(positions=[other_pos])
    await orch.subscribe("005930")
    pm.list_for_stock.return_value = [other_pos]
    await orch.on_position_closed("005930", "pid-2")
    ws.unsubscribe.assert_not_awaited()


@pytest.mark.asyncio
async def test_reevaluate_stock_runs_full_pipeline(orchestrator_factory):
    pos = _make_position(fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    await orch.reevaluate_stock("005930", current_price=60_000)
    executor.execute_stop_loss.assert_awaited_once_with(pos)


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_executor_failure_does_not_propagate(orchestrator_factory, caplog):
    pos = _make_position(fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    executor.execute_stop_loss = AsyncMock(side_effect=RuntimeError("boom"))
    msg = _make_message("005930", {"10": "60000"})
    with caplog.at_level("WARNING"):
        await orch._handle_price_message(msg)  # must not raise
    assert any("executor_failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_calculator_failure_does_not_propagate(orchestrator_factory, caplog):
    pos = _make_position(fixed_stop=66_500)
    orch, _pm, executor, _ws, _Ch = orchestrator_factory(positions=[pos])
    orch._calc = MagicMock()
    orch._calc.on_tick = MagicMock(side_effect=RuntimeError("calc boom"))
    msg = _make_message("005930", {"10": "70000"})
    with caplog.at_level("WARNING"):
        await orch._handle_price_message(msg)  # must not raise
    executor.execute_stop_loss.assert_not_awaited()
    assert any("calc_failed" in r.message for r in caplog.records)
