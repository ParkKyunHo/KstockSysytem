"""V7.1 Kiwoom exchange transport layer.

This package owns the wire-level conversation with the Kiwoom REST + WebSocket
endpoints. The first unit (P5-Kiwoom-1) ships ``token_manager`` and
``rate_limiter``; subsequent units add ``kiwoom_client``, ``kiwoom_websocket``,
``order_manager``, ``reconciler``, ``error_mapper``.

Spec:
  - 04_ARCHITECTURE.md §7.1 (Kiwoom REST integration)
  - KIWOOM_API_ANALYSIS.md (au10001 OAuth, 1700 rate limit)
  - 06_AGENTS_SPEC.md §1 (V71 Architect verified)
  - 12_SECURITY.md §6 (secret handling -- never log token plaintext)

Constitutional rules (헌법, 01_PRD_MAIN.md §1):
  Rule 3 (충돌 금지): V7.1 land. V7.0 modules must NOT import from this
    package; the dependency arrow is one-way:
        src.web.v71 -> src.core.v71 -> src.core (V7.0 infrastructure)
  Rule 5 (단순함): callers inject app_key / app_secret via the constructor.
    Modules here do NOT read os.environ or src.utils.config directly. The
    wiring layer (lifespan / main / scripts) is responsible for assembling
    secrets from .env and feeding them in.
"""

from .error_mapper import (
    V71KiwoomEnvMismatchError,
    V71KiwoomInvalidInputError,
    V71KiwoomIPMismatchError,
    V71KiwoomMappedError,
    V71KiwoomMarketNotFoundError,
    V71KiwoomRateLimitError,
    V71KiwoomRecursionError,
    V71KiwoomServerError,
    V71KiwoomTokenInvalidError,
    V71KiwoomUnknownError,
    V71StockNotFoundError,
    compute_backoff_seconds,
    is_fatal,
    map_business_error,
    severity_for,
    should_force_token_refresh,
    should_retry_with_backoff,
)
from .kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomError,
    V71KiwoomResponse,
    V71KiwoomTradeType,
    V71KiwoomTransportError,
)
from .kiwoom_websocket import (
    V71KiwoomChannelType,
    V71KiwoomWebSocket,
    V71WebSocketAuthError,
    V71WebSocketError,
    V71WebSocketHandler,
    V71WebSocketMessage,
    V71WebSocketState,
    V71WebSocketSubscription,
    V71WebSocketTransportError,
)
from .order_manager import (
    V71OrderError,
    V71OrderFillEvent,
    V71OrderManager,
    V71OrderNotFoundError,
    V71OrderRequest,
    V71OrderSubmissionFailed,
    V71OrderSubmitResult,
    V71OrderUnsupportedError,
)
from .rate_limiter import V71RateLimiter, V71RateLimiterStats
from .reconciler import (
    V71PyramidBuyDetected,
    V71Reconciler,
    V71ReconcilerError,
    V71ReconciliationApplyMode,
    V71ReconciliationDecision,
    V71ReconciliationReport,
    V71TrackingTerminated,
)
from .token_manager import (
    V71TokenAuthError,
    V71TokenError,
    V71TokenInfo,
    V71TokenManager,
    V71TokenRequestError,
)

__all__ = [
    "V71KiwoomBusinessError",
    "V71KiwoomChannelType",
    "V71KiwoomClient",
    "V71KiwoomEnvMismatchError",
    "V71KiwoomError",
    "V71KiwoomIPMismatchError",
    "V71KiwoomInvalidInputError",
    "V71KiwoomMappedError",
    "V71KiwoomMarketNotFoundError",
    "V71KiwoomRateLimitError",
    "V71KiwoomRecursionError",
    "V71KiwoomResponse",
    "V71KiwoomServerError",
    "V71KiwoomTokenInvalidError",
    "V71KiwoomTradeType",
    "V71KiwoomTransportError",
    "V71KiwoomUnknownError",
    "V71KiwoomWebSocket",
    "V71OrderError",
    "V71OrderFillEvent",
    "V71OrderManager",
    "V71OrderNotFoundError",
    "V71OrderRequest",
    "V71OrderSubmissionFailed",
    "V71OrderSubmitResult",
    "V71OrderUnsupportedError",
    "V71PyramidBuyDetected",
    "V71RateLimiter",
    "V71RateLimiterStats",
    "V71Reconciler",
    "V71ReconcilerError",
    "V71ReconciliationApplyMode",
    "V71ReconciliationDecision",
    "V71ReconciliationReport",
    "V71StockNotFoundError",
    "V71TrackingTerminated",
    "V71TokenAuthError",
    "V71TokenError",
    "V71TokenInfo",
    "V71TokenManager",
    "V71TokenRequestError",
    "V71WebSocketAuthError",
    "V71WebSocketError",
    "V71WebSocketHandler",
    "V71WebSocketMessage",
    "V71WebSocketState",
    "V71WebSocketSubscription",
    "V71WebSocketTransportError",
    "compute_backoff_seconds",
    "is_fatal",
    "map_business_error",
    "severity_for",
    "should_force_token_refresh",
    "should_retry_with_backoff",
]
