"""Notification circuit breaker (P4.1).

Spec: 02_TRADING_RULES.md §9.4

State machine::

    CLOSED ----3 fails----> OPEN
       ^                     |
       | 1 success           | 30s timeout
       |                     v
       +------ HALF_OPEN ----+
                  |
                  +-- 1 fail --> OPEN

Behaviour:
  - CLOSED: every attempt is allowed; success keeps it CLOSED, failures
    accumulate.
  - OPEN: attempts are *denied* until the timeout elapses; the queue
    keeps CRITICAL/HIGH and ages out MEDIUM/LOW.
  - HALF_OPEN: a single attempt is allowed (probe). Success -> CLOSED
    (counter reset). Failure -> OPEN (30s timer restarts).

Notes:
  - Independent of the V7.0 :class:`TelegramBot`'s own internal breaker
    (5 / 5min). The V7.1 service-level breaker is what governs queue
    behaviour; the V7.0 one is a redundant outer ring.
  - Pure logic; no I/O. The clock is injected so unit tests are
    deterministic.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum

from src.core.v71.strategies.v71_buy_executor import Clock
from src.core.v71.v71_constants import V71Constants


class V71CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class V71CircuitBreaker:
    """Tiny FSM around (failure_count, opened_at).

    Thread-safety: the breaker is consulted only from the worker
    coroutine (single producer for state transitions). Read-only queries
    such as :meth:`state` may run from a different coroutine; they avoid
    side-effects beyond the implicit ``CLOSED`` snapshot.
    """

    def __init__(
        self,
        *,
        clock: Clock,
        failure_threshold: int | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        self._clock = clock
        self._failure_threshold = (
            failure_threshold
            if failure_threshold is not None
            else V71Constants.NOTIFICATION_CIRCUIT_BREAKER_FAILURE_THRESHOLD
        )
        self._timeout_seconds = (
            timeout_seconds
            if timeout_seconds is not None
            else V71Constants.NOTIFICATION_CIRCUIT_BREAKER_TIMEOUT_SECONDS
        )
        if self._failure_threshold <= 0:
            raise ValueError("failure_threshold must be > 0")
        if self._timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be > 0")

        self._state: V71CircuitState = V71CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._opened_at: datetime | None = None

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def state(self) -> V71CircuitState:
        """Current state, lazily transitioning OPEN -> HALF_OPEN on timeout."""
        if self._state is V71CircuitState.OPEN and self._timeout_elapsed():
            self._state = V71CircuitState.HALF_OPEN
        return self._state

    def can_attempt(self) -> bool:
        """True iff the next send may proceed.

        OPEN with the timeout still ticking returns False; OPEN with the
        timeout expired transitions to HALF_OPEN and returns True (the
        probe). HALF_OPEN behaves the same as CLOSED for this query (a
        probe is allowed).
        """
        return self.state() is not V71CircuitState.OPEN

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def opened_at(self) -> datetime | None:
        return self._opened_at

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def record_success(self) -> None:
        """Successful delivery -> CLOSED + counter reset."""
        # Always promote to CLOSED on success: this is the
        # CLOSED <- (CLOSED | HALF_OPEN | OPEN expired) edge.
        self._state = V71CircuitState.CLOSED
        self._consecutive_failures = 0
        self._opened_at = None

    def record_failure(self) -> None:
        """Failed delivery -> increment counter; possibly trip OPEN.

        - From CLOSED: increment counter; ``>= threshold`` flips to OPEN.
        - From HALF_OPEN: any failure flips back to OPEN (timer restarts).
        - From OPEN (still in timeout): no-op (we shouldn't be sending).
        """
        if self._state is V71CircuitState.OPEN and not self._timeout_elapsed():
            # Defensive: shouldn't be called while OPEN, but don't double-count.
            return

        if self._state is V71CircuitState.HALF_OPEN:
            # Probe failed -> back to OPEN, timer restarts. Counter stays
            # at the threshold value (we never re-armed it).
            self._state = V71CircuitState.OPEN
            self._opened_at = self._clock.now()
            return

        # CLOSED path (or HALF_OPEN that we just transitioned to via
        # state(); already handled above).
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold:
            self._state = V71CircuitState.OPEN
            self._opened_at = self._clock.now()

    # ------------------------------------------------------------------

    def _timeout_elapsed(self) -> bool:
        if self._opened_at is None:
            return True
        elapsed = self._clock.now() - self._opened_at
        return elapsed >= timedelta(seconds=self._timeout_seconds)


__all__ = ["V71CircuitState", "V71CircuitBreaker"]
