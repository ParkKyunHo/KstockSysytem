"""Unit tests for ``src/core/v71/restart_recovery.py``.

Spec:
  - 02_TRADING_RULES.md §13.1 (7-step recovery)
  - 02_TRADING_RULES.md §13.2 (restart frequency monitor, no auto-stop)
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.utils import feature_flags as ff


@pytest.fixture(autouse=True)
def _enable_flags():
    saved = {k: v for k, v in os.environ.items() if k.startswith("V71_FF__")}
    os.environ["V71_FF__V71__BOX_SYSTEM"] = "true"
    os.environ["V71_FF__V71__POSITION_V71"] = "true"
    os.environ["V71_FF__V71__RECONCILIATION_V71"] = "true"
    os.environ["V71_FF__V71__RESTART_RECOVERY"] = "true"
    ff.reload()
    yield
    for k in list(os.environ):
        if k.startswith("V71_FF__"):
            del os.environ[k]
    os.environ.update(saved)
    ff.reload()


from src.core.v71.box.box_manager import V71BoxManager  # noqa: E402
from src.core.v71.position.v71_position_manager import (  # noqa: E402
    V71PositionManager,
)
from src.core.v71.position.v71_reconciler import (  # noqa: E402
    ReconcilerContext,
    V71Reconciler,
)
from src.core.v71.restart_recovery import (  # noqa: E402
    RecoveryContext,
    V71RestartRecovery,
)
from src.core.v71.skills.reconciliation_skill import KiwoomBalance  # noqa: E402

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 28, 9, 0)
    )
    sleeps: list[float] = field(default_factory=list)

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now_value = self.now_value + timedelta(seconds=seconds)

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target

    def advance(self, seconds: float) -> None:
        self.now_value = self.now_value + timedelta(seconds=seconds)


@dataclass
class FakeNotifier:
    events: list[dict] = field(default_factory=list)

    async def notify(self, **kwargs) -> None:
        self.events.append(kwargs)


# ---------------------------------------------------------------------------
# Builder helpers
# ---------------------------------------------------------------------------


def _make_reconciler(pm: V71PositionManager) -> V71Reconciler:
    bm = V71BoxManager()
    notifier = FakeNotifier()
    clock = FakeClock()
    return V71Reconciler(
        context=ReconcilerContext(
            position_manager=pm,
            box_manager=bm,
            notifier=notifier,
            clock=clock,
            list_tracked_for_stock=lambda _s: [],
            end_tracking=_async_noop,
        )
    )


async def _async_noop(*args, **kwargs) -> None:  # noqa: ARG001
    return None


def _ok_async(*, return_value=None) -> Callable[[], Awaitable]:
    async def fn():
        return return_value
    return fn


def _failing_async(exc: Exception) -> Callable[[], Awaitable]:
    async def fn():
        raise exc
    return fn


def _flaky_async(
    *, fail_until_attempt: int, return_value=None
) -> tuple[Callable[[], Awaitable], list[int]]:
    """Async fn that fails the first ``fail_until_attempt - 1`` calls,
    then succeeds. Returns (fn, attempts_log)."""
    attempts: list[int] = []

    async def fn():
        attempts.append(len(attempts) + 1)
        if len(attempts) < fail_until_attempt:
            raise RuntimeError(f"flaky attempt {len(attempts)}")
        return return_value

    return fn, attempts


def _build(
    *,
    connect_db=None,
    refresh_kiwoom=None,
    connect_websocket=None,
    connect_telegram=None,
    cancel_orders=None,
    fetch_balances=None,
    resubscribe=None,
) -> tuple[V71RestartRecovery, FakeNotifier, FakeClock, V71PositionManager,
           dict]:
    pm = V71PositionManager()
    notifier = FakeNotifier()
    clock = FakeClock()
    reconciler = V71Reconciler(
        context=ReconcilerContext(
            position_manager=pm,
            box_manager=V71BoxManager(),
            notifier=notifier,
            clock=clock,
            list_tracked_for_stock=lambda _s: [],
            end_tracking=_async_noop,
        )
    )

    safe_mode = {"entered": 0, "exited": 0}

    def enter():
        safe_mode["entered"] += 1

    def exit_():
        safe_mode["exited"] += 1

    ctx = RecoveryContext(
        reconciler=reconciler,
        notifier=notifier,
        clock=clock,
        connect_db=connect_db or _ok_async(),
        refresh_kiwoom_token=refresh_kiwoom or _ok_async(),
        connect_websocket=connect_websocket or _ok_async(),
        connect_telegram=connect_telegram or _ok_async(),
        cancel_all_pending_orders=cancel_orders or _ok_async(return_value=0),
        fetch_broker_balances=fetch_balances or _ok_async(return_value=[]),
        resubscribe_market_data=resubscribe or _ok_async(return_value=0),
        enter_safe_mode=enter,
        exit_safe_mode=exit_,
    )
    return V71RestartRecovery(context=ctx), notifier, clock, pm, safe_mode


# ---------------------------------------------------------------------------
# Happy-path 7-step
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_full_recovery_success(self):
        recovery, notifier, _, _, safe_mode = _build()
        report = await recovery.run()
        # Step 0 + Step 6
        assert safe_mode["entered"] == 1
        assert safe_mode["exited"] == 1
        # No failures
        assert report.succeeded()
        assert report.failures == []
        # CRITICAL recovery report alert sent
        assert any(
            n["event_type"] == "RECOVERY_COMPLETED"
            and n["severity"] == "CRITICAL"
            for n in notifier.events
        )

    @pytest.mark.asyncio
    async def test_report_records_counts(self):
        recovery, _, _, _, _ = _build(
            cancel_orders=_ok_async(return_value=3),
            resubscribe=_ok_async(return_value=12),
        )
        report = await recovery.run()
        assert report.cancelled_orders == 3
        assert report.resubscribed_count == 12
        assert report.duration_seconds() is not None
        assert report.duration_seconds() >= 0


# ---------------------------------------------------------------------------
# Step 1 retry behavior
# ---------------------------------------------------------------------------


class TestReconnectRetry:
    @pytest.mark.asyncio
    async def test_db_succeeds_on_third_attempt(self):
        flaky_db, attempts = _flaky_async(fail_until_attempt=3)
        recovery, _, clock, _, _ = _build(connect_db=flaky_db)
        report = await recovery.run()
        # 3 attempts (2 fails + 1 success)
        assert len(attempts) == 3
        # 2 sleeps between failed attempts
        assert clock.sleeps.count(1.0) >= 2
        assert report.succeeded()

    @pytest.mark.asyncio
    async def test_db_persistent_failure_records_but_continues(self):
        recovery, _, clock, _, safe_mode = _build(
            connect_db=_failing_async(RuntimeError("db dead")),
        )
        report = await recovery.run()
        # 5 attempts, 4 sleeps between them -> we still proceed
        assert "step1_db" in report.failures
        # Sequence STILL completes -- no auto-stop (Constitution 4)
        assert report.completed_at is not None
        # Safe mode released anyway -- operator handles
        assert safe_mode["exited"] == 1

    @pytest.mark.asyncio
    async def test_websocket_failure_does_not_block_others(self):
        recovery, _, _, _, _ = _build(
            connect_websocket=_failing_async(RuntimeError("ws unreachable")),
        )
        report = await recovery.run()
        assert "step1_websocket" in report.failures
        # DB / Kiwoom / Telegram remained successful (no failure for them)
        assert "step1_db" not in report.failures
        assert "step1_telegram" not in report.failures


# ---------------------------------------------------------------------------
# Step 2 / 3 / 4 failure modes
# ---------------------------------------------------------------------------


class TestStepFailures:
    @pytest.mark.asyncio
    async def test_cancel_orders_failure_recorded(self):
        recovery, _, _, _, _ = _build(
            cancel_orders=_failing_async(RuntimeError("kiwoom 5xx")),
        )
        report = await recovery.run()
        assert any(f.startswith("step2_cancel_orders") for f in report.failures)

    @pytest.mark.asyncio
    async def test_fetch_balances_failure_skips_reconcile(self):
        recovery, _, _, _, _ = _build(
            fetch_balances=_failing_async(RuntimeError("balance api dead")),
        )
        report = await recovery.run()
        assert any(f.startswith("step3_fetch_balances") for f in report.failures)
        assert report.reconciliation_results == []  # never called

    @pytest.mark.asyncio
    async def test_resubscribe_failure_recorded(self):
        recovery, _, _, _, _ = _build(
            resubscribe=_failing_async(RuntimeError("ws subscribe failed")),
        )
        report = await recovery.run()
        assert any(f.startswith("step4_resubscribe") for f in report.failures)


# ---------------------------------------------------------------------------
# Step 3 reconciliation actually runs
# ---------------------------------------------------------------------------


class TestReconciliationStep:
    @pytest.mark.asyncio
    async def test_reconcile_called_with_balances(self):
        # Pre-load a system position so we get a non-E case.
        async def fetch():
            return [
                KiwoomBalance(
                    stock_code="005930", quantity=120, avg_price=18_000
                )
            ]

        recovery, _, clock, pm, _ = _build(fetch_balances=fetch)
        # Add a system position of 100 -- broker shows 120 -> Case A.
        await pm.add_position(
            stock_code="005930", tracked_stock_id="t1", triggered_box_id="b1",
            path_type="PATH_A", quantity=100, weighted_avg_price=18_000,
            opened_at=clock.now(),
        )

        report = await recovery.run()
        assert len(report.reconciliation_results) == 1
        assert report.reconciliation_results[0].case.value == "A"


# ---------------------------------------------------------------------------
# Frequency monitor (§13.2)
# ---------------------------------------------------------------------------


class TestFrequencyMonitor:
    @pytest.mark.asyncio
    async def test_first_restart_no_alert(self):
        recovery, notifier, _, _, _ = _build()
        await recovery.run()
        # Only the RECOVERY_COMPLETED alert (no frequency alert).
        kinds = [n["event_type"] for n in notifier.events]
        assert "RESTART_FREQUENCY_ALERT" not in kinds

    @pytest.mark.asyncio
    async def test_two_restarts_within_hour_emits_high(self):
        recovery, notifier, clock, _, _ = _build()
        await recovery.run()
        clock.advance(60 * 30)  # 30 min later
        await recovery.run()
        # Two-tier alert.
        freq_alerts = [
            n for n in notifier.events
            if n["event_type"] == "RESTART_FREQUENCY_ALERT"
        ]
        assert len(freq_alerts) >= 1
        assert freq_alerts[-1]["severity"] == "HIGH"

    @pytest.mark.asyncio
    async def test_three_restarts_within_hour_emits_critical(self):
        recovery, notifier, clock, _, _ = _build()
        await recovery.run()
        clock.advance(60 * 10)
        await recovery.run()
        clock.advance(60 * 10)
        await recovery.run()
        criticals = [
            n for n in notifier.events
            if n["event_type"] == "RESTART_FREQUENCY_ALERT"
            and n["severity"] == "CRITICAL"
        ]
        assert len(criticals) >= 1

    @pytest.mark.asyncio
    async def test_five_plus_restarts_critical_with_5plus_tier(self):
        recovery, notifier, clock, _, _ = _build()
        for _ in range(5):
            await recovery.run()
            clock.advance(60 * 5)
        # Last alert should mention 5+ tier
        freq_alerts = [
            n for n in notifier.events
            if n["event_type"] == "RESTART_FREQUENCY_ALERT"
        ]
        assert any("5" in n["message"] for n in freq_alerts)

    @pytest.mark.asyncio
    async def test_restart_outside_window_does_not_count(self):
        recovery, notifier, clock, _, _ = _build()
        await recovery.run()
        clock.advance(60 * 60 * 2)  # 2 hours later (outside window)
        await recovery.run()
        # Second run only sees itself in the 1-hour window -> no alert.
        # (Window cutoff is strict: events at exactly the boundary count
        #  but events older are dropped.)
        freq_alerts = [
            n for n in notifier.events
            if n["event_type"] == "RESTART_FREQUENCY_ALERT"
        ]
        assert freq_alerts == []


# ---------------------------------------------------------------------------
# Constitution-4: no auto-stop
# ---------------------------------------------------------------------------


class TestNoAutoStop:
    @pytest.mark.asyncio
    async def test_run_always_returns_report_even_on_total_meltdown(self):
        """Every callback fails -- run() still returns a complete report."""
        recovery, _, _, _, safe_mode = _build(
            connect_db=_failing_async(RuntimeError("dead")),
            refresh_kiwoom=_failing_async(RuntimeError("dead")),
            connect_websocket=_failing_async(RuntimeError("dead")),
            connect_telegram=_failing_async(RuntimeError("dead")),
            cancel_orders=_failing_async(RuntimeError("dead")),
            fetch_balances=_failing_async(RuntimeError("dead")),
            resubscribe=_failing_async(RuntimeError("dead")),
        )
        report = await recovery.run()
        # Run completed.
        assert report.completed_at is not None
        # All step failures recorded.
        assert "step1_db" in report.failures
        assert "step1_kiwoom_oauth" in report.failures
        assert "step1_websocket" in report.failures
        assert "step1_telegram" in report.failures
        assert any(f.startswith("step2") for f in report.failures)
        assert any(f.startswith("step3") for f in report.failures)
        assert any(f.startswith("step4") for f in report.failures)
        # Safe mode released (operator handles from here).
        assert safe_mode["exited"] == 1


# ---------------------------------------------------------------------------
# Feature flag gate
# ---------------------------------------------------------------------------


class TestFlagGate:
    def test_runtime_error_when_disabled(self):
        os.environ["V71_FF__V71__RESTART_RECOVERY"] = "false"
        ff.reload()
        try:
            with pytest.raises(RuntimeError, match="v71.restart_recovery"):
                pm = V71PositionManager()
                ctx = RecoveryContext(
                    reconciler=_make_reconciler(pm),
                    notifier=FakeNotifier(),
                    clock=FakeClock(),
                    connect_db=_ok_async(),
                    refresh_kiwoom_token=_ok_async(),
                    connect_websocket=_ok_async(),
                    connect_telegram=_ok_async(),
                    cancel_all_pending_orders=_ok_async(return_value=0),
                    fetch_broker_balances=_ok_async(return_value=[]),
                    resubscribe_market_data=_ok_async(return_value=0),
                    enter_safe_mode=lambda: None,
                    exit_safe_mode=lambda: None,
                )
                V71RestartRecovery(context=ctx)
        finally:
            os.environ["V71_FF__V71__RESTART_RECOVERY"] = "true"
            ff.reload()
