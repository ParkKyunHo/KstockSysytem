"""V7.1 Kiwoom error mapper -- pure classifier + policy hints.

Spec sources:
  - KIWOOM_API_ANALYSIS.md line 1050~1094 (Kiwoom error codes 1500-1999 +
    8000-8103 + V7.1 정책 매핑)
  - 04_ARCHITECTURE.md §7.1 (Kiwoom REST layered architecture)
  - 06_AGENTS_SPEC.md §1 V71 Architect verification

Design summary (architect-approved scope):
  - This unit is a **pure classifier**. It maps a ``V71KiwoomBusinessError``
    (raised by ``V71KiwoomClient.request`` when ``return_code != 0``) to a
    typed V7.1 exception, plus hints (severity / fatal / retry / refresh).
  - Notification side-effects, the orchestrator (asyncio.sleep + retries +
    token refresh), and ``notification_skill.EventType`` extensions are
    explicitly **out of scope** -- they live in a follow-up unit. Keeping
    those concerns separate lets the mapper stay synchronous, dependency-
    free, and trivially testable (헌법 5: 단순함).
  - Naming: every typed error is ``V71Kiwoom*`` to avoid colliding with the
    HTTP-domain ``V71RateLimitError`` / ``V71AuthenticationError`` in
    ``src.web.v71.exceptions``. The Kiwoom errors describe broker-side
    business failures, not HTTP transport.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Literal

from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomError,
)

# ---------------------------------------------------------------------------
# Severity literal
# ---------------------------------------------------------------------------

Severity = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]

DEFAULT_BACKOFF_BASE_SECONDS = 1.0
DEFAULT_BACKOFF_CAP_SECONDS = 30.0


# ---------------------------------------------------------------------------
# Typed exception hierarchy
# ---------------------------------------------------------------------------


class V71KiwoomMappedError(V71KiwoomError):
    """Base for Kiwoom business errors that have a typed V7.1 mapping.

    Carries the original ``return_code`` / ``return_msg`` / ``api_id`` so
    callers can audit-log the broker-supplied detail without re-parsing,
    plus the V7.1 ``severity`` to drive notification routing.
    """

    def __init__(
        self,
        message: str,
        *,
        return_code: int,
        return_msg: str,
        api_id: str | None = None,
        severity: Severity = "HIGH",
    ) -> None:
        super().__init__(message)
        self.return_code = return_code
        self.return_msg = return_msg
        self.api_id = api_id
        self.severity: Severity = severity


class V71KiwoomRateLimitError(V71KiwoomMappedError):
    """Kiwoom 1700: 요청 개수 초과. Caller should backoff (see
    :func:`compute_backoff_seconds`) and retry."""


class V71KiwoomTokenInvalidError(V71KiwoomMappedError):
    """Kiwoom 8005: 토큰 유효 X. Distinct from ``V71TokenAuthError`` raised
    during au10001 issuance -- this code surfaces during a subsequent API
    call when the cached token has been invalidated. Caller should
    ``token_manager.refresh()`` and retry once."""


class V71KiwoomIPMismatchError(V71KiwoomMappedError):
    """Kiwoom 8010: 발급 IP ≠ 사용 IP. CRITICAL alert + safe-mode; never
    retry from this client (the IP is not going to change mid-flight)."""


class V71KiwoomEnvMismatchError(V71KiwoomMappedError):
    """Kiwoom 8030 / 8031: 실전/모의 (paper/live) 환경 불일치. Boot-time
    misconfiguration -- abort immediately, do not retry."""


class V71StockNotFoundError(V71KiwoomMappedError):
    """Kiwoom 1902: 종목 정보 없음. The stock_code does not exist; caller
    should reject the operation (e.g., delisted ticker registration)."""


class V71KiwoomInvalidInputError(V71KiwoomMappedError):
    """Kiwoom 1517: 입력값 형식 오류. Caller-provided payload was malformed."""


class V71KiwoomMarketNotFoundError(V71KiwoomMappedError):
    """Kiwoom 1901: 시장 코드 없음."""


class V71KiwoomRecursionError(V71KiwoomMappedError):
    """Kiwoom 1687: 재귀 호출 (호출 제한). Treat similar to rate-limit but
    typically caused by client-side recursion bug, not natural traffic."""


class V71KiwoomServerError(V71KiwoomMappedError):
    """Kiwoom 1999: 예기치 못한 에러 (server-side, business-layer).

    Note: this is a 200-OK response with ``return_code=1999``. Genuine HTTP
    5xx surfaces as ``V71KiwoomTransportError`` from ``kiwoom_client``, not
    here.
    """


class V71KiwoomUnknownError(V71KiwoomMappedError):
    """Fallback for any ``return_code`` not in the mapping table. Logged as
    HIGH so it gets attention without paging."""


# ---------------------------------------------------------------------------
# Mapping tables
# ---------------------------------------------------------------------------


# Read-only mapping (MappingProxyType) so a caller can never silently
# downgrade a CRITICAL code to LOW by mutating the dict at runtime.
ERROR_CODE_TO_TYPE: Mapping[int, type[V71KiwoomMappedError]] = MappingProxyType({
    1517: V71KiwoomInvalidInputError,
    1687: V71KiwoomRecursionError,
    1700: V71KiwoomRateLimitError,
    1901: V71KiwoomMarketNotFoundError,
    1902: V71StockNotFoundError,
    1999: V71KiwoomServerError,
    8005: V71KiwoomTokenInvalidError,
    8010: V71KiwoomIPMismatchError,
    8030: V71KiwoomEnvMismatchError,
    8031: V71KiwoomEnvMismatchError,
})


ERROR_CODE_TO_SEVERITY: Mapping[int, Severity] = MappingProxyType({
    1517: "LOW",
    1687: "LOW",
    1700: "HIGH",
    1901: "LOW",
    1902: "MEDIUM",
    1999: "HIGH",
    8005: "MEDIUM",
    8010: "CRITICAL",
    8030: "CRITICAL",
    8031: "CRITICAL",
})


# Codes that must never retry from this client (architectural / config).
_FATAL_CODES: frozenset[int] = frozenset({8010, 8030, 8031})

# Codes that signal a stale token -- caller should force_refresh + retry once.
_TOKEN_REFRESH_CODES: frozenset[int] = frozenset({8005})

# Codes that signal transient throttling -- caller should backoff + retry.
_BACKOFF_CODES: frozenset[int] = frozenset({1700})


# ---------------------------------------------------------------------------
# Pure classifier API
# ---------------------------------------------------------------------------


def severity_for(return_code: int) -> Severity:
    """Return the V7.1 severity bucket for a Kiwoom return_code.

    Unknown codes default to ``HIGH`` -- they get attention without paging
    a human (``CRITICAL`` is reserved for codes we *know* are dangerous).
    """
    return ERROR_CODE_TO_SEVERITY.get(return_code, "HIGH")


def map_business_error(
    business_error: V71KiwoomBusinessError,
) -> V71KiwoomMappedError:
    """Translate a raw ``V71KiwoomBusinessError`` into a typed mapped error.

    The caller is responsible for raising the result; this function only
    classifies. Severity is attached so the caller can decide whether to
    notify before re-raising.
    """
    return_code = business_error.return_code
    severity = severity_for(return_code)
    error_type = ERROR_CODE_TO_TYPE.get(return_code, V71KiwoomUnknownError)
    api_id = business_error.api_id
    return error_type(
        f"Kiwoom {return_code} ({api_id or 'unknown_api'}): {business_error.return_msg}",
        return_code=return_code,
        return_msg=business_error.return_msg,
        api_id=api_id,
        severity=severity,
    )


def is_fatal(error: V71KiwoomMappedError) -> bool:
    """True if the caller must abort and not retry.

    Fatal codes today: 8010 (IP mismatch), 8030 / 8031 (paper/live
    misconfig). All three are ``CRITICAL`` severity and require human
    intervention before another call can succeed.
    """
    return error.return_code in _FATAL_CODES


def should_force_token_refresh(error: V71KiwoomMappedError) -> bool:
    """True if the caller should ``token_manager.refresh()`` and retry once.

    Today only 8005 (token invalid) qualifies. The orchestrator must NOT
    refresh more than once per call -- repeated 8005 likely means the
    secret is wrong, which is a credential issue, not transient.
    """
    return error.return_code in _TOKEN_REFRESH_CODES


def should_retry_with_backoff(error: V71KiwoomMappedError) -> bool:
    """True if the caller should sleep (see :func:`compute_backoff_seconds`)
    and retry. Today only 1700 (rate limit) qualifies."""
    return error.return_code in _BACKOFF_CODES


def compute_backoff_seconds(
    attempt: int,
    *,
    base: float = DEFAULT_BACKOFF_BASE_SECONDS,
    cap: float = DEFAULT_BACKOFF_CAP_SECONDS,
) -> float:
    """Return exponential backoff for a 1-indexed retry ``attempt``.

    ``attempt=1 -> base`` (so the first retry waits one base interval).
    Subsequent attempts double the wait until capped at ``cap``.

    Raises ``ValueError`` for non-positive ``attempt`` / ``base`` / ``cap``
    or when ``cap < base``.
    """
    if attempt < 1:
        raise ValueError("attempt must be >= 1")
    if base <= 0:
        raise ValueError("base must be > 0")
    if cap <= 0:
        raise ValueError("cap must be > 0")
    if cap < base:
        raise ValueError("cap must be >= base")
    raw = base * (2 ** (attempt - 1))
    return min(raw, cap)


__all__ = [
    "DEFAULT_BACKOFF_BASE_SECONDS",
    "DEFAULT_BACKOFF_CAP_SECONDS",
    "ERROR_CODE_TO_SEVERITY",
    "ERROR_CODE_TO_TYPE",
    "Severity",
    "V71KiwoomEnvMismatchError",
    "V71KiwoomIPMismatchError",
    "V71KiwoomInvalidInputError",
    "V71KiwoomMappedError",
    "V71KiwoomMarketNotFoundError",
    "V71KiwoomRateLimitError",
    "V71KiwoomRecursionError",
    "V71KiwoomServerError",
    "V71KiwoomTokenInvalidError",
    "V71KiwoomUnknownError",
    "V71StockNotFoundError",
    "compute_backoff_seconds",
    "is_fatal",
    "map_business_error",
    "severity_for",
    "should_force_token_refresh",
    "should_retry_with_backoff",
]
