"""Unit tests for ``src/core/v71/box/box_entry_detector.py``.

Spec:
  - 02_TRADING_RULES.md §3.8~§3.11
  - 02_TRADING_RULES.md §4

Phase A Step F follow-up (P-Wire-13): the V7.0 ``CandleSource`` shim
was retired so the detector now subscribes directly to V71CandleManager
and filters by ``timeframe``. Tests use a minimal ``FakeCandleManager``
that exposes the ``register_on_complete`` / ``unregister_on_complete``
surface the detector relies on.
"""

from __future__ import annotations

import contextlib
import os
from datetime import datetime

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_box_system():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_entry_detector import V71BoxEntryDetector  # noqa: E402
from src.core.v71.candle.types import V71Candle as Candle  # noqa: E402
from src.core.v71.skills.box_entry_skill import (  # noqa: E402
    EntryDecision,
    MarketContext,
)
from src.core.v71.v71_constants import V71Timeframe  # noqa: E402
from tests.v71.conftest import FakeBoxManager  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeCandleManager:
    """Minimal stand-in for V71CandleManager exposing the subscriber API."""

    def __init__(self):
        self.subscribers: list = []
        self.unregister_calls: list = []

    def register_on_complete(self, callback) -> None:
        self.subscribers.append(callback)

    def unregister_on_complete(self, callback) -> None:
        self.unregister_calls.append(callback)
        with contextlib.suppress(ValueError):
            self.subscribers.remove(callback)


def _make_candle(
    *,
    stock_code: str = "005930",
    open_: int = 92,
    high: int = 99,
    low: int = 91,
    close: int = 95,
    when: datetime | None = None,
    timeframe: V71Timeframe = V71Timeframe.THREE_MINUTE,
) -> Candle:
    return Candle(
        stock_code=stock_code,
        timeframe=timeframe,
        timestamp=when or datetime(2026, 4, 27, 14, 30),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=1000,
    )


def _ctx(*, current_time: datetime) -> MarketContext:
    return MarketContext(
        is_market_open=True,
        is_vi_active=False,
        is_vi_recovered_today=False,
        current_time=current_time,
    )


def _make_detector(
    *,
    candle_manager=None,
    box_manager=None,
    on_entry=None,
    path_type: str = "PATH_A",
    timeframe: V71Timeframe = V71Timeframe.THREE_MINUTE,
    resolve_tracked_id=None,
):
    """Helper that mirrors the production constructor surface."""
    if on_entry is None:
        async def _noop(decision, box):  # noqa: ARG001
            return None
        on_entry = _noop
    return V71BoxEntryDetector(
        path_type=path_type,
        candle_manager=candle_manager or FakeCandleManager(),
        timeframe_filter=timeframe,
        box_manager=box_manager or FakeBoxManager(),
        on_entry=on_entry,
        resolve_tracked_id=resolve_tracked_id or (lambda _s: None),
        market_context=lambda c: _ctx(current_time=c.timestamp),
    )


# ---------------------------------------------------------------------------
# start() / stop() / subscribe
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_start_subscribes_once(self):
        cm = FakeCandleManager()
        det = _make_detector(candle_manager=cm)
        det.start()
        det.start()  # idempotent
        assert len(cm.subscribers) == 1
        assert cm.subscribers[0] == det._on_bar_complete_async

    def test_stop_unregisters_callback(self):
        cm = FakeCandleManager()
        det = _make_detector(candle_manager=cm)
        det.start()
        assert len(cm.subscribers) == 1
        det.stop()
        assert cm.subscribers == []
        assert cm.unregister_calls == [det._on_bar_complete_async]

    def test_stop_is_idempotent(self):
        cm = FakeCandleManager()
        det = _make_detector(candle_manager=cm)
        det.start()
        det.stop()
        det.stop()  # second call is a no-op
        # Only one unregister actually fires.
        assert cm.unregister_calls == [det._on_bar_complete_async]

    def test_stop_before_start_is_noop(self):
        cm = FakeCandleManager()
        det = _make_detector(candle_manager=cm)
        det.stop()  # never started -- silent
        assert cm.unregister_calls == []


# ---------------------------------------------------------------------------
# _on_bar_complete_async timeframe filter
# ---------------------------------------------------------------------------


