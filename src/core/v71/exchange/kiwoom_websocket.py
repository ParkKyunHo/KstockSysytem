"""V71KiwoomWebSocket -- Kiwoom realtime WebSocket transport (5 channels).

Spec sources:
  - KIWOOM_API_ANALYSIS.md §6 (WebSocket 5 채널) + §8 (0B 시세) + §9 (00 주문체결)
    + §10 (04 잔고, 1h VI)
  - 02_TRADING_RULES.md §8.2 (Phase 1/Phase 2 재연결 전략)
  - 12_SECURITY.md §6 (Bearer token plaintext never logged)
  - 06_AGENTS_SPEC.md §1 V71 Architect verification (WARNING items absorbed)

Design (architect-approved):
  - Single ``run()`` entry point handles connect → subscribe restore → recv
    loop → dispatch → reconnect. Caller spawns it as a task and never
    awaits it directly; ``aclose()`` cancels the loop cleanly.
  - Subscriptions are persisted in an in-memory ``set``; on every fresh
    connection the full set is re-sent in one ``REG`` batch so reconnects
    are transparent to handlers.
  - Reconnect uses PRD §8.2 strategy: Phase 1 = exponential backoff
    1/2/4/8/16 s (5 attempts), then Phase 2 = 300 s fixed forever.
    ``_consecutive_failures`` counter resets to 0 only after a successful
    receive (not just after a successful TCP open) so transient connect-
    then-disconnect storms don't ping-pong between phases.
  - Handlers are registered per channel; multiple handlers per channel
    fire in registration order, isolated from each other -- one handler
    raising never starves the queue. Sync handlers are rejected at
    registration time (we only support coroutine functions).
  - DI seams: ``connect_factory`` (defaults to ``websockets.connect``),
    ``sleep`` (defaults to ``asyncio.sleep``), ``clock`` (UTC now). Tests
    inject all three to drive a deterministic queue.

Out of scope (deferred):
  - REST polling fallback while WebSocket is down -- caller orchestrates.
  - Notification side-effects (state-change alerts via notification_skill).
  - Bar synthesis from 0B ticks -- consumer responsibility.
  - WebSocket 8005 (token invalid) auto refresh -- handled implicitly
    because ``token_manager.get_token()`` returns a fresh token on every
    reconnect.
"""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

try:
    import websockets
except ImportError as exc:  # pragma: no cover - listed in requirements.txt
    raise ImportError(
        "websockets>=12.0 is required (see requirements.txt)"
    ) from exc

from src.core.v71.exchange.token_manager import V71TokenManager
from src.core.v71.v71_constants import V71Constants
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIVE_BASE_URL = "wss://api.kiwoom.com:10000"
PAPER_BASE_URL = "wss://mockapi.kiwoom.com:10000"
DEFAULT_PATH = "/api/dostk/websocket"
DEFAULT_GROUP_NO = "1"

# PRD 02_TRADING_RULES.md §8.2 -- Phase 1 / Phase 2 reconnect cadence
# (centralised in V71Constants per Harness 3 §3 -- single source of truth).
PHASE_1_BACKOFF_SECONDS: tuple[float, ...] = V71Constants.WS_PHASE_1_BACKOFF_SECONDS
PHASE_2_INTERVAL_SECONDS = V71Constants.WS_PHASE_2_INTERVAL_SECONDS

# After this many consecutive auth failures (401/403), abort the run loop
# instead of hammering token_manager and tripping Kiwoom OAuth rate-limit
# (1700). Security review M2.
MAX_AUTH_FAILURES_BEFORE_ABORT = 3

# WebSocket transport defense-in-depth: cap incoming frame size, force
# keepalive so dead connections surface within ~20 s, bound graceful close.
MAX_FRAME_SIZE_BYTES = 65536
PING_INTERVAL_SECONDS = 20.0
PING_TIMEOUT_SECONDS = 20.0
CLOSE_TIMEOUT_SECONDS = 10.0

