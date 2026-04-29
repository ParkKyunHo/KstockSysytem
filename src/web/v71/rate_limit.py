"""Rate-limit primitives.

PRD ``09_API_SPEC §1.2`` mandates 5 login attempts / IP / minute. The
slowapi 0.1.9 + fastapi 0.115 호환성 issue (decorator 가 endpoint
signature introspection 을 깨뜨려 query/body validation 실패) 로
@limiter.limit 사용을 보류하고 자체 sliding-window limiter 를
FastAPI dependency 로 노출한다.

설계:
    * 키 함수: x-forwarded-for 우선, 없으면 starlette client.host.
    * In-memory deque per key. uvicorn 단일 worker 환경에서 충분.
    * 워커 분산 시 Redis 로 backing store 교체 (interface 동일).
    * 만료된 timestamp 는 check 시점에 lazy cleanup -- 별도 background
      sweep 불필요.

slowapi 모듈은 향후 호환 release 도입 시 다시 활성화할 수 있도록 import
경로를 유지하되, 새 호출 path 에서는 사용하지 않는다.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Any

from fastapi import Request as FastAPIRequest
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

# slowapi 호환 release 까지 비활성. 이 객체는 main.py 에 등록되지만 어떤
# decorator 에서도 호출되지 않는다. 향후 호환 활성화 시점에 다시 사용.
limiter = Limiter(
    key_func=_client_ip,
    default_limits=[f"{_settings.api_rate_limit_per_minute}/minute"],
    headers_enabled=True,
)

LOGIN_LIMIT = f"{_settings.login_rate_limit_per_minute}/minute"


# ---------------------------------------------------------------------
# Self-contained sliding-window limiter (D, 2026-04-29)
# ---------------------------------------------------------------------


class _SlidingWindowLimiter:
    """Per-key sliding-window counter.

    O(window 내 hits) 메모리. 단일 worker 환경에서 충분하며 Redis 로
    교체 시 같은 ``check(key)`` 인터페이스를 노출하면 된다.
    """

    def __init__(self, *, limit: int, window_seconds: float) -> None:
        if limit <= 0:
            raise ValueError("limit must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def check(self, key: str) -> None:
        """Raise V71RateLimitError if ``key`` exceeded its quota."""
        now = time.monotonic()
        cutoff = now - self.window
        with self._lock:
            q = self._hits[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= self.limit:
                retry_after = int(q[0] + self.window - now) + 1
                raise V71RateLimitError(
                    "Too many requests",
                    error_code="RATE_LIMIT_EXCEEDED",
                    details={"retry_after_seconds": max(retry_after, 1)},
                )
            q.append(now)


# Login: PRD §1.2 = 5/분/IP (settings 에서 override 가능).
_login_limiter = _SlidingWindowLimiter(
    limit=_settings.login_rate_limit_per_minute,
    window_seconds=60.0,
)

# TOTP verify: brute-force 6자리 코드 방어 = 5/분/IP.
_totp_limiter = _SlidingWindowLimiter(limit=5, window_seconds=60.0)

# Refresh: 비교적 관대 = 30/분/IP (정상 SPA 도 1초마다 refresh 폴링하지
# 않으므로 충분 + 분산 공격은 IP 기반).
_refresh_limiter = _SlidingWindowLimiter(limit=30, window_seconds=60.0)


def login_rate_limit(request: FastAPIRequest) -> None:
    """FastAPI dependency for /auth/login."""
    _login_limiter.check(f"login:{_client_ip(request)}")


def totp_rate_limit(request: FastAPIRequest) -> None:
    """FastAPI dependency for /auth/totp/verify."""
    _totp_limiter.check(f"totp:{_client_ip(request)}")


def refresh_rate_limit(request: FastAPIRequest) -> None:
    """FastAPI dependency for /auth/refresh."""
    _refresh_limiter.check(f"refresh:{_client_ip(request)}")


async def rate_limit_exceeded_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    """Maps slowapi errors to the V7.1 error envelope (PRD §1.2 429).

    V71RateLimitError 는 register_exception_handlers 에서 별도 처리되므로
    여기는 slowapi 가 다시 활성화되었을 때를 위한 backward path.
    """
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


__all__ = [
    "LOGIN_LIMIT",
    "RateLimitExceeded",
    "V71RateLimitError",
    "limiter",
    "login_rate_limit",
    "rate_limit_exceeded_handler",
    "refresh_rate_limit",
    "totp_rate_limit",
]
