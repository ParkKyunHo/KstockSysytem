"""Shared fixtures for ``src/core/v71/exchange/`` tests.

Spec: docs/v71/06_AGENTS_SPEC.md §5 (Test Strategy fixture template)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import pytest

from src.core.v71.exchange.token_manager import KST


@pytest.fixture
def kst() -> timezone:
    return KST


@pytest.fixture
def utc() -> timezone:
    return timezone.utc


@pytest.fixture
def fixed_clock_utc() -> Callable[[], datetime]:
    """A controllable UTC clock. Call ``advance(seconds=N)`` to fast-forward.

    The returned callable is what ``V71TokenManager`` consumes; the bound
    ``advance`` attribute is for the test to manipulate time deterministically.
    """
    state = {"now": datetime(2026, 4, 27, 0, 0, 0, tzinfo=timezone.utc)}

    def _clock() -> datetime:
        return state["now"]

    def _advance(*, seconds: float = 0, minutes: float = 0, hours: float = 0) -> None:
        state["now"] += timedelta(seconds=seconds, minutes=minutes, hours=hours)

    def _set(when: datetime) -> None:
        if when.tzinfo is None:
            raise ValueError("clock target must be tz-aware")
        state["now"] = when

    _clock.advance = _advance  # type: ignore[attr-defined]
    _clock.set = _set  # type: ignore[attr-defined]
    return _clock


@pytest.fixture
def fixed_clock_monotonic() -> Callable[[], float]:
    """A controllable monotonic clock for ``V71RateLimiter``."""
    state = {"now": 0.0}

    def _clock() -> float:
        return state["now"]

    def _advance(seconds: float) -> None:
        state["now"] += seconds

    def _set(value: float) -> None:
        state["now"] = value

    _clock.advance = _advance  # type: ignore[attr-defined]
    _clock.set = _set  # type: ignore[attr-defined]
    return _clock


@pytest.fixture
def fake_sleep_advancing(fixed_clock_monotonic):
    """A paired ``(clock, sleep)`` so the limiter's wait loop terminates.

    The sleep coroutine advances the same monotonic clock by the requested
    duration, so ``_refill_locked`` sees the elapsed time on the next pass.
    """

    async def _sleep(seconds: float) -> None:
        if seconds > 0:
            fixed_clock_monotonic.advance(seconds)
        # Yield once so other coroutines can progress under asyncio.gather.
        await asyncio.sleep(0)

    return _sleep


@pytest.fixture
def make_token_response(kst: timezone) -> Callable[..., dict]:
    """Build a Kiwoom au10001 success response dict."""

    def _build(
        *,
        token: str = "WQJaSAMPLEtoken1234ABCDxyzMOCK",
        token_type: str = "bearer",
        ttl_seconds: int = 86400,
        return_code: int = 0,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        if expires_at is None:
            expires_at = datetime.now(kst) + timedelta(seconds=ttl_seconds)
        return {
            "return_code": return_code,
            "token": token,
            "token_type": token_type,
            "expires_dt": expires_at.strftime("%Y%m%d%H%M%S"),
        }

    return _build


class CallCountingTransport(httpx.MockTransport):
    """A ``MockTransport`` wrapper that counts handler invocations."""

    def __init__(self, handler):
        super().__init__(handler)
        self.calls = 0
        self.requests: list[httpx.Request] = []


@pytest.fixture
def make_transport(make_token_response) -> Callable[..., CallCountingTransport]:
    """Build a counting ``MockTransport`` from a list of response specs.

    Each spec is a dict with optional keys: ``status``, ``json``, ``raise``.
    The handler advances through the list and clamps to the last spec for
    extra calls (so tests can assert "no more than N calls").
    """

    def _build(specs: list[dict] | None = None):
        specs = specs or [{"status": 200, "json": make_token_response()}]
        state = {"i": 0}

        def _handler(request: httpx.Request) -> httpx.Response:
            transport.requests.append(request)
            transport.calls += 1
            idx = min(state["i"], len(specs) - 1)
            state["i"] = min(state["i"] + 1, len(specs) - 1)
            spec = specs[idx]
            exc = spec.get("raise")
            if exc is not None:
                raise exc
            status_code = spec.get("status", 200)
            payload = spec.get("json", {})
            return httpx.Response(status_code=status_code, json=payload)

        transport = CallCountingTransport(_handler)
        return transport

    return _build


@pytest.fixture
async def http_client(make_transport):
    """An ``httpx.AsyncClient`` wired to a default 200 transport."""
    transport = make_transport()
    async with httpx.AsyncClient(transport=transport) as client:
        client._test_transport = transport  # type: ignore[attr-defined]
        yield client
