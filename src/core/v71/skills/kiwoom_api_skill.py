"""Skill 1: Kiwoom API call wrapper.

Spec: docs/v71/07_SKILLS_SPEC.md §1
Constitution: every Kiwoom REST call in V7.1 MUST go through this module
(Harness 3 enforces -- raw httpx/requests imports outside of this file
are blocked).

Design notes (full implementation lands in V7.0 integration step, not
P3.2):
  - Rate-limited via the V7.0 rate limiter (4.5/sec live, 0.33/sec paper).
  - OAuth token auto-refresh on EGW00001/EGW00002.
  - Exponential backoff on EGW00201 rate-limit errors.
  - 3 retries (V71Constants.API_MAX_RETRIES) with 10-second timeout.
  - Structured logging via structlog.

P3.2 surface:
  - :class:`ExchangeAdapter` Protocol -- the contract V71BuyExecutor (and
    later V71ExitExecutor) consumes. A real implementation wraps the
    convenience functions below; tests inject a fake.
  - Order/orderbook dataclasses -- typed transport for the executor.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class KiwoomAPIError(Exception):
    """Base for all Kiwoom-API failures surfaced by this skill."""


class KiwoomRateLimitError(KiwoomAPIError):
    """Raised after exhausting retries on EGW00201 (rate-limited)."""


class KiwoomAuthError(KiwoomAPIError):
    """Raised when token refresh fails (EGW00001/EGW00002)."""


class KiwoomTimeoutError(KiwoomAPIError):
    """Raised on transport-level timeout."""


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
    """Bundle of injected dependencies. Tests substitute mocks."""

    client: object        # KiwoomAPIClient (V7.0 src.api.client)
    auth_manager: object  # OAuthManager (V7.0 src.api.auth)
    rate_limiter: object  # KiwoomRateLimiter (V7.0)


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
# Convenience free functions (kept for parity with §1.4 -- still NotImpl
# until V7.0 integration)
# ---------------------------------------------------------------------------

async def call_kiwoom_api(
    context: KiwoomAPIContext,
    request: KiwoomAPIRequest,
) -> KiwoomAPIResponse:
    """Standard Kiwoom API entry point.

    Raises:
        KiwoomTimeoutError, KiwoomRateLimitError, KiwoomAuthError,
        KiwoomAPIError -- per docs/v71/07_SKILLS_SPEC.md §1.3.
    """
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1"
    )


async def send_buy_order(
    context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",
) -> KiwoomAPIResponse:
    """Convenience wrapper -- submit a buy order (kt10000)."""
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1.4"
    )


async def send_sell_order(
    context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",
) -> KiwoomAPIResponse:
    """Convenience wrapper -- submit a sell order."""
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1.4"
    )


async def cancel_order(
    context: KiwoomAPIContext,
    order_id: str,
    stock_code: str,
) -> KiwoomAPIResponse:
    """Convenience wrapper -- cancel a pending order."""
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1.4"
    )


async def get_balance(context: KiwoomAPIContext) -> KiwoomAPIResponse:
    """Convenience wrapper -- account balance."""
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1.4"
    )


async def get_position(
    context: KiwoomAPIContext,
    stock_code: str | None = None,
) -> KiwoomAPIResponse:
    """Convenience wrapper -- broker-side position snapshot."""
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1.4"
    )


async def get_order_status(
    context: KiwoomAPIContext,
    order_id: str,
) -> KiwoomAPIResponse:
    """Convenience wrapper -- order status."""
    raise NotImplementedError(
        "V7.0 integration -- see docs/v71/07_SKILLS_SPEC.md §1.4"
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
