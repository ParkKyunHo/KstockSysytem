"""Skill 1: Kiwoom API call wrapper.

Spec: docs/v71/07_SKILLS_SPEC.md §1
Constitution: every Kiwoom REST call in V7.1 MUST go through this module
(Harness 3 enforces -- raw httpx/requests imports outside of this file
are blocked).

Wiring (P5-Kiwoom-Wire, 2026-04-28):
  - Module-level convenience functions are now real -- they delegate to
    ``V71KiwoomClient`` (transport / rate-limit / token / retry) and
    surface broker errors through the V7.0-compatible
    :class:`KiwoomAPIError` hierarchy. Each raised error carries the
    underlying :class:`V71KiwoomMappedError` on ``.v71_mapped`` so a
    caller with a ``V71NotificationQueue`` can route it through
    ``notify_kiwoom_error`` without losing the policy hints (severity /
    is_fatal / should_force_token_refresh / should_retry_with_backoff).
  - These free functions are intended for *raw* transport callers
    (paper-trade smoke tests, health checks, external tooling). The
    V7.1 trading-rule path -- buy retry, weighted-avg recompute, DB
    INSERT, WS reconcile -- lives on :class:`V71OrderManager` and must
    be used for any user-facing trade.

P3.2 surface (still in place):
  - :class:`ExchangeAdapter` Protocol -- the contract V71BuyExecutor and
    V71ExitExecutor consume. The concrete implementation built on top
    of V71KiwoomClient ships in a follow-up unit (P5-Kiwoom-Adapter)
    along with ka10004 (호가) + ka10001 (현재가) endpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol

from src.core.v71.exchange.error_mapper import (
    V71KiwoomMappedError,
    V71KiwoomRateLimitError,
    V71KiwoomTokenInvalidError,
    map_business_error,
)
from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomResponse,
    V71KiwoomTradeType,
    V71KiwoomTransportError,
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class KiwoomAPIError(Exception):
    """Base for all Kiwoom-API failures surfaced by this skill.

    Wraps the underlying :class:`V71KiwoomMappedError` (when one exists)
    on ``.v71_mapped`` so callers with a notification queue can route it
    through ``notify_kiwoom_error`` without losing the policy hints
    (severity / is_fatal / should_force_token_refresh /
    should_retry_with_backoff).
    """

    def __init__(
        self,
        message: str,
        *,
        v71_mapped: V71KiwoomMappedError | None = None,
    ) -> None:
        super().__init__(message)
        self.v71_mapped = v71_mapped


class KiwoomRateLimitError(KiwoomAPIError):
    """Raised after exhausting retries on EGW00201 / Kiwoom 1700."""


class KiwoomAuthError(KiwoomAPIError):
    """Raised when token refresh fails (EGW00001/EGW00002 / Kiwoom 8005)."""


class KiwoomTimeoutError(KiwoomAPIError):
    """Raised on transport-level timeout / network failure."""


# ---------------------------------------------------------------------------
# Raw API request / response (advanced callers)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KiwoomAPIRequest:
    """A single Kiwoom REST request payload."""

    endpoint: str  # e.g. "/api/dostk/ordr"
    method: str    # "POST" | "GET"
    api_id: str    # e.g. "kt10000"
    payload: dict
    timeout_seconds: int = 10


@dataclass(frozen=True)
class KiwoomAPIResponse:
    """Normalized response. ``success`` distinguishes business outcome
    from transport outcome; both surface here uniformly."""

    success: bool
    data: dict | None
    error_code: str | None
    error_message: str | None
    raw_response: dict
    duration_ms: int


@dataclass(frozen=True)
class KiwoomAPIContext:
    """Bundle of injected dependencies. Tests substitute mocks.

    V7.1 wiring (P5-Kiwoom-Wire): ``client`` MUST be a
    :class:`V71KiwoomClient` instance. ``auth_manager`` and
    ``rate_limiter`` are kept on the dataclass for V7.0 signature
    compatibility but are unused in V7.1 -- the client owns its own
    token + rate-limit machinery (V71TokenManager + V71RateLimiter).
    The module-level free functions enforce the V71KiwoomClient type
    via an isinstance guard so a mis-injected V7.0 client fails fast
    rather than silently producing the wrong wire calls.
    """

    client: object        # V7.1: must be V71KiwoomClient
    auth_manager: object  # V7.1: unused (V71TokenManager owns it)
    rate_limiter: object  # V7.1: unused (V71RateLimiter owns it)


# ---------------------------------------------------------------------------
# Order primitives (P3.2 surface) -- V71-prefixed to avoid V7.0 collisions
# (Constitution 3 / Harness 1: V7.0 src.api.endpoints.order and
# src.database.models already define OrderType/OrderSide/OrderResult/
# OrderStatus -- these are different concepts living in V7.0 infra).
# ---------------------------------------------------------------------------

class V71OrderType(Enum):
    """Order pricing mode."""

    LIMIT = "LIMIT"
    MARKET = "MARKET"


class V71OrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class V71Orderbook:
    """Top-of-book snapshot used to choose a limit price.

    ``ask_1`` is the best (lowest) ask price -- per §4.1, a limit buy
    aims at this price for fastest fill.
    """

    stock_code: str
    bid_1: int       # 매수 1호가 (best bid)
    ask_1: int       # 매도 1호가 (best ask)
    last_price: int  # 직전 체결가


@dataclass(frozen=True)
class V71OrderResult:
    """Result of submitting (not necessarily filling) an order.

    ``order_id`` is the broker-assigned identifier used by subsequent
    status / cancel calls. ``filled_quantity == 0`` is normal -- limit
    orders fill asynchronously.
    """

    order_id: str
    stock_code: str
    side: V71OrderSide
    order_type: V71OrderType
    requested_quantity: int
    requested_price: int
    filled_quantity: int = 0
    avg_fill_price: int = 0


@dataclass(frozen=True)
class V71OrderStatus:
    """Polled status of a previously submitted order."""

    order_id: str
    stock_code: str
    requested_quantity: int
    filled_quantity: int
    avg_fill_price: int
    is_open: bool   # True if more fills are possible (still resting)
    is_cancelled: bool


class OrderRejectedError(KiwoomAPIError):
    """Broker rejected the order (e.g., insufficient cash, halted stock)."""


# ---------------------------------------------------------------------------
# ExchangeAdapter -- the executor-facing contract
# ---------------------------------------------------------------------------

class ExchangeAdapter(Protocol):
    """Subset of broker interactions V71BuyExecutor (and exit executor)
    rely on.

    Concrete implementations:
      - real: V7.0 ``src.api.client.KiwoomAPIClient`` adapted via the
        free functions below (P3.4+ integration);
      - test: in-memory ``FakeExchange`` constructed per scenario.

    All methods are awaitable. Raises :class:`KiwoomAPIError` (or one of
    its subclasses) on transport failure.
    """

    async def get_orderbook(self, stock_code: str) -> V71Orderbook: ...

    async def get_current_price(self, stock_code: str) -> int: ...

    async def send_order(
        self,
        *,
        stock_code: str,
        side: V71OrderSide,
        quantity: int,
        price: int,
        order_type: V71OrderType,
    ) -> V71OrderResult: ...

    async def cancel_order(
        self, *, order_id: str, stock_code: str
    ) -> V71OrderResult: ...

    async def get_order_status(self, order_id: str) -> V71OrderStatus: ...


# ---------------------------------------------------------------------------
# Wiring helpers (P5-Kiwoom-Wire)
# ---------------------------------------------------------------------------


_ORDER_TYPE_TO_V71_TRADE: dict[str, V71KiwoomTradeType] = {
    "LIMIT": V71KiwoomTradeType.LIMIT,
    "MARKET": V71KiwoomTradeType.MARKET,
}


def _require_v71_client(context: KiwoomAPIContext) -> V71KiwoomClient:
    """Architect-mandated isinstance guard. V7.1 module-level functions
    refuse to silently work against a V7.0 client -- a wrong injection
    is a wiring bug, not a runtime condition we recover from."""
    client = context.client
    if not isinstance(client, V71KiwoomClient):
        raise TypeError(
            "KiwoomAPIContext.client must be a V71KiwoomClient instance "
            f"(got {type(client).__name__!r}); see P5-Kiwoom-Wire wiring."
        )
    return client


def _v71_response_to_kiwoom(response: V71KiwoomResponse) -> KiwoomAPIResponse:
    """Map a successful V71KiwoomResponse to the V7.0-compatible
    :class:`KiwoomAPIResponse` shape."""
    return KiwoomAPIResponse(
        success=True,
        data=dict(response.data or {}),
        error_code=None,
        error_message=None,
        raw_response={
            "api_id": response.api_id,
            "return_code": response.return_code,
            "return_msg": response.return_msg,
            "cont_yn": response.cont_yn,
            "next_key": response.next_key,
            "duration_ms": response.duration_ms,
            "data": dict(response.data or {}),
        },
        duration_ms=response.duration_ms,
    )


def _wrap_business_error(
    exc: V71KiwoomBusinessError, *, context_msg: str,
) -> KiwoomAPIError:
    """Translate a Kiwoom business error (200 OK + return_code != 0) to
    the V7.0 :class:`KiwoomAPIError` hierarchy. The mapped exception is
    attached as ``.v71_mapped`` so callers can forward it to
    ``notify_kiwoom_error`` without losing policy hints."""
    mapped = map_business_error(exc)
    message = (
        f"{context_msg}: code={exc.return_code} "
        f"({exc.api_id or 'unknown_api'}) -- {exc.return_msg}"
    )
    if isinstance(mapped, V71KiwoomRateLimitError):
        return KiwoomRateLimitError(message, v71_mapped=mapped)
    if isinstance(mapped, V71KiwoomTokenInvalidError):
        return KiwoomAuthError(message, v71_mapped=mapped)
    return KiwoomAPIError(message, v71_mapped=mapped)


def _wrap_transport_error(
    exc: V71KiwoomTransportError, *, context_msg: str,
) -> KiwoomTimeoutError:
    """Network / 4xx / 5xx / non-JSON failures all surface as the
    V7.0 ``KiwoomTimeoutError`` so caller branching stays simple."""
    return KiwoomTimeoutError(
        f"{context_msg}: {type(exc).__name__}: {exc}",
        v71_mapped=None,
    )


def _filter_position_by_stock(
    data: dict[str, Any] | None, stock_code: str,
) -> dict[str, Any] | None:
    """Pick the holdings entry for ``stock_code`` out of a kt00018
    response. Returns ``None`` when the broker has no row for the stock
    (caller decides whether absence is an error)."""
    holdings = (data or {}).get("acnt_evlt_remn_indv_tot") or []
    for item in holdings:
        if not isinstance(item, dict):
            continue
        if str(item.get("stk_cd", "")).strip() == stock_code:
            return item
    return None


# ---------------------------------------------------------------------------
# Convenience free functions (P5-Kiwoom-Wire wiring)
# ---------------------------------------------------------------------------


async def call_kiwoom_api(
    context: KiwoomAPIContext,
    request: KiwoomAPIRequest,
) -> KiwoomAPIResponse:
    """Standard Kiwoom API entry point. Delegates to
    ``V71KiwoomClient.request`` which handles rate-limit + token + retry
    + structured logging.

    Note: ``request.timeout_seconds`` is observed by the underlying
    V71KiwoomClient configuration (V71Constants.API_TIMEOUT_SECONDS,
    set when the client was constructed); per-call override is not
    plumbed through this surface in V7.1 by design.

    Raises:
        KiwoomTimeoutError -- transport / network failure (V71KiwoomTransportError).
        KiwoomRateLimitError -- broker 1700 (V71KiwoomRateLimitError).
        KiwoomAuthError -- broker 8005 (V71KiwoomTokenInvalidError).
        KiwoomAPIError -- any other broker business error
            (V71KiwoomBusinessError); ``.v71_mapped`` carries the typed
            mapped error for ``notify_kiwoom_error`` routing.
    """
    client = _require_v71_client(context)
    try:
        response = await client.request(
            api_id=request.api_id,
            endpoint=request.endpoint,
            payload=request.payload,
            method=request.method,
        )
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg=f"call_kiwoom_api({request.api_id})",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg=f"call_kiwoom_api({request.api_id})",
        ) from exc
    return _v71_response_to_kiwoom(response)


async def send_buy_order(
    context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",
) -> KiwoomAPIResponse:
    """Submit a raw kt10000 buy order via V71KiwoomClient.

    WARNING: this is the *raw transport* path. The V7.1 trading-rule
    flow (buy retry per 02 §4.2 / position INSERT / WS reconcile)
    lives on ``V71OrderManager.submit_order`` -- use that for any
    user-facing trade. This function exists for paper-trade smoke
    tests, health checks, and external tooling that need a thin wire
    call without DB side effects.
    """
    client = _require_v71_client(context)
    trade_type = _ORDER_TYPE_TO_V71_TRADE.get(order_type.upper())
    if trade_type is None:
        raise KiwoomAPIError(
            f"send_buy_order: unsupported order_type={order_type!r} "
            f"(LIMIT / MARKET only)"
        )
    try:
        response = await client.place_buy_order(
            stock_code=stock_code,
            quantity=quantity,
            price=price if trade_type == V71KiwoomTradeType.LIMIT else None,
            trade_type=trade_type,
        )
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg=f"send_buy_order({stock_code})",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg=f"send_buy_order({stock_code})",
        ) from exc
    except ValueError as exc:
        # Security M2: V71KiwoomClient._build_order_payload raises
        # ValueError on bad quantity / price; surface it through the
        # documented KiwoomAPIError contract instead of leaking
        # ValueError to the caller.
        raise KiwoomAPIError(
            f"send_buy_order({stock_code}): invalid input -- {exc}",
        ) from exc
    return _v71_response_to_kiwoom(response)


async def send_sell_order(
    context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",
) -> KiwoomAPIResponse:
    """Submit a raw kt10001 sell order via V71KiwoomClient.

    Same V71OrderManager-vs-raw caveat as :func:`send_buy_order`.
    """
    client = _require_v71_client(context)
    trade_type = _ORDER_TYPE_TO_V71_TRADE.get(order_type.upper())
    if trade_type is None:
        raise KiwoomAPIError(
            f"send_sell_order: unsupported order_type={order_type!r} "
            f"(LIMIT / MARKET only)"
        )
    try:
        response = await client.place_sell_order(
            stock_code=stock_code,
            quantity=quantity,
            price=price if trade_type == V71KiwoomTradeType.LIMIT else None,
            trade_type=trade_type,
        )
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg=f"send_sell_order({stock_code})",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg=f"send_sell_order({stock_code})",
        ) from exc
    except ValueError as exc:
        raise KiwoomAPIError(
            f"send_sell_order({stock_code}): invalid input -- {exc}",
        ) from exc
    return _v71_response_to_kiwoom(response)


async def cancel_order(
    context: KiwoomAPIContext,
    order_id: str,
    stock_code: str,
) -> KiwoomAPIResponse:
    """Cancel a pending order via kt10003 (잔량 전부 취소).

    ``order_id`` is the broker-assigned ``ord_no`` from a prior submit.
    """
    client = _require_v71_client(context)
    try:
        response = await client.cancel_order(
            orig_order_no=order_id,
            stock_code=stock_code,
            cancel_qty=0,  # 0 = cancel remainder per Kiwoom spec
        )
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg=f"cancel_order({order_id})",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg=f"cancel_order({order_id})",
        ) from exc
    except ValueError as exc:
        raise KiwoomAPIError(
            f"cancel_order({order_id}): invalid input -- {exc}",
        ) from exc
    return _v71_response_to_kiwoom(response)


async def get_balance(context: KiwoomAPIContext) -> KiwoomAPIResponse:
    """Account balance snapshot via kt00018 (계좌평가잔고)."""
    client = _require_v71_client(context)
    try:
        response = await client.get_account_balance()
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg="get_balance",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg="get_balance",
        ) from exc
    return _v71_response_to_kiwoom(response)


async def get_position(
    context: KiwoomAPIContext,
    stock_code: str | None = None,
) -> KiwoomAPIResponse:
    """Broker-side position snapshot via kt00018.

    When ``stock_code`` is given, the response ``data`` is filtered to
    the matching holdings entry (``data == {"position": {...}}``);
    otherwise the full balance shape is returned. Absence of the stock
    surfaces as ``data == {"position": None}`` -- not an error.
    """
    client = _require_v71_client(context)
    try:
        response = await client.get_account_balance()
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg="get_position",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg="get_position",
        ) from exc
    if stock_code is None:
        return _v71_response_to_kiwoom(response)
    entry = _filter_position_by_stock(response.data, stock_code)
    return KiwoomAPIResponse(
        success=True,
        data={"position": entry},
        error_code=None,
        error_message=None,
        raw_response={
            "api_id": response.api_id,
            "return_code": response.return_code,
            "return_msg": response.return_msg,
            "duration_ms": response.duration_ms,
            "stock_code": stock_code,
        },
        duration_ms=response.duration_ms,
    )


async def get_order_status(
    context: KiwoomAPIContext,
    order_id: str,
) -> KiwoomAPIResponse:
    """Poll an order's broker-side status via ka10075 (미체결조회).

    Resolution order:
      1. ka10075 -- if the order is still pending, return that row.
      2. Not found in pending -- return ``data == {"found": False}``;
         caller decides whether the order finished, was cancelled, or
         never existed. (ka10076 체결조회 fallback ships in a follow-up
         unit when V7.1 needs broker-side fill detail beyond the
         WebSocket 00 stream the V71OrderManager already consumes.)
    """
    client = _require_v71_client(context)
    try:
        response = await client.get_pending_orders()
    except V71KiwoomTransportError as exc:
        raise _wrap_transport_error(
            exc, context_msg=f"get_order_status({order_id})",
        ) from exc
    except V71KiwoomBusinessError as exc:
        raise _wrap_business_error(
            exc, context_msg=f"get_order_status({order_id})",
        ) from exc
    pending = (response.data or {}).get("oso") or []
    for item in pending:
        if not isinstance(item, dict):
            continue
        if str(item.get("ord_no", "")).strip() == order_id:
            return KiwoomAPIResponse(
                success=True,
                data={"found": True, "order": item},
                error_code=None,
                error_message=None,
                raw_response={
                    "api_id": response.api_id,
                    "return_code": response.return_code,
                    "duration_ms": response.duration_ms,
                    "order_id": order_id,
                },
                duration_ms=response.duration_ms,
            )
    return KiwoomAPIResponse(
        success=True,
        data={"found": False, "order": None},
        error_code=None,
        error_message=None,
        raw_response={
            "api_id": response.api_id,
            "return_code": response.return_code,
            "duration_ms": response.duration_ms,
            "order_id": order_id,
        },
        duration_ms=response.duration_ms,
    )


__all__ = [
    # errors
    "KiwoomAPIError",
    "KiwoomRateLimitError",
    "KiwoomAuthError",
    "KiwoomTimeoutError",
    "OrderRejectedError",
    # raw transport
    "KiwoomAPIRequest",
    "KiwoomAPIResponse",
    "KiwoomAPIContext",
    # P3.2 order surface (V71-prefixed to avoid V7.0 collisions)
    "V71OrderType",
    "V71OrderSide",
    "V71Orderbook",
    "V71OrderResult",
    "V71OrderStatus",
    "ExchangeAdapter",
    # convenience (NotImpl, V7.0 integration step)
    "call_kiwoom_api",
    "send_buy_order",
    "send_sell_order",
    "cancel_order",
    "get_balance",
    "get_position",
    "get_order_status",
]
