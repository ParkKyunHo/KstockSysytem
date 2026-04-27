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

from .rate_limiter import V71RateLimiter, V71RateLimiterStats
from .token_manager import (
    V71TokenAuthError,
    V71TokenError,
    V71TokenInfo,
    V71TokenManager,
    V71TokenRequestError,
)

__all__ = [
    "V71RateLimiter",
    "V71RateLimiterStats",
    "V71TokenAuthError",
    "V71TokenError",
    "V71TokenInfo",
    "V71TokenManager",
    "V71TokenRequestError",
]
