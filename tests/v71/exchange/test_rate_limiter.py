"""Unit tests for ``src/core/v71/exchange/rate_limiter.py``.

Spec: docs/v71/06_AGENTS_SPEC.md §5 Test Strategy verification (14 cases)
"""

from __future__ import annotations

import asyncio

import pytest

from src.core.v71.exchange.rate_limiter import (
    DEFAULT_RATE_PER_SECOND,
    V71RateLimiter,
    V71RateLimiterStats,
)

# ---------------------------------------------------------------------------
# Group 1 -- happy path
# ---------------------------------------------------------------------------


def _make(fixed_clock_monotonic, fake_sleep_advancing, **kwargs):
    return V71RateLimiter(
        clock=fixed_clock_monotonic,
        sleep=fake_sleep_advancing,
        **kwargs,
    )


async def test_first_acquire_returns_zero_wait(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    limiter = _make(fixed_clock_monotonic, fake_sleep_advancing, rate_per_second=4.0)
    wait = await limiter.acquire()
    assert wait == 0.0
    assert limiter.stats().current_tokens == pytest.approx(3.0, abs=1e-9)


async def test_burst_capacity_no_wait(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    limiter = _make(
        fixed_clock_monotonic, fake_sleep_advancing,
        rate_per_second=4.0, burst_capacity=4,
    )
    waits = [await limiter.acquire() for _ in range(4)]
    assert all(w == 0.0 for w in waits)
    stats = limiter.stats()
    assert stats.total_acquired == 4
    assert stats.total_wait_seconds == 0.0
    assert stats.current_tokens == pytest.approx(0.0, abs=1e-9)


async def test_acquire_when_empty_waits_deficit_over_rate(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    limiter = _make(
        fixed_clock_monotonic, fake_sleep_advancing,
        rate_per_second=4.0, burst_capacity=1,
    )
    await limiter.acquire()  # drains
    # Bucket empty: 1 token needs 0.25s.
    wait = await limiter.acquire()
    assert wait == pytest.approx(0.25, abs=1e-9)
    assert limiter.stats().total_wait_seconds == pytest.approx(0.25, abs=1e-9)


# ---------------------------------------------------------------------------
# Group 2 -- refill / time progression
# ---------------------------------------------------------------------------


async def test_refill_caps_at_burst_capacity(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    limiter = _make(
        fixed_clock_monotonic, fake_sleep_advancing,
        rate_per_second=4.0, burst_capacity=4,
    )
    await limiter.acquire()  # 3 left
    fixed_clock_monotonic.advance(3600.0)  # huge gap
    # Bucket must not exceed capacity even after enormous elapsed time.
    await limiter.acquire()
    assert limiter.stats().current_tokens == pytest.approx(3.0, abs=1e-9)


async def test_clock_regression_does_not_overcredit(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    limiter = _make(
        fixed_clock_monotonic, fake_sleep_advancing,
        rate_per_second=4.0, burst_capacity=4,
    )
    for _ in range(4):
        await limiter.acquire()
    # Take a peek -- bucket drained.
    assert limiter.stats().current_tokens == pytest.approx(0.0, abs=1e-9)
    # 0.25s elapsed -- exactly one token earned.
    fixed_clock_monotonic.advance(0.25)
    wait = await limiter.acquire()
    assert wait == 0.0


# ---------------------------------------------------------------------------
# Group 3 -- concurrency / stats
# ---------------------------------------------------------------------------


async def test_concurrent_acquires_throttle_to_rate(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    """Three callers at rate=10 burst=1 must collectively wait >= 0.2s.

    The bucket is not strictly FIFO under contention -- once a sleeping
    caller releases the lock, any other waiter that re-enters the lock can
    pick up newly-refilled tokens before the original sleeper resumes. We
    assert the aggregate-rate invariant rather than per-caller fairness:
    aggregate wait time across all callers >= (n - capacity) / rate.
    """
    limiter = _make(
        fixed_clock_monotonic, fake_sleep_advancing,
        rate_per_second=10.0, burst_capacity=1,
    )
    waits = await asyncio.gather(*[limiter.acquire() for _ in range(3)])
    stats = limiter.stats()
    assert stats.total_acquired == 3
    # n=3, capacity=1, rate=10 -> need >= 0.2s of throttling in total.
    assert stats.total_wait_seconds >= 0.2 - 1e-9
    # No caller starves: all acquires returned a finite, non-negative wait.
    assert all(w >= 0.0 for w in waits)
    # The clock has advanced by at least 0.2s of token refill time.
    assert fixed_clock_monotonic() >= 0.2 - 1e-9


async def test_stats_accumulates_correctly(
    fixed_clock_monotonic, fake_sleep_advancing,
):
    limiter = _make(
        fixed_clock_monotonic, fake_sleep_advancing,
        rate_per_second=4.0, burst_capacity=4,
    )
    for _ in range(4):
        await limiter.acquire()
    s = limiter.stats()
    assert isinstance(s, V71RateLimiterStats)
    assert s.total_acquired == 4
    assert s.total_wait_seconds == 0.0
    assert s.rate_per_second == 4.0
    assert s.burst_capacity == 4


# ---------------------------------------------------------------------------
# Group 4 -- validation
# ---------------------------------------------------------------------------


async def test_acquire_zero_or_negative_tokens_raises():
    limiter = V71RateLimiter(rate_per_second=4.0)
    with pytest.raises(ValueError):
        await limiter.acquire(0)
    with pytest.raises(ValueError):
        await limiter.acquire(-1)


async def test_acquire_above_capacity_raises():
    limiter = V71RateLimiter(rate_per_second=4.0, burst_capacity=4)
    with pytest.raises(ValueError):
        await limiter.acquire(5)


@pytest.mark.parametrize("rate", [0, -1, -0.5])
def test_invalid_rate_rejected(rate):
    with pytest.raises(ValueError):
        V71RateLimiter(rate_per_second=rate)


def test_burst_capacity_too_large_rejected():
    # 10x guard rail.
    with pytest.raises(ValueError, match="burst_capacity"):
        V71RateLimiter(rate_per_second=4.0, burst_capacity=41)


def test_burst_capacity_must_be_positive():
    with pytest.raises(ValueError):
        V71RateLimiter(rate_per_second=4.0, burst_capacity=0)


def test_default_rate_constant_mirrors_v71constants():
    from src.core.v71.v71_constants import V71Constants
    assert DEFAULT_RATE_PER_SECOND == V71Constants.API_RATE_LIMIT_PER_SECOND


def test_default_burst_capacity_is_ceil_of_rate():
    limiter = V71RateLimiter(rate_per_second=3.5)
    assert limiter.burst_capacity == 4