_TRNM_REG = "REG"
_TRNM_REMOVE = "REMOVE"
_TRNM_REAL = "REAL"
_TRNM_PING = "PING"
_TRNM_SYSTEM = "SYSTEM"
_TRNM_LOGIN = "LOGIN"
_REFRESH_KEEP = "1"

# 키움 application-level keep-alive (사용자 키움 공식 답변 2026-04-29):
#
#   PING:   {"trnm": "PING"}
#           서버 -> 클라이언트. 받은 메시지를 그대로 서버에 echo (PONG).
#           응답 누락 시 서버가 connection close (5회 누락 기준).
#           websockets 라이브러리의 RFC 6455 ping/pong 은 transport
#           레벨이라 별개로 application-level echo 가 필요.
#
#   SYSTEM: {"trnm": "SYSTEM", "return_code": "0", "return_msg": "..."}
#           서버 -> 클라이언트. 서버 상태 / 점검 / 오류 / 버전 정보 등
#           정보 전달용. ★ 응답 없음 (echo 시 protocol 위반으로 즉시
#           close 관찰됨). return_code "0" = 정상, 다른 값 = 점검 / 오류.
#
# 따라서 _KEEPALIVE_TRNMS 에는 PING 만 포함. SYSTEM 은 별도 분기에서
# return_code 분석 + 운영 가시성에 사용한다.
_KEEPALIVE_TRNMS: frozenset[str] = frozenset({_TRNM_PING})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V71WebSocketError(Exception):
    """Base class for V7.1 Kiwoom WebSocket failures."""


class V71WebSocketAuthError(V71WebSocketError):
    """Connect rejected (token invalid, IP mismatch, etc.). Caller should
    NOT retry without addressing the underlying credential / network
    issue first."""


class V71WebSocketTransportError(V71WebSocketError):
    """Underlying transport problem (handshake / disconnect / timeout)."""


# ---------------------------------------------------------------------------
# Channel + state enums
# ---------------------------------------------------------------------------


class V71KiwoomChannelType(Enum):
    """Kiwoom realtime channel codes (KIWOOM_API_ANALYSIS.md §6).

    PRICE_TICK, ORDER_EXECUTION, BALANCE, VI are the four V7.1 needs from
    day one. ORDERBOOK is enumerated for completeness; this unit accepts
    it but the trading rules currently don't subscribe to 0D.
    """

    PRICE_TICK = "0B"        # 주식체결 (실시간 시세)
    ORDERBOOK = "0D"          # 주식호가잔량 (선택, 본 단위 미사용)
    ORDER_EXECUTION = "00"    # 주문체결 (계좌, item="" OK)
    BALANCE = "04"            # 잔고 (계좌, item="" OK)
    VI = "1h"                 # VI 발동/해제


class V71WebSocketState(Enum):
    DISCONNECTED = "DISCONNECTED"
    CONNECTING = "CONNECTING"
    CONNECTED = "CONNECTED"
    RECONNECTING_PHASE_1 = "RECONNECTING_PHASE_1"
    RECONNECTING_PHASE_2 = "RECONNECTING_PHASE_2"
    CLOSED = "CLOSED"


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71WebSocketSubscription:
    """An active subscription. ``item=""`` is allowed for account channels
    (00 / 04 / 1h) where Kiwoom auto-routes by account."""

    channel: V71KiwoomChannelType
    item: str = ""
    grp_no: str = DEFAULT_GROUP_NO

    def to_data_entry(self) -> dict[str, str]:
        return {"item": self.item, "type": self.channel.value}


@dataclass(frozen=True)
class V71WebSocketMessage:
    """Parsed REAL message payload."""

    channel: V71KiwoomChannelType
    item: str
    name: str
    values: dict[str, str]
    received_at: datetime
    raw: dict[str, Any] = field(repr=False)


