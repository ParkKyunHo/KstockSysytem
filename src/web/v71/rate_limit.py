"""Rate-limit primitives (slowapi).

PRD ``09_API_SPEC §1.2`` mandates 5 login attempts / IP / minute. The
limiter is constructed once at module import so middleware/decorators
can share state in-process. Production should swap the in-memory store
for Redis (``slowapi.extension.RateLimitExceeded`` already supports it).
"""

from __future__ import annotations

from typing import Any

from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.requests import Request
from starlette.responses import JSONResponse

from .config import get_settings
from .exceptions import V71RateLimitError
from .schemas.common import build_meta


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return get_remote_address(request)


_settings = get_settings()
limiter = Limiter(
    key_func=_client_ip,
    default_limits=[f"{_settings.api_rate_limit_per_minute}/minute"],
    headers_enabled=True,
)

LOGIN_LIMIT = f"{_settings.login_rate_limit_per_minute}/minute"


async def rate_limit_exceeded_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Maps slowapi errors to the V7.1 error envelope (PRD §1.2 429)."""
    retry_after: int | None = None
    if isinstance(exc, RateLimitExceeded):
        retry_after = int(getattr(exc, "retry_after", 60) or 60)

    rid = getattr(request.state, "request_id", "")
    payload: dict[str, Any] = {
        "error_code": "RATE_LIMIT_EXCEEDED",
        "message": "Too many requests",
        "details": {"retry_after_seconds": retry_after} if retry_after else None,
        "meta": build_meta(rid),
    }
    headers = {}
    if retry_after:
        headers["Retry-After"] = str(retry_after)
    return JSONResponse(status_code=429, content=payload, headers=headers)


# Re-export so callers don't import slowapi directly.
__all__ = [
    "LOGIN_LIMIT",
    "V71RateLimitError",
    "RateLimitExceeded",
    "limiter",
    "rate_limit_exceeded_handler",
]
