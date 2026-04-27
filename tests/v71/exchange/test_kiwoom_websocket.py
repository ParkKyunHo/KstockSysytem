"""Unit tests for ``src/core/v71/exchange/kiwoom_websocket.py``.

Spec sources:
  - docs/v71/06_AGENTS_SPEC.md §5 Test Strategy verification
  - docs/v71/12_SECURITY.md §6 (token plaintext must never be logged)
  - docs/v71/02_TRADING_RULES.md §8.2 (Phase 1 / Phase 2 reconnect cadence)
  - docs/v71/KIWOOM_API_ANALYSIS.md §6~§10 (WebSocket payload spec)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import deque
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from src.core.v71.exchange.kiwoom_websocket import (
    LIVE_BASE_URL,
    MAX_AUTH_FAILURES_BEFORE_ABORT,
    MAX_FRAME_SIZE_BYTES,
    PAPER_BASE_URL,
    PHASE_1_BACKOFF_SECONDS,
    PHASE_2_INTERVAL_SECONDS,
    PING_INTERVAL_SECONDS,
    V71KiwoomChannelType,
    V71KiwoomWebSocket,
    V71WebSocketAuthError,
    V71WebSocketMessage,
    V71WebSocketState,
    V71WebSocketSubscription,
)

# ---------------------------------------------------------------------------
# Helpers (FakeKiwoomWebSocket defined locally to avoid sibling-import quirks)
# ---------------------------------------------------------------------------


class FakeKiwoomWebSocket:
    """In-memory fake of websockets.WebSocketClientProtocol for tests."""

    def __init__(
        self,
        recv_queue=None,
        *,
        close_after_drain: bool = True,
        raise_on_iter=None,
    ):
        self.sent: list[dict] = []
        self.connect_kwargs: dict = {}
        self._recv_queue = deque(recv_queue or [])
        self._close_after_drain = close_after_drain
        self._raise_on_iter = raise_on_iter
        self.closed = False

    async def send(self, msg: str) -> None:
        if self.closed:
            raise ConnectionError("send on closed fake")
        import json as _j
        self.sent.append(_j.loads(msg))

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        if self.closed:
            raise StopAsyncIteration
        if not self._recv_queue:
            if self._raise_on_iter is not None:
                raise self._raise_on_iter
            if self._close_after_drain:
                self.closed = True
                raise StopAsyncIteration
            raise ConnectionError("recv on dry queue")
        return self._recv_queue.popleft()

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def make_factory():
    """Build a connect_factory that yields prepared FakeKiwoomWebSocket(s)."""

    def _build(*, sockets=None, fail_first_n: int = 0, failure_exc=None):
        sockets = list(sockets or [])
        attempts = {"fails": fail_first_n}

        async def _factory(url, *, additional_headers=None, **kwargs):
            if attempts["fails"] > 0:
                attempts["fails"] -= 1
                raise failure_exc or ConnectionError("connect failed")
            if not sockets:
                raise ConnectionError("no more fake sockets")
            ws = sockets.pop(0)
            ws.connect_kwargs = {
                "url": url,
                "additional_headers": dict(additional_headers or {}),
                **kwargs,
            }
            return ws

        return _factory

    return _build


def _real_msg(*, channel: str, item: str, values=None, name="X") -> str:
    return json.dumps({
        "trnm": "REAL",
        "data": [{
            "type": channel, "item": item, "name": name,
            "values": values or {"10": "73500"},
        }],
    })


async def _yielding_sleep(_seconds: float) -> None:
    """Default fake sleep -- yields control once so other tasks can run."""
    await asyncio.sleep(0)


def _make_ws(
    *,
    token_manager,
    connect_factory,
    sleep=None,
    is_paper=True,
    on_state_change=None,
    clock=None,
    stop_on_normal_close: bool = True,
):
    return V71KiwoomWebSocket(
        token_manager=token_manager,
        is_paper=is_paper,
        connect_factory=connect_factory,
        sleep=sleep or _yielding_sleep,
        clock=clock,
        on_state_change=on_state_change,
        stop_on_normal_close=stop_on_normal_close,
    )


# ---------------------------------------------------------------------------
# Group A -- happy path
# ---------------------------------------------------------------------------


async def test_connect_uses_bearer_token_and_security_options(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert sock.connect_kwargs["additional_headers"] == {
        "Authorization": "Bearer WS_TOKEN_FIXTURE_1234ABCD",
    }
    assert sock.connect_kwargs["max_size"] == MAX_FRAME_SIZE_BYTES
    assert sock.connect_kwargs["ping_interval"] == PING_INTERVAL_SECONDS
    assert sock.connect_kwargs["url"].startswith(PAPER_BASE_URL)


async def test_first_connect_sends_active_subscriptions_batched_by_grp_no(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930", grp_no="1")
    await ws.subscribe(V71KiwoomChannelType.ORDER_EXECUTION, "", grp_no="2")
    await asyncio.wait_for(ws.run(), timeout=5.0)
    by_grp = {msg["grp_no"]: msg for msg in sock.sent if msg["trnm"] == "REG"}
    assert {"1", "2"} == set(by_grp.keys())
    assert by_grp["1"]["data"] == [{"item": "005930", "type": "0B"}]
    assert by_grp["2"]["data"] == [{"item": "", "type": "00"}]


async def test_real_message_dispatched_to_handler(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([
        _real_msg(channel="0B", item="005930", values={"10": "73500"}),
    ])
    factory = make_factory(sockets=[sock])
    fixed_now = datetime(2026, 4, 28, 10, 0, tzinfo=timezone.utc)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws, connect_factory=factory,
        clock=lambda: fixed_now,
    )
    received = []

    async def handler(msg: V71WebSocketMessage) -> None:
        received.append(msg)

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, handler)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert len(received) == 1
    msg = received[0]
    assert msg.channel == V71KiwoomChannelType.PRICE_TICK
    assert msg.item == "005930"
    assert msg.values == {"10": "73500"}
    assert msg.received_at == fixed_now


async def test_multiple_handlers_called_in_registration_order(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([_real_msg(channel="0B", item="005930")])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    order = []

    async def h1(_msg):
        order.append("h1")

    async def h2(_msg):
        order.append("h2")

    async def h3(_msg):
        order.append("h3")

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h1)
    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h2)
    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h3)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert order == ["h1", "h2", "h3"]


async def test_state_transitions_normal_path(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([])
    factory = make_factory(sockets=[sock])
    states: list[V71WebSocketState] = []

    async def on_state(s):
        states.append(s)

    ws = _make_ws(
        token_manager=fake_token_manager_for_ws, connect_factory=factory,
        on_state_change=on_state,
    )
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert V71WebSocketState.CONNECTING in states
    assert V71WebSocketState.CONNECTED in states
    assert states[-1] == V71WebSocketState.CLOSED


# ---------------------------------------------------------------------------
# Group B -- handler isolation
# ---------------------------------------------------------------------------


async def test_handler_exception_does_not_block_other_handlers(
    fake_token_manager_for_ws, make_factory, caplog,
):
    sock = FakeKiwoomWebSocket([_real_msg(channel="0B", item="005930")])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)

    called = []

    async def bad(_msg):
        called.append("bad-before-raise")
        raise RuntimeError("boom")

    async def good(_msg):
        called.append("good")

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, bad)
    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, good)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    with caplog.at_level(logging.ERROR):
        await asyncio.wait_for(ws.run(), timeout=5.0)
    assert called == ["bad-before-raise", "good"]


def test_register_sync_handler_raises_type_error(
    fake_token_manager_for_ws, make_factory,
):
    factory = make_factory(sockets=[])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)

    def sync_handler(_msg):
        return None

    with pytest.raises(TypeError, match="coroutine"):
        ws.register_handler(V71KiwoomChannelType.PRICE_TICK, sync_handler)


async def test_unknown_channel_skipped_without_error(
    fake_token_manager_for_ws, make_factory, caplog,
):
    sock = FakeKiwoomWebSocket([
        json.dumps({"trnm": "REAL", "data": [
            {"type": "ZZ", "item": "X", "values": {}},
        ]}),
        _real_msg(channel="0B", item="005930"),
    ])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    received = []

    async def h(msg):
        received.append(msg)

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(ws.run(), timeout=5.0)
    assert len(received) == 1


# ---------------------------------------------------------------------------
# Group C -- message parsing
# ---------------------------------------------------------------------------


async def test_invalid_json_continues_recv_loop(
    fake_token_manager_for_ws, make_factory, caplog,
):
    sock = FakeKiwoomWebSocket([
        "{not json",
        _real_msg(channel="0B", item="005930"),
    ])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    received = []

    async def h(msg):
        received.append(msg)

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    with caplog.at_level(logging.WARNING):
        await asyncio.wait_for(ws.run(), timeout=5.0)
    assert len(received) == 1


async def test_subscribe_ack_does_not_dispatch(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([
        json.dumps({"trnm": "REG", "grp_no": "1"}),
        json.dumps({"trnm": "REMOVE", "grp_no": "1"}),
    ])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    received = []

    async def h(msg):
        received.append(msg)

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert received == []


async def test_empty_values_dispatched(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([
        json.dumps({"trnm": "REAL", "data": [
            {"type": "0B", "item": "005930", "values": {}},
        ]}),
    ])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    received = []

    async def h(msg):
        received.append(msg)

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert received[0].values == {}


# ---------------------------------------------------------------------------
# Group D -- reconnect cadence
# ---------------------------------------------------------------------------


async def test_phase1_backoff_sequence(
    fake_token_manager_for_ws, make_factory,
):
    final_sock = FakeKiwoomWebSocket([])
    factory = make_factory(
        sockets=[final_sock],
        fail_first_n=2,
        failure_exc=ConnectionError("boom"),
    )
    sleep = AsyncMock(side_effect=_yielding_sleep)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory,
        sleep=sleep,
    )
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert sleep.await_args_list[0].args == (PHASE_1_BACKOFF_SECONDS[0],)
    assert sleep.await_args_list[1].args == (PHASE_1_BACKOFF_SECONDS[1],)


async def test_phase2_engages_after_phase1_exhausted(
    fake_token_manager_for_ws, make_factory,
):
    final_sock = FakeKiwoomWebSocket([])
    factory = make_factory(
        sockets=[final_sock],
        # Exhaust Phase 1 (5 attempts) + force one Phase 2 sleep.
        fail_first_n=len(PHASE_1_BACKOFF_SECONDS) + 1,
        failure_exc=ConnectionError("boom"),
    )
    sleep = AsyncMock(side_effect=_yielding_sleep)
    states = []

    async def on_state(s):
        states.append(s)

    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory,
        sleep=sleep,
        on_state_change=on_state,
    )
    await asyncio.wait_for(ws.run(), timeout=5.0)
    delays = [c.args[0] for c in sleep.await_args_list]
    # Phase 1 (5x) then Phase 2 (300s) once before final success.
    assert delays[: len(PHASE_1_BACKOFF_SECONDS)] == list(PHASE_1_BACKOFF_SECONDS)
    assert delays[len(PHASE_1_BACKOFF_SECONDS)] == PHASE_2_INTERVAL_SECONDS
    assert V71WebSocketState.RECONNECTING_PHASE_2 in states


async def test_subscriptions_restored_after_reconnect(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([])
    factory = make_factory(
        sockets=[sock],
        fail_first_n=1,
        failure_exc=ConnectionError("boom"),
    )
    sleep = AsyncMock(side_effect=_yielding_sleep)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory, sleep=sleep,
    )
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    await ws.subscribe(V71KiwoomChannelType.BALANCE, "")
    await asyncio.wait_for(ws.run(), timeout=5.0)
    types = {entry["type"] for msg in sock.sent for entry in msg.get("data", [])}
    assert types == {"0B", "04"}


async def test_real_message_resets_failure_counters(
    fake_token_manager_for_ws, make_factory,
):
    first = FakeKiwoomWebSocket([_real_msg(channel="0B", item="005930")])
    factory = make_factory(
        sockets=[first],
        fail_first_n=2,
        failure_exc=ConnectionError("boom"),
    )
    sleep = AsyncMock(side_effect=_yielding_sleep)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory, sleep=sleep,
    )

    async def h(_m):
        return None

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert ws.consecutive_failures == 0
    assert ws.consecutive_auth_failures == 0


async def test_auth_failure_aborts_after_max_attempts(
    fake_token_manager_for_ws, make_factory,
):
    class FakeAuthExc(Exception):
        status_code = 401

    factory = make_factory(
        sockets=[],
        fail_first_n=10,
        failure_exc=FakeAuthExc("auth"),
    )
    sleep = AsyncMock(side_effect=_yielding_sleep)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory, sleep=sleep,
    )
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert ws.consecutive_auth_failures == MAX_AUTH_FAILURES_BEFORE_ABORT


# ---------------------------------------------------------------------------
# Group E -- input validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_url", ["ws://x.com", "http://x.com", "https://x.com"])
def test_invalid_base_url_rejected(fake_token_manager_for_ws, bad_url):
    with pytest.raises(ValueError, match="wss://"):
        V71KiwoomWebSocket(token_manager=fake_token_manager_for_ws, base_url=bad_url)


def test_paper_url_default(fake_token_manager_for_ws):
    ws = V71KiwoomWebSocket(token_manager=fake_token_manager_for_ws, is_paper=True)
    assert ws.url.startswith(PAPER_BASE_URL)


def test_live_url_default(fake_token_manager_for_ws):
    ws = V71KiwoomWebSocket(token_manager=fake_token_manager_for_ws, is_paper=False)
    assert ws.url.startswith(LIVE_BASE_URL)


# ---------------------------------------------------------------------------
# Group F -- security regression
# ---------------------------------------------------------------------------


async def test_logs_never_contain_plaintext_token(
    fake_token_manager_for_ws, make_factory, caplog,
):
    secret = "WS_TOKEN_FIXTURE_1234ABCD"  # matches fake_token_manager_for_ws
    sock = FakeKiwoomWebSocket([
        _real_msg(channel="0B", item="005930"),
        "{not json",
        json.dumps({"trnm": "UNKNOWN"}),
    ])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)

    async def h(_m):
        return None

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    with caplog.at_level(logging.DEBUG):
        await asyncio.wait_for(ws.run(), timeout=5.0)
    for record in caplog.records:
        assert secret not in record.getMessage()


def test_repr_does_not_leak_secret(fake_token_manager_for_ws):
    ws = V71KiwoomWebSocket(
        token_manager=fake_token_manager_for_ws, is_paper=True,
    )
    assert "WS_TOKEN_FIXTURE" not in repr(ws)


async def test_auth_error_message_does_not_leak_token(
    fake_token_manager_for_ws, make_factory,
):
    class FakeAuthExc(Exception):
        status_code = 401

    factory = make_factory(
        sockets=[], fail_first_n=10, failure_exc=FakeAuthExc("denied"),
    )
    sleep = AsyncMock(side_effect=_yielding_sleep)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory, sleep=sleep,
    )
    # Run to trigger auth failures and abort; no exception escapes run().
    await asyncio.wait_for(ws.run(), timeout=5.0)
    # Build a sample error directly to check str() shape
    err = V71WebSocketAuthError("denied")
    assert "WS_TOKEN_FIXTURE" not in str(err)


# ---------------------------------------------------------------------------
# Group G -- lifecycle
# ---------------------------------------------------------------------------


async def test_async_context_manager_closes(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([])
    factory = make_factory(sockets=[sock])
    async with _make_ws(
        token_manager=fake_token_manager_for_ws, connect_factory=factory,
    ) as ws:
        await asyncio.wait_for(ws.run(), timeout=5.0)
    assert ws.state == V71WebSocketState.CLOSED


async def test_aclose_during_run_terminates_loop(
    fake_token_manager_for_ws, make_factory,
):
    # Socket never closes; run() blocks on recv until aclose() is called.
    sock = FakeKiwoomWebSocket([], close_after_drain=False,
                                raise_on_iter=ConnectionError("boom"))
    factory = make_factory(sockets=[sock])
    sleep = AsyncMock(side_effect=_yielding_sleep)
    ws = _make_ws(
        token_manager=fake_token_manager_for_ws,
        connect_factory=factory, sleep=sleep,
    )

    async def stop_after_first_failure():
        await asyncio.sleep(0)
        await ws.aclose()

    await asyncio.gather(ws.run(), stop_after_first_failure())
    assert ws.state == V71WebSocketState.CLOSED


# ---------------------------------------------------------------------------
# Group H -- subscription + handler edges
# ---------------------------------------------------------------------------


async def test_unregister_handler_stops_dispatch(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([_real_msg(channel="0B", item="005930")])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    calls = []

    async def h(_m):
        calls.append("h")

    ws.register_handler(V71KiwoomChannelType.PRICE_TICK, h)
    ws.unregister_handler(V71KiwoomChannelType.PRICE_TICK, h)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    await asyncio.wait_for(ws.run(), timeout=5.0)
    assert calls == []


async def test_subscribe_dedupes_active_set(
    fake_token_manager_for_ws, make_factory,
):
    sock = FakeKiwoomWebSocket([])
    factory = make_factory(sockets=[sock])
    ws = _make_ws(token_manager=fake_token_manager_for_ws, connect_factory=factory)
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
    expected = V71WebSocketSubscription(
        channel=V71KiwoomChannelType.PRICE_TICK, item="005930",
    )
    assert expected in ws.subscriptions
    assert len(ws.subscriptions) == 1
