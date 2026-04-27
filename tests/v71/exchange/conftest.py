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


# ---------------------------------------------------------------------------
# Kiwoom client fixtures (P5-Kiwoom-2)
# ---------------------------------------------------------------------------


@pytest.fixture
def make_kiwoom_response() -> Callable[..., dict]:
    """Build a Kiwoom REST response spec for ``CallCountingTransport``."""

    def _build(
        *,
        return_code: int = 0,
        return_msg: str = "OK",
        data: dict | None = None,
        cont_yn: str = "N",
        next_key: str = "",
        status: int = 200,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"return_code": return_code, "return_msg": return_msg}
        if data:
            body.update(data)
        return {
            "status": status,
            "json": body,
            "headers": {"cont-yn": cont_yn, "next-key": next_key},
        }

    return _build


class _RecordingTransport(httpx.MockTransport):
    """``MockTransport`` that records each request + applies optional headers."""

    def __init__(self, specs: list[dict[str, Any]]) -> None:
        self.specs = specs
        self.calls: int = 0
        self.requests: list[httpx.Request] = []
        super().__init__(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        idx = min(self.calls, len(self.specs) - 1)
        self.calls += 1
        spec = self.specs[idx]
        if "raise" in spec and spec["raise"] is not None:
            raise spec["raise"]
        status = spec.get("status", 200)
        body = spec.get("json", {})
        headers = spec.get("headers", {})
        return httpx.Response(status_code=status, json=body, headers=headers)


@pytest.fixture
def make_kiwoom_transport():
    """Build a recording ``MockTransport`` from a list of Kiwoom response specs."""

    def _build(specs: list[dict[str, Any]]) -> _RecordingTransport:
        return _RecordingTransport(specs)

    return _build


@pytest.fixture
def fake_token_manager():
    """AsyncMock-backed V71TokenManager stand-in returning a fixed token."""

    from unittest.mock import AsyncMock

    manager = AsyncMock()
    manager.get_token = AsyncMock(return_value="TKN_FIXTURE_TOKEN_1234ABCD")
    return manager


@pytest.fixture
def fake_rate_limiter():
    """AsyncMock-backed V71RateLimiter stand-in (acquire returns 0.0)."""

    from unittest.mock import AsyncMock

    limiter = AsyncMock()
    limiter.acquire = AsyncMock(return_value=0.0)
    return limiter


@pytest.fixture
def make_kiwoom_client(make_kiwoom_transport, fake_token_manager, fake_rate_limiter):
    """Wire a ``V71KiwoomClient`` against a recording transport."""

    from src.core.v71.exchange.kiwoom_client import V71KiwoomClient

    def _build(specs=None, *, base_url="https://api.kiwoom.com"):
        transport = make_kiwoom_transport(specs or [{"status": 200, "json": {"return_code": 0, "return_msg": "OK"}, "headers": {"cont-yn": "N", "next-key": ""}}])
        http = httpx.AsyncClient(transport=transport, base_url=base_url)
        client = V71KiwoomClient(
            token_manager=fake_token_manager,
            rate_limiter=fake_rate_limiter,
            http_client=http,
            base_url=base_url,
        )
        return client, transport, fake_token_manager, fake_rate_limiter

    return _build