class TestTimeframeFilter:
    @pytest.mark.asyncio
    async def test_path_a_skips_daily_candle(self):
        bm = FakeBoxManager()
        await bm.create_box(
            tracked_stock_id="tracked-001",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        called: list[str] = []

        async def on_entry(decision, box):  # noqa: ARG001
            called.append(box.id)
            return "ok"

        det = _make_detector(
            box_manager=bm,
            path_type="PATH_A",
            timeframe=V71Timeframe.THREE_MINUTE,
            on_entry=on_entry,
            resolve_tracked_id=lambda _s: "tracked-001",
        )
        # Daily candle dispatched to a 3-min detector -- silent skip.
        daily = _make_candle(timeframe=V71Timeframe.DAILY)
        await det._on_bar_complete_async(daily)
        assert called == []

    @pytest.mark.asyncio
    async def test_path_b_skips_three_minute_candle(self):
        bm = FakeBoxManager()
        det = _make_detector(
            box_manager=bm,
            path_type="PATH_B",
            timeframe=V71Timeframe.DAILY,
            resolve_tracked_id=lambda _s: "tracked-001",
        )
        await det._on_bar_complete_async(
            _make_candle(timeframe=V71Timeframe.THREE_MINUTE),
        )
        # No assertion needed beyond "did not raise"; silent skip.

    @pytest.mark.asyncio
    async def test_matching_timeframe_runs_check_entry(self):
        bm = FakeBoxManager()
        await bm.create_box(
            tracked_stock_id="tracked-001",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        seen: list[str] = []

        async def on_entry(decision, box):  # noqa: ARG001
            seen.append(decision.reason)
            return "ok"

        det = _make_detector(
            box_manager=bm,
            path_type="PATH_A",
            timeframe=V71Timeframe.THREE_MINUTE,
            on_entry=on_entry,
            resolve_tracked_id=lambda _s: "tracked-001",
        )
        # Prime prev.
        await det._on_bar_complete_async(
            _make_candle(open_=92, high=98, low=91, close=95),
        )
        # Second bar with PULLBACK conditions -> dispatch.
        await det._on_bar_complete_async(
            _make_candle(open_=95, high=99, low=94, close=97),
        )
        assert seen == ["PULLBACK_A_TRIGGERED"]


# ---------------------------------------------------------------------------
# check_entry routing
# ---------------------------------------------------------------------------


class TestCheckEntryRouting:
    @pytest.mark.asyncio
    async def test_unresolved_stock_returns_empty(self):
        det = _make_detector(resolve_tracked_id=lambda _s: None)
        assert await det.check_entry(_make_candle()) == []

    @pytest.mark.asyncio
    async def test_no_waiting_boxes_returns_empty(self):
        bm = FakeBoxManager()
        det = _make_detector(
            box_manager=bm, resolve_tracked_id=lambda _s: "tracked-001",
        )
        assert await det.check_entry(_make_candle()) == []

    @pytest.mark.asyncio
    async def test_pullback_a_two_bars_dispatches(self):
        """First bar caches; second bar (with first as prev) triggers."""
        bm = FakeBoxManager()
        await bm.create_box(
            tracked_stock_id="tracked-001",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )
        dispatched: list[tuple[EntryDecision, str]] = []

        async def on_entry(decision, box):
            dispatched.append((decision, box.id))
            return "ok"

        det = _make_detector(
            box_manager=bm, on_entry=on_entry,
            resolve_tracked_id=lambda _s: "tracked-001",
        )

        bar1 = _make_candle(open_=92, high=98, low=91, close=95)
        out1 = await det.check_entry(bar1)
        assert out1 == []
        assert dispatched == []

        bar2 = _make_candle(open_=95, high=99, low=94, close=97)
        out2 = await det.check_entry(bar2)
        assert len(out2) == 1
        assert len(dispatched) == 1
        assert dispatched[0][0].reason == "PULLBACK_A_TRIGGERED"

    @pytest.mark.asyncio
    async def test_skips_box_with_mismatched_path(self):
        bm = FakeBoxManager()
        await bm.create_box(
            tracked_stock_id="tracked-001",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_B",  # daily, but detector serves PATH_A
        )
        called: list[str] = []

        async def on_entry(decision, box):  # noqa: ARG001
            called.append(box.id)

        det = _make_detector(
            box_manager=bm, on_entry=on_entry,
            resolve_tracked_id=lambda _s: "tracked-001",
        )
        # path-A detector queries list_waiting_for_tracked(tracked, PATH_A)
        # so PATH_B boxes are filtered upstream and never seen.
        out = await det.check_entry(_make_candle())
        assert out == []
        assert called == []

    @pytest.mark.asyncio
    async def test_callback_exception_logged_as_type_only(self, caplog):
        """Security M2: traceback must not be logged (could echo
        Bearer/Authorization in nested KiwoomAPIError bodies)."""
        import logging as _logging

        bm = FakeBoxManager()
        await bm.create_box(
            tracked_stock_id="tracked-001",
            upper_price=100,
            lower_price=90,
            position_size_pct=10.0,
            strategy_type="PULLBACK",
            path_type="PATH_A",
        )

        async def flaky(decision, box):  # noqa: ARG001
            raise RuntimeError("simulated_executor_crash")

        det = _make_detector(
            box_manager=bm, on_entry=flaky,
            resolve_tracked_id=lambda _s: "tracked-001",
        )
        # Prime prev.
        await det.check_entry(
            _make_candle(open_=92, high=98, low=91, close=95),
        )
        with caplog.at_level(_logging.WARNING):
            out = await det.check_entry(
                _make_candle(open_=95, high=99, low=94, close=97),
            )
        assert out == []
        assert any(
            "on_entry callback failed" in r.message
            and "RuntimeError" in r.message
            and "simulated_executor_crash" not in r.message
            for r in caplog.records
        )
