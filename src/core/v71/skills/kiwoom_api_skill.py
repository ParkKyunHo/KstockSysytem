"""Skill 1: Kiwoom API call wrapper.

Spec: docs/v71/07_SKILLS_SPEC.md §1
Constitution: every Kiwoom REST call in V7.1 MUST go through this module
(Harness 3 enforces -- raw httpx/requests imports outside of this file
are blocked).

Design notes (full implementation lands in P3.2 / Phase 3):
  - Rate-limited via the V7.0 rate limiter (4.5/sec live, 0.33/sec paper).
  - OAuth token auto-refresh on EGW00001/EGW00002.
  - Exponential backoff on EGW00201 rate-limit errors.
  - 3 retries (V71Constants.API_MAX_RETRIES) with 10-second timeout.
  - Structured logging via structlog.
"""

from __future__ import annotations

from dataclasses import dataclass


class KiwoomAPIError(Exception):
    """Base for all Kiwoom-API failures surfaced by this skill."""


class KiwoomRateLimitError(KiwoomAPIError):
    """Raised after exhausting retries on EGW00201 (rate-limited)."""


class KiwoomAuthError(KiwoomAPIError):
    """Raised when token refresh fails (EGW00001/EGW00002)."""


class KiwoomTimeoutError(KiwoomAPIError):
    """Raised on transport-level timeout."""


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


async def call_kiwoom_api(
    context: KiwoomAPIContext,
    request: KiwoomAPIRequest,
) -> KiwoomAPIResponse:
    """Standard Kiwoom API entry point.

    Raises:
        KiwoomTimeoutError, KiwoomRateLimitError, KiwoomAuthError,
        KiwoomAPIError -- per docs/v71/07_SKILLS_SPEC.md §1.3.
    """
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1")


async def send_buy_order(
    context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",
) -> KiwoomAPIResponse:
    """Convenience wrapper -- submit a buy order (kt10000)."""
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1.4")


async def send_sell_order(
    context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",
) -> KiwoomAPIResponse:
    """Convenience wrapper -- submit a sell order."""
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1.4")


async def cancel_order(
    context: KiwoomAPIContext,
    order_id: str,
    stock_code: str,
) -> KiwoomAPIResponse:
    """Convenience wrapper -- cancel a pending order."""
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1.4")


async def get_balance(context: KiwoomAPIContext) -> KiwoomAPIResponse:
    """Convenience wrapper -- account balance."""
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1.4")


async def get_position(
    context: KiwoomAPIContext,
    stock_code: str | None = None,
) -> KiwoomAPIResponse:
    """Convenience wrapper -- broker-side position snapshot."""
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1.4")


async def get_order_status(
    context: KiwoomAPIContext,
    order_id: str,
) -> KiwoomAPIResponse:
    """Convenience wrapper -- order status."""
    raise NotImplementedError("P3.2 -- see docs/v71/07_SKILLS_SPEC.md §1.4")


__all__ = [
    "KiwoomAPIError",
    "KiwoomRateLimitError",
    "KiwoomAuthError",
    "KiwoomTimeoutError",
    "KiwoomAPIRequest",
    "KiwoomAPIResponse",
    "KiwoomAPIContext",
    "call_kiwoom_api",
    "send_buy_order",
    "send_sell_order",
    "cancel_order",
    "get_balance",
    "get_position",
    "get_order_status",
]
