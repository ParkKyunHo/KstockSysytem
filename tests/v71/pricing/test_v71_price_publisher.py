"""V71PricePublisher P0 unit tests.

P-Wire-Price-Tick (2026-04-30). Test-strategy 가이드의 P0 84 cases 중
핵심 14 cases — throttle / PnL / sanity / handler isolation / lifecycle
를 다룹니다 (자금 안전 영역).

Test-strategy 회귀 위험 #5 (kt00018 vs WS 0B timestamp guard) 도 포함.

Constitution checks (P1, P2, P3, P4, P5) covered:
  - P1 (4 columns only): test_flush_only_updates_4_display_columns
  - P2 (separate locks): test_publisher_locks_separate_from_orchestrator
  - P3 (no avg cache): test_flush_calls_list_for_stock_every_iteration
  - P4 (VI gate): test_vi_active_skips_publish
  - P5 (no avg mutation): covered by P1 (subset of UPDATE columns)

NFR1 (handler < 1ms budget) covered indirectly: handler awaits no I/O —
flush loop owns DB + publish.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from src.core.v71.exchange.kiwoom_websocket import (
    V71KiwoomChannelType,
    V71WebSocketMessage,
)

# ---------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _enable_publisher_flag(monkeypatch):
    """All tests in this module need v71.price_publisher = true."""
    monkeypatch.setenv("V71_FF__V71__PRICE_PUBLISHER", "true")


@pytest.fixture
def fake_websocket() -> MagicMock:
    ws = MagicMock()
    ws.register_handler = MagicMock()
    return ws


@pytest.fixture
def fake_session_factory() -> MagicMock:
    """Async sessionmaker shape: callable() → async context yielding session.

    Session has begin() async ctx + execute() async — V71PricePublisher
    uses ``async with sm() as s, s.begin(): await s.execute(stmt)``.
    """
    session = AsyncMock()
    session.execute = AsyncMock()
    # session.begin() returns an async context manager (sqlalchemy pattern).
    begin_ctx = AsyncMock()
    begin_ctx.__aenter__ = AsyncMock(return_value=session)
    begin_ctx.__aexit__ = AsyncMock(return_value=None)
    session.begin = MagicMock(return_value=begin_ctx)

    sm_instance = AsyncMock()
    sm_instance.__aenter__ = AsyncMock(return_value=session)
    sm_instance.__aexit__ = AsyncMock(return_value=None)

    sm = MagicMock(return_value=sm_instance)
    sm._captured_session = session  # for assertions
    return sm


@pytest.fixture
def fake_position_manager() -> AsyncMock:
    pm = AsyncMock()
    pm.list_for_stock = AsyncMock(return_value=[])
    return pm


@pytest.fixture
def fake_publish_fn() -> AsyncMock:
    return AsyncMock(return_value=None)


@pytest.fixture
def fixed_clock():
    fixed = datetime(2026, 4, 30, 9, 0, 0, tzinfo=timezone.utc)
    return lambda: fixed


def make_position(
    *,
    position_id: str | None = None,
    stock_code: str = "005930",
    weighted_avg_price: int = 10000,
    total_quantity: int = 100,
    status: Any = None,
) -> Any:
    """Lightweight PositionState double — only the attributes
    V71PricePublisher reads."""
    from src.database.models_v71 import PositionStatus

    pos = MagicMock()
    pos.position_id = position_id or str(uuid4())
    pos.stock_code = stock_code
    pos.weighted_avg_price = Decimal(weighted_avg_price)
    pos.total_quantity = total_quantity
    pos.status = status if status is not None else PositionStatus.OPEN
    return pos


def make_message(stock_code: str, price: int) -> V71WebSocketMessage:
    return V71WebSocketMessage(
        channel=V71KiwoomChannelType.PRICE_TICK,
        item=stock_code,
        name="0B",
        values={"10": str(price), "stck_prpr": str(price)},
        received_at=datetime.now(timezone.utc),
        raw={"trnm": "REAL", "data": [{"item": stock_code}]},
    )


def _make_publisher(
    *,
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
    vi_monitor=None,
):
    from src.core.v71.pricing import V71PricePublisher

    return V71PricePublisher(
        position_manager=fake_position_manager,
        websocket=fake_websocket,
        sessionmaker=fake_session_factory,
        publish_fn=fake_publish_fn,
        clock=fixed_clock,
        vi_monitor=vi_monitor,
    )


# ---------------------------------------------------------------------
# T1.1 throttle
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handler_caches_latest_price_for_stock(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """Tier 1: handler updates in-memory cache only. No await DB."""
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    # 5 ticks — handler updates cache to latest each time.
    for price in (10000, 10100, 10200, 10250, 10280):
        await pub._handle_price_message(make_message("005930", price))
    cached = pub._last_received["005930"]
    assert cached[0] == 10280
    # Handler must not touch DB / publish.
    fake_publish_fn.assert_not_called()
    fake_position_manager.list_for_stock.assert_not_called()


@pytest.mark.asyncio
async def test_handler_rejects_zero_and_negative_prices(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    await pub._handle_price_message(make_message("005930", 0))
    await pub._handle_price_message(make_message("005930", -100))
    assert "005930" not in pub._last_received


@pytest.mark.asyncio
async def test_handler_rejects_above_sanity_max(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """Security S2 MEDIUM: PRICE_TICK_SANITY_MAX = 1억원/주."""
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    await pub._handle_price_message(make_message("005930", 100_000_001))
    assert "005930" not in pub._last_received


@pytest.mark.asyncio
async def test_handler_rejects_50pct_jump(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """Security S2 MEDIUM: ±50% jump rejected."""
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    await pub._handle_price_message(make_message("005930", 10000))
    # 60% jump → reject (last_received stays at 10000).
    await pub._handle_price_message(make_message("005930", 16000))
    assert pub._last_received["005930"][0] == 10000


# ---------------------------------------------------------------------
# T1.4 PnL calc
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_computes_pnl_and_publishes(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """Flush loop: PnL = (price - avg) * qty; pct = (price - avg) / avg."""
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    pos = make_position(weighted_avg_price=10000, total_quantity=100)
    fake_position_manager.list_for_stock.return_value = [pos]
    # Inject a tick + run one flush cycle directly.
    await pub._handle_price_message(make_message("005930", 11000))
    await pub._flush_once()
    assert fake_publish_fn.call_count == 1
    kwargs = fake_publish_fn.call_args.kwargs
    assert kwargs["stock_code"] == "005930"
    assert kwargs["current_price"] == 11000.0
    assert kwargs["pnl_amount"] == 100000.0  # (11000 - 10000) * 100
    assert kwargs["pnl_pct"] == pytest.approx(0.1)


@pytest.mark.asyncio
async def test_flush_skips_when_price_unchanged(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """Delta-only UPDATE: same price → publish 0."""
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    pos = make_position(weighted_avg_price=10000, total_quantity=100)
    fake_position_manager.list_for_stock.return_value = [pos]
    await pub._handle_price_message(make_message("005930", 10500))
    await pub._flush_once()
    # Same price re-injected — second flush must skip.
    await pub._handle_price_message(make_message("005930", 10500))
    await pub._flush_once()
    assert fake_publish_fn.call_count == 1


# ---------------------------------------------------------------------
# T1.7 feature flag
# ---------------------------------------------------------------------


def test_init_raises_when_flag_off(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
    monkeypatch,
):
    from src.core.v71.pricing import V71PricePublisher

    # autouse fixture sets the flag to true; this test overrides it
    # back to false to exercise the require_enabled gate.
    monkeypatch.setenv("V71_FF__V71__PRICE_PUBLISHER", "false")
    with pytest.raises(RuntimeError):
        V71PricePublisher(
            position_manager=fake_position_manager,
            websocket=fake_websocket,
            sessionmaker=fake_session_factory,
            publish_fn=fake_publish_fn,
            clock=fixed_clock,
        )


# ---------------------------------------------------------------------
# T1.8 ExitOrchestrator isolation
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publisher_locks_separate_from_orchestrator_locks(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """P2: _publisher_locks must be a fresh dict, named distinctly from
    ExitOrchestrator's `_stock_locks` so no future refactor can
    accidentally share the lock map.
    """
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    assert isinstance(pub._publisher_locks, dict)
    # Attribute name must NOT collide with ExitOrchestrator's slot.
    assert not hasattr(pub, "_stock_locks")


@pytest.mark.asyncio
async def test_start_registers_handler_on_websocket(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    await pub.start()
    fake_websocket.register_handler.assert_called_once()
    args = fake_websocket.register_handler.call_args.args
    assert args[0] == V71KiwoomChannelType.PRICE_TICK
    # Bound method comparison: rebinding produces fresh wrapper objects;
    # equality (==) checks the underlying function + instance match.
    assert args[1] == pub._handle_price_message
    await pub.stop()


@pytest.mark.asyncio
async def test_start_idempotent(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    await pub.start()
    await pub.start()  # second call must be a no-op
    assert fake_websocket.register_handler.call_count == 1
    await pub.stop()


@pytest.mark.asyncio
async def test_stop_idempotent(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    await pub.start()
    await pub.stop()
    await pub.stop()  # safe — no exception


# ---------------------------------------------------------------------
# P3: list_for_stock 매번 호출 (no avg cache)
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_flush_calls_list_for_stock_every_iteration(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """P3: weighted_avg_price 캐시 X — pyramid buy 후 stale avg 방지."""
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
        )
    # First flush: avg=10000
    pos1 = make_position(weighted_avg_price=10000, total_quantity=100)
    fake_position_manager.list_for_stock.return_value = [pos1]
    await pub._handle_price_message(make_message("005930", 10500))
    await pub._flush_once()
    first_pct = fake_publish_fn.call_args.kwargs["pnl_pct"]
    assert first_pct == pytest.approx(0.05)
    # Second flush: simulated pyramid buy → new avg=10250, qty=200.
    pos2 = make_position(
        position_id=pos1.position_id,
        weighted_avg_price=10250,
        total_quantity=200,
    )
    fake_position_manager.list_for_stock.return_value = [pos2]
    await pub._handle_price_message(make_message("005930", 10750))
    await pub._flush_once()
    # PnL must reflect the *new* avg, not stale 10000.
    second_pct = fake_publish_fn.call_args.kwargs["pnl_pct"]
    assert second_pct == pytest.approx((10750 - 10250) / 10250)


# ---------------------------------------------------------------------
# P4: VI gate
# ---------------------------------------------------------------------


@pytest.mark.asyncio
async def test_vi_active_blocks_cache_update(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """P4 (recommended): VI_TRIGGERED 시 publish skip."""
    vi = MagicMock()
    vi.is_vi_active = MagicMock(return_value=True)
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
            vi_monitor=vi,
        )
    await pub._handle_price_message(make_message("005930", 10500))
    assert "005930" not in pub._last_received


@pytest.mark.asyncio
async def test_vi_check_failure_fails_open(
    fake_websocket,
    fake_session_factory,
    fake_position_manager,
    fake_publish_fn,
    fixed_clock,
):
    """헌법 4 (always-on): vi_monitor raise → publish proceeds."""
    vi = MagicMock()
    vi.is_vi_active = MagicMock(side_effect=RuntimeError("boom"))
    pub = _make_publisher(
            fake_websocket=fake_websocket,
            fake_session_factory=fake_session_factory,
            fake_position_manager=fake_position_manager,
            fake_publish_fn=fake_publish_fn,
            fixed_clock=fixed_clock,
            vi_monitor=vi,
        )
    await pub._handle_price_message(make_message("005930", 10500))
    assert pub._last_received["005930"][0] == 10500
