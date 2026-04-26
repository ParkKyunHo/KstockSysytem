"""Unit tests for ``src/core/v71/vi_monitor.py``.

Spec: 02_TRADING_RULES.md §10
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__VI_MONITOR"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.skills.vi_skill import VIState  # noqa: E402
from src.core.v71.vi_monitor import (  # noqa: E402
    V71ViMonitor,
    ViMonitorContext,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 28, 11, 0)
    )

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.now_value = self.now_value + timedelta(seconds=seconds)

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)

    async def notify(self, **kwargs) -> None:
        self.events.append(kwargs)


def _build(
    *, on_resumed_calls: list[str] | None = None
) -> tuple[V71ViMonitor, FakeNotifier, FakeClock]:
    notifier = FakeNotifier()
    clock = FakeClock()

    async def on_resumed(stock_code: str) -> None:
        if on_resumed_calls is not None:
            on_resumed_calls.append(stock_code)

    ctx = ViMonitorContext(
        notifier=notifier,
        clock=clock,
        on_vi_resumed=on_resumed if on_resumed_calls is not None else None,
    )
    return V71ViMonitor(context=ctx), notifier, clock


STOCK = "005930"


# ---------------------------------------------------------------------------
# State queries
# ---------------------------------------------------------------------------


class TestStateQueries:
    def test_default_state_is_normal(self):
        monitor, _, _ = _build()
        assert monitor.get_state(STOCK) is VIState.NORMAL
        assert monitor.is_vi_active(STOCK) is False
        assert monitor.is_vi_recovered_today(STOCK) is False

    @pytest.mark.asyncio
    async def test_state_after_trigger(self):
        monitor, _, _ = _build()
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        assert monitor.is_vi_active(STOCK) is True
        assert monitor.get_state(STOCK) is VIState.TRIGGERED
        assert monitor.get_last_close_before_vi(STOCK) == 18_500


# ---------------------------------------------------------------------------
# Trigger event
# ---------------------------------------------------------------------------


class TestOnViTriggered:
    @pytest.mark.asyncio
    async def test_emits_high_alert(self):
        monitor, notifier, _ = _build()
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        events = [
            e for e in notifier.events if e.get("event_type") == "VI_TRIGGERED"
        ]
        assert len(events) == 1
        assert events[0]["severity"] == "HIGH"
        assert events[0]["stock_code"] == STOCK

    @pytest.mark.asyncio
    async def test_idempotent_when_already_triggered(self):
        monitor, notifier, _ = _build()
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_500, last_close_before_vi=18_500
        )
        # Only one alert.
        triggers = [
            e for e in notifier.events if e.get("event_type") == "VI_TRIGGERED"
        ]
        assert len(triggers) == 1


# ---------------------------------------------------------------------------
# Resolve event (full TRIGGERED -> RESUMED -> NORMAL flow)
# ---------------------------------------------------------------------------


class TestOnViResolved:
    @pytest.mark.asyncio
    async def test_full_cycle_sets_recovered_today(self):
        monitor, notifier, _ = _build()
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        await monitor.on_vi_resolved(
            STOCK, first_price_after_resume=20_400
        )
        # State auto-resettled to NORMAL.
        assert monitor.get_state(STOCK) is VIState.NORMAL
        # Block flag set.
        assert monitor.is_vi_recovered_today(STOCK) is True
        # Two alerts (trigger + resume).
        kinds = [e.get("event_type") for e in notifier.events]
        assert "VI_TRIGGERED" in kinds
        assert "VI_RESUMED" in kinds

    @pytest.mark.asyncio
    async def test_resume_fires_on_vi_resumed_callback(self):
        called: list[str] = []
        monitor, _, _ = _build(on_resumed_calls=called)
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        await monitor.on_vi_resolved(
            STOCK, first_price_after_resume=20_400
        )
        assert called == [STOCK]

    @pytest.mark.asyncio
    async def test_resume_without_prior_trigger_is_dropped(self):
        monitor, notifier, _ = _build()
        await monitor.on_vi_resolved(
            STOCK, first_price_after_resume=20_400
        )
        # No state change, no alert.
        assert monitor.get_state(STOCK) is VIState.NORMAL
        assert notifier.events == []
        assert monitor.is_vi_recovered_today(STOCK) is False

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_block_auto_resettle(self):
        """An on_vi_resumed crash must not leave us stuck in RESUMED."""
        monitor, notifier, _ = _build()

        async def crashing_resumed(_stock):
            raise RuntimeError("boom")

        ctx = ViMonitorContext(
            notifier=monitor._ctx.notifier,
            clock=monitor._ctx.clock,
            on_vi_resumed=crashing_resumed,
        )
        monitor = V71ViMonitor(context=ctx)
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        await monitor.on_vi_resolved(
            STOCK, first_price_after_resume=20_400
        )
        # Despite the callback crash, state transitioned to NORMAL.
        assert monitor.get_state(STOCK) is VIState.NORMAL
        assert monitor.is_vi_recovered_today(STOCK) is True


# ---------------------------------------------------------------------------
# Daily reset
# ---------------------------------------------------------------------------


class TestDailyReset:
    @pytest.mark.asyncio
    async def test_reset_clears_recovered_today(self):
        monitor, _, _ = _build()
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        await monitor.on_vi_resolved(
            STOCK, first_price_after_resume=20_400
        )
        assert monitor.is_vi_recovered_today(STOCK) is True

        monitor.reset_daily()

        assert monitor.is_vi_recovered_today(STOCK) is False
        assert monitor.get_state(STOCK) is VIState.NORMAL
        assert monitor.get_last_close_before_vi(STOCK) is None

    def test_reset_when_empty_is_noop(self):
        monitor, _, _ = _build()
        monitor.reset_daily()  # no exceptions
        assert monitor.is_vi_recovered_today(STOCK) is False


# ---------------------------------------------------------------------------
# Sync dispatcher (V7.0 bridge)
# ---------------------------------------------------------------------------


class TestSyncDispatcher:
    @pytest.mark.asyncio
    async def test_dispatcher_routes_flag_1_to_triggered(self):
        monitor, _, _ = _build()
        dispatch = monitor.make_sync_dispatcher()
        dispatch(STOCK, 1, 20_000, 18_500)
        # Yield to let the scheduled task complete.
        await asyncio.sleep(0)
        for _ in range(5):
            if monitor.is_vi_active(STOCK):
                break
            await asyncio.sleep(0)
        assert monitor.is_vi_active(STOCK) is True

    @pytest.mark.asyncio
    async def test_dispatcher_routes_flag_2_to_resolved(self):
        monitor, _, _ = _build()
        # First, trigger.
        await monitor.on_vi_triggered(
            STOCK, trigger_price=20_000, last_close_before_vi=18_500
        )
        # Now flag=2.
        dispatch = monitor.make_sync_dispatcher()
        dispatch(STOCK, 2, 20_400, None)
        # Drain.
        for _ in range(10):
            if monitor.get_state(STOCK) is VIState.NORMAL:
                break
            await asyncio.sleep(0)
        assert monitor.is_vi_recovered_today(STOCK) is True

    def test_dispatcher_no_running_loop_logs_only(self):
        """No running loop -- swallow gracefully (V7.0 pipeline must not crash)."""
        monitor, _, _ = _build()
        dispatch = monitor.make_sync_dispatcher()
        dispatch(STOCK, 1, 20_000, 18_500)  # no exception


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_runtime_error_when_disabled(self):
        os.environ["V71_FF__V71__VI_MONITOR"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.vi_monitor"):
                ctx = ViMonitorContext(
                    notifier=FakeNotifier(),
                    clock=FakeClock(),
                )
                V71ViMonitor(context=ctx)
        finally:
            os.environ["V71_FF__V71__VI_MONITOR"] = "true"
            ff.reload()