V71WebSocketHandler = Callable[[V71WebSocketMessage], Awaitable[None]]
V71StateChangeHandler = Callable[[V71WebSocketState], Awaitable[None]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class V71KiwoomWebSocket:
    """Reconnecting Kiwoom realtime WebSocket client.

    Use as::

        async with V71KiwoomWebSocket(token_manager=tm, is_paper=True) as ws:
            ws.register_handler(V71KiwoomChannelType.PRICE_TICK, on_price)
            await ws.subscribe(V71KiwoomChannelType.PRICE_TICK, "005930")
            await ws.run()    # typically as a background task

    ``run()`` returns only when ``aclose()`` is called. Phase 1 / Phase 2
    reconnect is automatic and transparent to handlers.
    """

    def __init__(
        self,
        *,
        token_manager: V71TokenManager,
        is_paper: bool = False,
        base_url: str | None = None,
        path: str = DEFAULT_PATH,
        connect_factory: Callable[..., Awaitable[Any]] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        clock: Callable[[], datetime] | None = None,
        on_state_change: V71StateChangeHandler | None = None,
        on_reconnect_recovered: Callable[[], Awaitable[None]] | None = None,
        stop_on_normal_close: bool = False,
    ) -> None:
        resolved_base = base_url or (PAPER_BASE_URL if is_paper else LIVE_BASE_URL)
        if not resolved_base.lower().startswith("wss://"):
            raise ValueError(
                f"base_url must use wss:// (got {resolved_base!r}); "
                "Kiwoom credentials must never travel over cleartext"
            )

        self._token_manager = token_manager
        self._is_paper = is_paper
        self._base_url = resolved_base.rstrip("/")
        self._path = path
        self._connect_factory = connect_factory or websockets.connect
        self._sleep = sleep or asyncio.sleep
        self._clock = clock or _utcnow
        self._on_state_change = on_state_change
        # 재연결 후 첫 정상 메시지(REAL) 수신 시 호출되는 콜백. 외부에서
        # reconciler 즉시 실행 + CRITICAL 알림 등 복구 경로를 트리거한다.
        # service restart 직후의 첫 연결에서는 호출되지 않고 (실패 카운터가
        # 0 이므로), WS 끊김 후 재연결 케이스에서만 호출된다.
        self._on_reconnect_recovered = on_reconnect_recovered
        # When True, ``run()`` exits cleanly if the recv loop ends without
        # exception (i.e., server closed the socket gracefully). Kiwoom in
        # production never closes cleanly, so the operational default is
        # ``False``; tests flip it on for deterministic shutdown.
        self._stop_on_normal_close = stop_on_normal_close

        self._state: V71WebSocketState = V71WebSocketState.DISCONNECTED
        self._consecutive_failures: int = 0
        self._consecutive_auth_failures: int = 0
        self._stop_event = asyncio.Event()

        # Active subscriptions persist across reconnects. ``set`` so
        # repeated subscribe() calls don't duplicate REG entries.
        self._subscriptions: set[V71WebSocketSubscription] = set()

        # ``dict[channel, list[handler]]`` -- registration order preserved.
        self._handlers: dict[V71KiwoomChannelType, list[V71WebSocketHandler]] = {}

        self._lock = asyncio.Lock()
        self._ws: Any | None = None  # active websockets connection

    # ----- Properties --------------------------------------------------

    @property
    def state(self) -> V71WebSocketState:
        return self._state

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    @property
    def url(self) -> str:
        return f"{self._base_url}{self._path}"

    @property
    def subscriptions(self) -> frozenset[V71WebSocketSubscription]:
        """Snapshot of active subscriptions (immutable view)."""
        return frozenset(self._subscriptions)

    @property
    def consecutive_failures(self) -> int:
        return self._consecutive_failures

    @property
    def consecutive_auth_failures(self) -> int:
        return self._consecutive_auth_failures

    # ----- Handler registration ----------------------------------------

    def register_handler(
        self,
        channel: V71KiwoomChannelType,
        handler: V71WebSocketHandler,
    ) -> None:
        """Register a coroutine handler for ``channel``.

        Multiple handlers per channel fire in registration order; one
        handler raising never blocks the others. Sync handlers are
        rejected -- the caller must always be awaitable.
        """
        if not inspect.iscoroutinefunction(handler):
            raise TypeError(
                "handler must be a coroutine function (async def)"
            )
        self._handlers.setdefault(channel, []).append(handler)

    def unregister_handler(
        self,
        channel: V71KiwoomChannelType,
        handler: V71WebSocketHandler,
    ) -> None:
        handlers = self._handlers.get(channel)
        if handlers and handler in handlers:
            handlers.remove(handler)

    # ----- Subscription ------------------------------------------------

    async def subscribe(
        self,
        channel: V71KiwoomChannelType,
        item: str = "",
        grp_no: str = DEFAULT_GROUP_NO,
    ) -> None:
        """Add a subscription. If currently connected, send REG immediately;
        otherwise queue for the next ``run()`` cycle."""
        sub = V71WebSocketSubscription(channel=channel, item=item, grp_no=grp_no)
        async with self._lock:
            already = sub in self._subscriptions
            self._subscriptions.add(sub)
            connected = self._state == V71WebSocketState.CONNECTED and self._ws is not None
        if connected and not already:
            await self._send_subscriptions([sub], trnm=_TRNM_REG)

    async def unsubscribe(
        self,
        channel: V71KiwoomChannelType,
        item: str = "",
        grp_no: str = DEFAULT_GROUP_NO,
    ) -> None:
        sub = V71WebSocketSubscription(channel=channel, item=item, grp_no=grp_no)
        async with self._lock:
            existed = sub in self._subscriptions
            self._subscriptions.discard(sub)
            connected = self._state == V71WebSocketState.CONNECTED and self._ws is not None
        if connected and existed:
            await self._send_subscriptions([sub], trnm=_TRNM_REMOVE)

    # ----- Lifecycle ---------------------------------------------------

    async def run(self) -> None:
        """Main loop: connect → restore subscriptions → recv → reconnect.

        Blocks until ``aclose()`` is called. Caller typically launches
        this with ``asyncio.create_task(ws.run())``.
        """
        try:
            while not self._stop_event.is_set():
                try:
                    await self._connect_and_serve()
                except V71WebSocketAuthError as exc:
                    if self._stop_event.is_set():
                        break
                    self._consecutive_auth_failures += 1
                    self._consecutive_failures += 1
                    if self._consecutive_auth_failures >= MAX_AUTH_FAILURES_BEFORE_ABORT:
                        # Security M2: stop reconnecting on persistent auth
                        # failure so we don't burn through Kiwoom OAuth
                        # quota (1700). The caller (orchestrator) is then
                        # expected to surface a CRITICAL alert and ask the
                        # operator to fix credentials before restarting.
                        logger.error(
                            "v71_kiwoom_ws_auth_failure_abort",
                            consecutive_auth_failures=self._consecutive_auth_failures,
                            error=type(exc).__name__,
                        )
                        break
                    await self._sleep_for_reconnect(exc)
                except V71WebSocketTransportError as exc:
                    if self._stop_event.is_set():
                        break
                    self._consecutive_failures += 1
                    await self._sleep_for_reconnect(exc)
                except Exception as exc:  # noqa: BLE001 - catch-all reconnect path
                    if self._stop_event.is_set():
                        break
                    logger.warning(
                        "v71_kiwoom_ws_unexpected_error",
                        error=type(exc).__name__,
                        consecutive_failures=self._consecutive_failures,
                    )
                    self._consecutive_failures += 1
                    await self._sleep_for_reconnect(exc)
        finally:
            await self._set_state(V71WebSocketState.CLOSED)

    async def aclose(self) -> None:
        """Stop the run loop and close the active connection."""
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(asyncio.TimeoutError, Exception):  # noqa: BLE001
                await asyncio.wait_for(ws.close(), timeout=CLOSE_TIMEOUT_SECONDS)
        await self._set_state(V71WebSocketState.CLOSED)

    async def __aenter__(self) -> V71KiwoomWebSocket:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return (
            f"V71KiwoomWebSocket(is_paper={self._is_paper}, url={self.url!r}, "
            f"state={self._state.value}, "
            f"subscriptions={len(self._subscriptions)})"
        )

    # ----- Internal: connect + serve -----------------------------------

    async def _connect_and_serve(self) -> None:
        await self._set_state(V71WebSocketState.CONNECTING)
        token = await self._token_manager.get_token()
        # Security L1: HTTP/1.1 headers are case-insensitive but the
        # canonical form is Title-Case; older websockets versions sometimes
        # echoed the literal name back, so we keep the spec-friendly form.
        headers = {"Authorization": f"Bearer {token}"}

        try:
            # Security M3: bound frame size + keepalive + close timeout.
            ws = await self._connect_factory(
                self.url,
                additional_headers=headers,
                max_size=MAX_FRAME_SIZE_BYTES,
                ping_interval=PING_INTERVAL_SECONDS,
                ping_timeout=PING_TIMEOUT_SECONDS,
                close_timeout=CLOSE_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            # Duck-type the auth-failure case so the exact websockets exception
            # class doesn't matter (it changed between 11.x and 13.x). Any
            # exception that exposes ``status_code`` 401/403 is treated as auth
            # failure -- everything else is a transport failure.
            await self._set_state(V71WebSocketState.DISCONNECTED)
            status = getattr(exc, "status_code", None)
            if status in (401, 403):
                raise V71WebSocketAuthError(
                    f"Kiwoom WS handshake rejected (status={status})"
                ) from exc
            raise V71WebSocketTransportError(
                f"Kiwoom WS connect failed: {type(exc).__name__}"
            ) from exc

        self._ws = ws
        await self._set_state(V71WebSocketState.CONNECTED)

        # 키움 application-level LOGIN (사용자 키움 답변 + 2026-04-29
        # production R10004 관찰 결과로 확정): connect 의 ``Authorization``
        # 헤더 만으로는 application 인증이 충족되지 않는다. connect 직후
        # ``{"trnm": "LOGIN", "token": <access_token>}`` 을 첫 메시지로
        # 보내지 않으면 키움이 매 ~10초마다 R10004 SYSTEM 메시지 + close
        # 를 반복한다. ``token`` 은 connect 시 발급 받은 그 값을 그대로
        # 재사용 (재요청 X) -- 같은 token 이 양쪽에서 검증된다.
        try:
            await ws.send(json.dumps({"trnm": _TRNM_LOGIN, "token": token}))
            logger.debug("v71_kiwoom_ws_login_sent")
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "v71_kiwoom_ws_login_send_failed",
                error=type(exc).__name__,
            )

        normal_close = False
        try:
            await self._restore_subscriptions()
            await self._recv_loop(ws)
            # recv_loop returning without raise = server-side close.
            normal_close = True
        finally:
            self._ws = None
            with contextlib.suppress(asyncio.TimeoutError, Exception):  # noqa: BLE001
                await asyncio.wait_for(ws.close(), timeout=CLOSE_TIMEOUT_SECONDS)
            if not self._stop_event.is_set():
                await self._set_state(V71WebSocketState.DISCONNECTED)
        if normal_close and self._stop_on_normal_close:
            self._stop_event.set()

    async def _restore_subscriptions(self) -> None:
        if not self._subscriptions:
            return
        # Group by grp_no so the restore stays a single REG per group.
        by_group: dict[str, list[V71WebSocketSubscription]] = {}
        for sub in self._subscriptions:
            by_group.setdefault(sub.grp_no, []).append(sub)
        for grp, subs in by_group.items():
            await self._send_payload({
                "trnm": _TRNM_REG,
                "grp_no": grp,
                "refresh": _REFRESH_KEEP,
                "data": [s.to_data_entry() for s in subs],
            })

    async def _recv_loop(self, ws: Any) -> None:
        async for raw in ws:
            if self._stop_event.is_set():
                break
            try:
                payload = json.loads(raw)
            except (TypeError, ValueError):
                logger.warning(
                    "v71_kiwoom_ws_invalid_json",
                    size=len(raw) if raw else 0,
                )
                continue

            trnm = payload.get("trnm")
            if trnm == _TRNM_REAL:
                await self._dispatch_real(payload)
                # First successful REAL means the connection is healthy --
                # reset both failure counters so the next disconnect starts
                # fresh in Phase 1 (and so a single recovered connection
                # clears any prior auth blip).
                was_recovering = self._consecutive_failures > 0
                self._consecutive_failures = 0
                self._consecutive_auth_failures = 0
                if was_recovering and self._on_reconnect_recovered is not None:
                    # 재연결 직후 첫 정상 메시지를 받은 시점. 외부
                    # (orchestrator) 가 reconciler 즉시 실행 + CRITICAL
                    # 알림으로 재연결 사이 누락된 체결/잔고/VI 를 복구한다.
                    try:
                        await self._on_reconnect_recovered()
                    except Exception as exc:  # noqa: BLE001
                        logger.error(
                            "v71_kiwoom_ws_reconnect_recovered_handler_error",
                            error=type(exc).__name__,
                        )
            elif trnm in (_TRNM_REG, _TRNM_REMOVE):
                logger.debug("v71_kiwoom_ws_subscribe_ack", trnm=trnm)
            elif trnm == _TRNM_LOGIN:
                # LOGIN ack -- 응답 형식은 키움 spec 미명시이지만 일반적
                # ack pattern. 단순 debug 로깅 (운영 실패 시 SYSTEM
                # return_code 로 별도 노출됨).
                logger.debug("v71_kiwoom_ws_login_ack")
            elif trnm in _KEEPALIVE_TRNMS:
                # PING echo (사용자 키움 답변 2026-04-29: 5회 누락 시 close).
                try:
                    await self._send_payload(payload)
                    logger.debug("v71_kiwoom_ws_keepalive_echo", trnm=trnm)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "v71_kiwoom_ws_keepalive_echo_failed",
                        trnm=trnm,
                        error=type(exc).__name__,
                    )
            elif trnm == _TRNM_SYSTEM:
                # 키움 spec (2026-04-29): SYSTEM 은 정보 전달용 (응답 없음).
                # return_code "0" = 정상 -> debug. 다른 값 = 점검 / 오류
                # / 접속 제한 등 -> warning 으로 운영자에게 자동 노출.
                #
                # 키움 공식 spec 의 키 이름은 ``return_code`` / ``return_msg``
                # 이지만 우리 production 환경에서는 ``code`` / ``message`` 키로
                # 도착하는 케이스 관찰됨 (2026-04-29 production observation).
                # 둘 다 fallback 처리 + 안전 truncate (200자).
                return_code = str(
                    payload.get("return_code") or payload.get("code") or ""
                )
                return_msg = str(
                    payload.get("return_msg") or payload.get("message") or ""
                )[:200]
                if return_code and return_code != "0":
                    logger.warning(
                        "v71_kiwoom_ws_system_alert",
                        return_code=return_code,
                        return_msg=return_msg,
                    )
                else:
                    logger.debug(
                        "v71_kiwoom_ws_system_status",
                        return_code=return_code or "(empty)",
                        return_msg=return_msg,
                    )
            else:
                logger.warning("v71_kiwoom_ws_unknown_trnm", trnm=trnm)

    async def _dispatch_real(self, payload: dict[str, Any]) -> None:
        for item in payload.get("data") or ():
            channel_code = item.get("type")
            try:
                channel = V71KiwoomChannelType(channel_code)
            except ValueError:
                logger.warning(
                    "v71_kiwoom_ws_unknown_channel",
                    channel_code=channel_code,
                )
                continue
            message = V71WebSocketMessage(
                channel=channel,
                item=item.get("item", ""),
                name=item.get("name", ""),
                values=dict(item.get("values") or {}),
                received_at=self._clock(),
                raw=item,
            )
            for handler in tuple(self._handlers.get(channel, ())):
                try:
                    await handler(message)
                except Exception as exc:  # noqa: BLE001 - handler isolation
                    # Security M1: avoid logger.exception (frame locals
                    # could leak position quantities, prices, etc. as PII).
                    logger.error(
                        "v71_kiwoom_ws_handler_error",
                        channel=channel.value,
                        item=message.item,
                        handler=getattr(handler, "__qualname__", repr(handler)),
                        error=type(exc).__name__,
                    )

    async def _send_subscriptions(
        self,
        subs: list[V71WebSocketSubscription],
        *,
        trnm: str,
    ) -> None:
        # Group subs by grp_no so each REG/REMOVE is a single message.
        by_group: dict[str, list[V71WebSocketSubscription]] = {}
        for sub in subs:
            by_group.setdefault(sub.grp_no, []).append(sub)
        for grp, group_subs in by_group.items():
            payload: dict[str, Any] = {
                "trnm": trnm,
                "grp_no": grp,
                "data": [s.to_data_entry() for s in group_subs],
            }
            if trnm == _TRNM_REG:
                payload["refresh"] = _REFRESH_KEEP
            await self._send_payload(payload)

    async def _send_payload(self, payload: dict[str, Any]) -> None:
        ws = self._ws
        if ws is None:
            raise V71WebSocketTransportError("WebSocket not connected")
        await ws.send(json.dumps(payload))

    # ----- Internal: reconnect cadence ---------------------------------

    async def _sleep_for_reconnect(self, exc: BaseException) -> None:
        attempt = self._consecutive_failures
        if attempt <= len(PHASE_1_BACKOFF_SECONDS):
            delay = PHASE_1_BACKOFF_SECONDS[attempt - 1]
            target_state = V71WebSocketState.RECONNECTING_PHASE_1
        else:
            delay = PHASE_2_INTERVAL_SECONDS
            target_state = V71WebSocketState.RECONNECTING_PHASE_2

        await self._set_state(target_state)
        logger.info(
            "v71_kiwoom_ws_reconnect_scheduled",
            phase=target_state.value,
            attempt=attempt,
            delay_seconds=delay,
            error=type(exc).__name__,
        )
        await self._sleep(delay)

    # ----- Internal: state ---------------------------------------------

    async def _set_state(self, new_state: V71WebSocketState) -> None:
        if self._state == new_state:
            return
        self._state = new_state
        if self._on_state_change is not None:
            try:
                await self._on_state_change(new_state)
            except Exception as exc:  # noqa: BLE001
                # Security M1: see handler-error rationale above.
                logger.error(
                    "v71_kiwoom_ws_state_change_handler_error",
                    state=new_state.value,
                    error=type(exc).__name__,
                )


__all__ = [
    "CLOSE_TIMEOUT_SECONDS",
    "DEFAULT_GROUP_NO",
    "DEFAULT_PATH",
    "LIVE_BASE_URL",
    "MAX_AUTH_FAILURES_BEFORE_ABORT",
    "MAX_FRAME_SIZE_BYTES",
    "PAPER_BASE_URL",
    "PHASE_1_BACKOFF_SECONDS",
    "PHASE_2_INTERVAL_SECONDS",
    "PING_INTERVAL_SECONDS",
    "PING_TIMEOUT_SECONDS",
    "V71KiwoomChannelType",
    "V71KiwoomWebSocket",
    "V71StateChangeHandler",
    "V71WebSocketAuthError",
    "V71WebSocketError",
    "V71WebSocketHandler",
    "V71WebSocketMessage",
    "V71WebSocketState",
    "V71WebSocketSubscription",
    "V71WebSocketTransportError",
]
