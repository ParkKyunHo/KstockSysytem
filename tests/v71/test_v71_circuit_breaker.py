"""Unit tests for ``src/core/v71/notification/v71_circuit_breaker.py``.

Spec: 02_TRADING_RULES.md §9.4
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

import pytest

from src.core.v71.notification.v71_circuit_breaker import (
    V71CircuitBreaker,
    V71CircuitState,
)


@dataclass
class FakeClock:
    now_value: datetime = field(
        default_factory=lambda: datetime(2026, 4, 26, 9, 0)
    )

    def now(self) -> datetime:
        return self.now_value

    async def sleep(self, _seconds: float) -> None:
        return None

    async def sleep_until(self, target: datetime) -> None:
        if target > self.now_value:
            self.now_value = target

    def advance(self, **kwargs: int) -> None:
        self.now_value = self.now_value + timedelta(**kwargs)


# ---------------------------------------------------------------------------
# Construction / validation
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_defaults_match_constants(self) -> None:
        from src.core.v71.v71_constants import V71Constants

        cb = V71CircuitBreaker(clock=FakeClock())
        # Internal accessors are not part of the public API, but the
        # behaviour drives off these defaults; pin them via state +
        # threshold count below.
        assert cb.state() is V71CircuitState.CLOSED
        # Trip the breaker by N defaults to assert it ties to the constant.
        for _ in range(
            V71Constants.NOTIFICATION_CIRCUIT_BREAKER_FAILURE_THRESHOLD - 1
        ):
            cb.record_failure()
        assert cb.state() is V71CircuitState.CLOSED
        cb.record_failure()
        assert cb.state() is V71CircuitState.OPEN

    def test_invalid_threshold(self) -> None:
        with pytest.raises(ValueError, match="failure_threshold"):
            V71CircuitBreaker(clock=FakeClock(), failure_threshold=0)
        with pytest.raises(ValueError, match="failure_threshold"):
            V71CircuitBreaker(clock=FakeClock(), failure_threshold=-1)

    def test_invalid_timeout(self) -> None:
        with pytest.raises(ValueError, match="timeout_seconds"):
            V71CircuitBreaker(clock=FakeClock(), timeout_seconds=0)
        with pytest.raises(ValueError, match="timeout_seconds"):
            V71CircuitBreaker(clock=FakeClock(), timeout_seconds=-5)


# ---------------------------------------------------------------------------
# CLOSED -> OPEN
# ---------------------------------------------------------------------------


class TestClosedToOpen:
    def test_below_threshold_stays_closed(self) -> None:
        cb = V71CircuitBreaker(
            clock=FakeClock(), failure_threshold=3, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state() is V71CircuitState.CLOSED
        assert cb.consecutive_failures == 2
        assert cb.opened_at is None

    def test_threshold_trips_open(self) -> None:
        clock = FakeClock()
        cb = V71CircuitBreaker(
            clock=clock, failure_threshold=3, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()  # 3rd -> OPEN
        assert cb.state() is V71CircuitState.OPEN
        assert cb.opened_at == clock.now_value

    def test_can_attempt_false_when_open(self) -> None:
        cb = V71CircuitBreaker(
            clock=FakeClock(), failure_threshold=2, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state() is V71CircuitState.OPEN
        assert cb.can_attempt() is False


# ---------------------------------------------------------------------------
# Recovery: OPEN -> HALF_OPEN -> CLOSED / OPEN
# ---------------------------------------------------------------------------


class TestHalfOpenAndRecovery:
    def test_open_to_half_open_after_timeout(self) -> None:
        clock = FakeClock()
        cb = V71CircuitBreaker(
            clock=clock, failure_threshold=2, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state() is V71CircuitState.OPEN

        # Right at timeout boundary -> HALF_OPEN.
        clock.advance(seconds=30)
        assert cb.state() is V71CircuitState.HALF_OPEN
        assert cb.can_attempt() is True

    def test_half_open_success_returns_to_closed(self) -> None:
        clock = FakeClock()
        cb = V71CircuitBreaker(
            clock=clock, failure_threshold=2, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        clock.advance(seconds=31)
        assert cb.state() is V71CircuitState.HALF_OPEN

        cb.record_success()
        assert cb.state() is V71CircuitState.CLOSED
        assert cb.consecutive_failures == 0
        assert cb.opened_at is None

    def test_half_open_failure_returns_to_open_with_new_timer(self) -> None:
        clock = FakeClock()
        cb = V71CircuitBreaker(
            clock=clock, failure_threshold=2, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        original_open = cb.opened_at

        clock.advance(seconds=31)
        assert cb.state() is V71CircuitState.HALF_OPEN

        clock.advance(seconds=1)
        cb.record_failure()  # probe failed
        assert cb.state() is V71CircuitState.OPEN
        assert cb.opened_at != original_open
        assert cb.opened_at == clock.now_value

    def test_open_record_failure_during_timeout_is_noop(self) -> None:
        clock = FakeClock()
        cb = V71CircuitBreaker(
            clock=clock, failure_threshold=2, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.consecutive_failures == 2

        # Still inside the timeout -- record_failure should not double-count.
        clock.advance(seconds=10)
        cb.record_failure()
        # consecutive_failures remains at threshold (we didn't reopen).
        assert cb.consecutive_failures == 2
        assert cb.state() is V71CircuitState.OPEN

    def test_record_success_in_open_recovers_immediately(self) -> None:
        # Defensive behaviour: if the worker accidentally calls
        # record_success() while OPEN, treat it as recovery (the send
        # actually succeeded somehow). The breaker should not stay
        # stuck OPEN.
        cb = V71CircuitBreaker(
            clock=FakeClock(), failure_threshold=2, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        assert cb.state() is V71CircuitState.OPEN

        cb.record_success()
        assert cb.state() is V71CircuitState.CLOSED
        assert cb.consecutive_failures == 0


# ---------------------------------------------------------------------------
# CLOSED + record_success
# ---------------------------------------------------------------------------


class TestClosedAndSuccess:
    def test_success_resets_running_failures(self) -> None:
        cb = V71CircuitBreaker(
            clock=FakeClock(), failure_threshold=3, timeout_seconds=30
        )
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        assert cb.consecutive_failures == 0
        # Now we have 3 fresh failures available before tripping.
        cb.record_failure()
        cb.record_failure()
        assert cb.state() is V71CircuitState.CLOSED
        cb.record_failure()
        assert cb.state() is V71CircuitState.OPEN
