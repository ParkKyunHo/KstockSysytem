"""V71RateLimiter -- async token bucket for Kiwoom REST.

Spec sources:
  - KIWOOM_API_ANALYSIS.md "Rate Limit 정확한 값 미공개" -- the documented
    limit is implicit and the user-visible failure is error 1700 ("요청 개수
    초과"). PRD 09_API_SPEC reports a working assumption of ~4.5/sec for live
    and ~0.33/sec for paper; we default to the conservative live value (4/s)
    and let callers tune.
  - 04_ARCHITECTURE.md §0.1 (Constitution rule 5: prefer simple primitives;
    a token bucket is the smallest model that allows momentary bursts while
    still capping the average).
  - 06_AGENTS_SPEC.md §1 review notes (V71-prefix on the public stats type;
    sanity-check on burst capacity vs. rate).

Why a token bucket and not the V7.0 minimum-interval limiter:
  - The V7.0 implementation forces a fixed gap between every call. That is
    correct under steady load but penalises legitimate bursts (recovery scans,
    parallel reconciles). The token bucket caps the *long-run* rate and
    permits short bursts up to the bucket capacity, which matches how Kiwoom
    enforces 1700 in practice (a leaky-bucket-style window).
  - The bucket is still safe at steady state: refilling at ``rate_per_second``
    means the average call rate cannot exceed the configured rate.

Concurrency: a single ``asyncio.Lock`` serialises bucket arithmetic. ``acquire``
releases the lock while sleeping so that token arithmetic can be re-checked
when the next waiter wakes. The limiter caps the *aggregate* call rate but is
**not strictly FIFO** under contention -- once a sleeping caller releases the
lock, any other waiter can re-enter and pick up newly-refilled tokens before
the original sleeper resumes. The aggregate-rate invariant still holds (so no
caller can starve indefinitely under steady arrival), and Kiwoom's typical
sequential usage profile makes per-caller fairness a non-goal for this unit.
A future revision can add an explicit FIFO waiter queue if production traffic
demonstrates starvation under bursty parallel scans.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from src.core.v71.v71_constants import V71Constants
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Defaults (single source of truth = V71Constants -- Harness 3 §3)
# ---------------------------------------------------------------------------

# Mirrors V71Constants.API_RATE_LIMIT_PER_SECOND / _PAPER_PER_SECOND from
# 02_TRADING_RULES.md / KIWOOM_API_ANALYSIS.md. Re-exported here so callers can
# write ``V71RateLimiter()`` without reaching for V71Constants every time, but
# the value still flows through the constants module.
DEFAULT_RATE_PER_SECOND = V71Constants.API_RATE_LIMIT_PER_SECOND
DEFAULT_PAPER_RATE_PER_SECOND = V71Constants.API_RATE_LIMIT_PAPER_PER_SECOND

# Beyond this multiple of ``rate_per_second`` the bucket effectively disables
# throttling -- almost certainly a misconfiguration. Architect's sanity check.
_BURST_CAPACITY_MAX_MULTIPLE = 10


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71RateLimiterStats:
    """Snapshot of the limiter's accumulated activity.

    Useful for status panels (PRD 09_API_SPEC system/status) and tests.
    ``current_tokens`` is the bucket level at snapshot time -- callers should
    not assume it remains valid across awaits.
    """

    total_acquired: int
    total_wait_seconds: float
    current_tokens: float
    rate_per_second: float
    burst_capacity: int


# ---------------------------------------------------------------------------
# Limiter
# ---------------------------------------------------------------------------

ClockFn = Callable[[], float]
SleepFn = Callable[[float], Awaitable[None]]


class V71RateLimiter:
    """Async token bucket for Kiwoom REST throttling.

    Construction is cheap; the bucket starts full so the first ``burst_capacity``
    calls return without waiting. After that the bucket refills at
    ``rate_per_second`` tokens per second.

    Typical wiring:

        limiter = V71RateLimiter(rate_per_second=4.0)
        async def call_kiwoom(...):
            await limiter.acquire()
            return await http.post(...)

    All public methods are coroutine-safe.
    """

    def __init__(
        self,
        *,
        rate_per_second: float = DEFAULT_RATE_PER_SECOND,
        burst_capacity: int | None = None,
        clock: ClockFn | None = None,
        sleep: SleepFn | None = None,
    ) -> None:
        if rate_per_second <= 0:
            raise ValueError("rate_per_second must be > 0")

        if burst_capacity is None:
            burst_capacity = max(1, int(math.ceil(rate_per_second)))
        if burst_capacity <= 0:
            raise ValueError("burst_capacity must be > 0")
        if burst_capacity > rate_per_second * _BURST_CAPACITY_MAX_MULTIPLE:
            raise ValueError(
                f"burst_capacity={burst_capacity} exceeds {_BURST_CAPACITY_MAX_MULTIPLE}x "
                f"rate_per_second={rate_per_second}; refusing to construct silent throttling-off limiter"
            )

        self._rate = float(rate_per_second)
        self._capacity = int(burst_capacity)
        self._clock: ClockFn = clock or time.monotonic
        # Tests that pair a fake clock with deterministic time progression
        # also inject ``sleep`` so the loop does not block on real wall-clock.
        self._sleep: SleepFn = sleep or asyncio.sleep
        self._tokens: float = float(self._capacity)
        self._last_refill: float = self._clock()
        self._lock = asyncio.Lock()
        self._total_acquired = 0
        self._total_wait_seconds = 0.0

    # ----- Public API --------------------------------------------------

    async def acquire(self, tokens: int = 1) -> float:
        """Block until ``tokens`` are available; return seconds spent waiting.

        Raises ``ValueError`` when ``tokens`` is non-positive or exceeds the
        bucket capacity (because the request could never succeed).
        """
        if tokens <= 0:
            raise ValueError("tokens must be > 0")
        if tokens > self._capacity:
            raise ValueError(
                f"tokens={tokens} exceeds burst_capacity={self._capacity}; "
                "increase burst_capacity or split the request"
            )

        wait_total = 0.0
        # The loop covers two edge cases:
        #   1) Many waiters drain the bucket while one of them is sleeping.
        #   2) Clock granularity producing a tiny under-estimate of wait time.
        # In both we re-check under the lock and sleep again if needed.
        while True:
            async with self._lock:
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    self._total_acquired += tokens
                    if wait_total > 0:
                        self._total_wait_seconds += wait_total
                    return wait_total
                deficit = tokens - self._tokens
                wait_for = deficit / self._rate
            # Release the lock before sleeping so other awaiters can also see
            # the refill and join the queue. ``self._sleep`` is the injection
            # seam for deterministic tests that pair a fake clock with a
            # clock-advancing sleep.
            await self._sleep(wait_for)
            wait_total += wait_for

    def stats(self) -> V71RateLimiterStats:
        """Return a snapshot of accumulated activity."""
        return V71RateLimiterStats(
            total_acquired=self._total_acquired,
            total_wait_seconds=self._total_wait_seconds,
            current_tokens=self._tokens,
            rate_per_second=self._rate,
            burst_capacity=self._capacity,
        )

    # ----- Properties --------------------------------------------------

    @property
    def rate_per_second(self) -> float:
        return self._rate

    @property
    def burst_capacity(self) -> int:
        return self._capacity

    # ----- Internal ----------------------------------------------------

    def _refill_locked(self) -> None:
        now = self._clock()
        elapsed = now - self._last_refill
        if elapsed <= 0:
            return
        self._tokens = min(
            self._capacity,
            self._tokens + elapsed * self._rate,
        )
        self._last_refill = now


__all__ = [
    "DEFAULT_PAPER_RATE_PER_SECOND",
    "DEFAULT_RATE_PER_SECOND",
    "V71RateLimiter",
    "V71RateLimiterStats",
]
