"""V71TokenManager -- Kiwoom OAuth (au10001) token lifecycle.

Spec sources:
  - KIWOOM_API_ANALYSIS.md §1 (au10001 OAuth, expires_dt format YYYYMMDDHHMMSS in KST)
  - KIWOOM_API_ANALYSIS.md error table (8005 token invalid, 8010 IP mismatch,
    8030/8031 paper/live env mismatch)
  - 12_SECURITY.md §6 (secret handling: token plaintext never logged)
  - 06_AGENTS_SPEC.md §1 verification (FAIL items 1-3 absorbed)

Design decisions captured during V71 Architect review:
  - Tokens are tz-aware. Kiwoom returns the expiry in KST (no zone in payload);
    we attach KST explicitly so all comparisons against ``datetime.now(UTC)``
    are correct across timezones.
  - ``base_url`` is decided at construction time and frozen -- runtime switching
    between paper and live would silently route orders to the wrong venue
    (헌법 3 충돌 금지).
  - Secrets are injected, never read here. ``.env`` -> wiring layer ->
    constructor. This module never sees ``os.environ``.
  - Token plaintext is never logged. ``_mask_token`` is the only path to a
    logger; callers MUST NOT format the token themselves.
  - Single-flight refresh via double-checked locking: callers in a hot path
    skip the lock when a fresh token is cached, and only one coroutine ever
    issues a network request when a refresh is needed.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIVE_BASE_URL = "https://api.kiwoom.com"
PAPER_BASE_URL = "https://mockapi.kiwoom.com"
OAUTH_TOKEN_PATH = "/oauth2/token"
OAUTH_REVOKE_PATH = "/oauth2/revoke"
OAUTH_ISSUE_API_ID = "au10001"
OAUTH_REVOKE_API_ID = "au10002"

# Kiwoom expiry timestamps are wall-clock KST without zone designator.
KST = timezone(timedelta(hours=9))

DEFAULT_REFRESH_WINDOW_SECONDS = 300  # 5 minutes per KIWOOM_API_ANALYSIS
DEFAULT_REQUEST_TIMEOUT_SECONDS = 10.0

# Mask helper bounds: token must be at least this long before partial reveal.
_MASK_REVEAL_PREFIX = 4
_MASK_REVEAL_SUFFIX = 4
_MASK_MIN_LENGTH = _MASK_REVEAL_PREFIX + _MASK_REVEAL_SUFFIX


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V71TokenError(Exception):
    """Base class for V7.1 OAuth token failures surfaced from this module."""


class V71TokenRequestError(V71TokenError):
    """Transport-level failure (network, timeout, non-2xx)."""


class V71TokenAuthError(V71TokenError):
    """Kiwoom rejected the credentials or returned a malformed payload.

    Raised when the response is 2xx but the body is missing required keys,
    or when ``return_code`` is non-zero.
    """


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _mask_token(token: str) -> str:
    """Return a log-safe representation of ``token``.

    Reveals first/last 4 characters once long enough; otherwise ``****``.
    Callers feeding tokens into a logger MUST route through this helper -- the
    raw token is a credential and must never appear in plaintext.
    """
    if not token or len(token) < _MASK_MIN_LENGTH:
        return "****"
    return f"{token[:_MASK_REVEAL_PREFIX]}****{token[-_MASK_REVEAL_SUFFIX:]}"


# ---------------------------------------------------------------------------
# Value object
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71TokenInfo:
    """Immutable snapshot of an issued OAuth token.

    All datetimes are tz-aware (KST for ``expires_at``, UTC for ``issued_at``).
    Equality is by value; identity is irrelevant because we replace this whole
    object on every refresh.

    The ``token`` field is ``repr=False`` so the default dataclass repr never
    leaks the credential. Use :meth:`masked` for any human-facing output.
    """

    token: str = field(repr=False)
    token_type: str = ""
    expires_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    issued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_paper: bool = False

    def __post_init__(self) -> None:
        if not self.token:
            raise ValueError("token must be non-empty")
        if self.expires_at.tzinfo is None:
            raise ValueError("expires_at must be tz-aware")
        if self.issued_at.tzinfo is None:
            raise ValueError("issued_at must be tz-aware")

    def __repr__(self) -> str:
        return (
            f"V71TokenInfo(token={self.masked()!r}, token_type={self.token_type!r}, "
            f"expires_at={self.expires_at.isoformat()}, issued_at={self.issued_at.isoformat()}, "
            f"is_paper={self.is_paper})"
        )

    def is_expired(self, *, now: datetime | None = None) -> bool:
        return (now or _utcnow()) >= self.expires_at

    def should_refresh(
        self,
        *,
        window_seconds: int = DEFAULT_REFRESH_WINDOW_SECONDS,
        now: datetime | None = None,
    ) -> bool:
        threshold = self.expires_at - timedelta(seconds=window_seconds)
        return (now or _utcnow()) >= threshold

    def remaining_seconds(self, *, now: datetime | None = None) -> int:
        delta = self.expires_at - (now or _utcnow())
        return max(0, int(delta.total_seconds()))

    def masked(self) -> str:
        return _mask_token(self.token)


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

ClockFn = Callable[[], datetime]
ClientFactoryFn = Callable[[], Awaitable[httpx.AsyncClient]]


class V71TokenManager:
    """Issues, refreshes, and revokes Kiwoom OAuth tokens.

    Lifecycle:
      - Construction is cheap; no network calls.
      - First ``get_token()`` triggers an OAuth issue under the lock.
      - Subsequent calls return the cached token until the refresh window
        opens (default 5 minutes before expiry), at which point one coroutine
        refreshes and the others reuse the result.
      - ``revoke()`` is best-effort and clears local state regardless of the
        server response (we want the client to forget the token even when the
        Kiwoom revoke call fails).

    Concurrency:
      - ``get_token()`` is safe to call from any number of coroutines. An
        ``asyncio.Lock`` plus double-checked caching ensures a single inflight
        OAuth request per refresh window.

    HTTP client ownership:
      - When the caller passes ``http_client``, this class will not close it.
      - When ``http_client`` is ``None``, we lazily create one and close it on
        :meth:`aclose` / ``async with``. The default client uses the
        ``request_timeout`` argument as the read+connect+write+pool timeout.
    """

    def __init__(
        self,
        *,
        app_key: str,
        app_secret: str,
        is_paper: bool = False,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        clock: ClockFn | None = None,
        refresh_window_seconds: int = DEFAULT_REFRESH_WINDOW_SECONDS,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if not app_key or not app_secret:
            raise ValueError("app_key and app_secret are required")
        if refresh_window_seconds < 0:
            raise ValueError("refresh_window_seconds must be >= 0")
        if request_timeout <= 0:
            raise ValueError("request_timeout must be > 0")

        self._app_key = app_key
        self._app_secret = app_secret
        self._is_paper = is_paper
        # Frozen at construction; runtime venue switches are forbidden.
        resolved_base = (
            base_url or (PAPER_BASE_URL if is_paper else LIVE_BASE_URL)
        ).rstrip("/")
        # Security M-1: refuse cleartext transports. Kiwoom credentials must
        # never travel over HTTP/file/whatever a typo or test fixture supplies.
        if not resolved_base.lower().startswith("https://"):
            raise ValueError(
                f"base_url must use https:// (got {resolved_base!r}); "
                "Kiwoom credentials must never travel over cleartext"
            )
        self._base_url = resolved_base
        self._refresh_window = refresh_window_seconds
        self._request_timeout = request_timeout
        self._clock: ClockFn = clock or _utcnow
        self._http_client = http_client
        self._owns_client = http_client is None
        self._lock = asyncio.Lock()
        self._current: V71TokenInfo | None = None

    # ----- Public API --------------------------------------------------

    async def get_token(self) -> str:
        """Return a non-expired access token, refreshing if necessary."""
        cached = self._current
        if cached is not None and not cached.should_refresh(
            window_seconds=self._refresh_window, now=self._clock(),
        ):
            return cached.token

        async with self._lock:
            cached = self._current  # re-read under the lock
            if cached is not None and not cached.should_refresh(
                window_seconds=self._refresh_window, now=self._clock(),
            ):
                return cached.token
            new_token = await self._issue_token_locked()
            self._current = new_token
            return new_token.token

    async def refresh(self) -> V71TokenInfo:
        """Force a refresh regardless of the cached token's freshness."""
        async with self._lock:
            new_token = await self._issue_token_locked()
            self._current = new_token
            return new_token

    async def revoke(self) -> None:
        """Best-effort revoke. Always clears local state."""
        async with self._lock:
            cached = self._current
            self._current = None
            if cached is None:
                return
            try:
                await self._call_revoke_locked(cached.token)
            except Exception as exc:  # noqa: BLE001 -- best-effort path
                logger.warning(
                    "v71_token_revoke_failed",
                    is_paper=self._is_paper,
                    error=type(exc).__name__,
                )

    async def aclose(self) -> None:
        """Release the lazily-created HTTP client (if owned)."""
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self) -> V71TokenManager:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    # ----- Properties --------------------------------------------------

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def current_token(self) -> V71TokenInfo | None:
        return self._current

    # ----- Internal ----------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            # Security L-2: ignore HTTPS_PROXY/HTTP_PROXY/SSL_CERT_FILE env
            # vars. Wiring layer that needs a corporate proxy must construct
            # its own client and inject it through the constructor.
            self._http_client = httpx.AsyncClient(
                timeout=self._request_timeout,
                trust_env=False,
            )
            self._owns_client = True
        return self._http_client

    def _scrub_response_body(self, text: str | None) -> str:
        """Trim and redact echoed-back secrets from server-supplied text.

        Some gateways include parts of the request body in error messages. We
        defensively remove any substring of ``app_key`` / ``app_secret`` (or
        the current token) before that text reaches an exception or log.
        """
        if not text:
            return ""
        scrubbed = text[:200]
        for secret in (self._app_key, self._app_secret):
            if secret and secret in scrubbed:
                scrubbed = scrubbed.replace(secret, _mask_token(secret))
        cur = self._current
        if cur is not None and cur.token in scrubbed:
            scrubbed = scrubbed.replace(cur.token, _mask_token(cur.token))
        return scrubbed

    def __repr__(self) -> str:
        return (
            f"V71TokenManager(is_paper={self._is_paper}, base_url={self._base_url!r}, "
            f"has_token={self._current is not None})"
        )

    async def _issue_token_locked(self) -> V71TokenInfo:
        url = f"{self._base_url}{OAUTH_TOKEN_PATH}"
        headers = {
            "api-id": OAUTH_ISSUE_API_ID,
            "Content-Type": "application/json;charset=UTF-8",
        }
        body = {
            "grant_type": "client_credentials",
            "appkey": self._app_key,
            "secretkey": self._app_secret,
        }

        client = await self._ensure_client()
        try:
            resp = await client.post(
                url,
                headers=headers,
                json=body,
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "v71_token_issue_transport_error",
                is_paper=self._is_paper,
                error=type(exc).__name__,
            )
            raise V71TokenRequestError(f"OAuth transport failure: {exc}") from exc

        if resp.status_code >= 400:
            logger.warning(
                "v71_token_issue_http_error",
                is_paper=self._is_paper,
                status_code=resp.status_code,
            )
            raise V71TokenRequestError(
                f"OAuth HTTP {resp.status_code}: {self._scrub_response_body(resp.text)}"
            )

        try:
            data = resp.json()
        except ValueError as exc:
            raise V71TokenAuthError(
                f"OAuth response not JSON: {self._scrub_response_body(resp.text)}"
            ) from exc

        return_code = data.get("return_code")
        if return_code not in (None, 0):
            raise V71TokenAuthError(
                f"OAuth return_code={return_code} msg={data.get('return_msg')!r}"
            )

        token = data.get("token")
        token_type = data.get("token_type", "bearer")
        expires_dt_str = data.get("expires_dt")
        if not token or not expires_dt_str:
            raise V71TokenAuthError(
                f"OAuth response missing token/expires_dt: keys={sorted(data.keys())}"
            )

        try:
            naive_kst = datetime.strptime(expires_dt_str, "%Y%m%d%H%M%S")
        except ValueError as exc:
            raise V71TokenAuthError(
                f"OAuth expires_dt format invalid: {expires_dt_str!r}"
            ) from exc

        expires_at = naive_kst.replace(tzinfo=KST)
        info = V71TokenInfo(
            token=token,
            token_type=token_type,
            expires_at=expires_at,
            issued_at=self._clock(),
            is_paper=self._is_paper,
        )
        logger.info(
            "v71_token_issued",
            is_paper=self._is_paper,
            token=info.masked(),
            expires_at=info.expires_at.isoformat(),
            remaining_seconds=info.remaining_seconds(now=self._clock()),
        )
        return info

    async def _call_revoke_locked(self, token: str) -> None:
        url = f"{self._base_url}{OAUTH_REVOKE_PATH}"
        headers = {
            "api-id": OAUTH_REVOKE_API_ID,
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
        }
        body = {
            "appkey": self._app_key,
            "secretkey": self._app_secret,
            "token": token,
        }
        client = await self._ensure_client()
        resp = await client.post(
            url,
            headers=headers,
            json=body,
            timeout=self._request_timeout,
        )
        if resp.status_code >= 400:
            logger.warning(
                "v71_token_revoke_http_error",
                is_paper=self._is_paper,
                status_code=resp.status_code,
                token=_mask_token(token),
            )
        else:
            logger.info(
                "v71_token_revoked",
                is_paper=self._is_paper,
                token=_mask_token(token),
            )


__all__ = [
    "DEFAULT_REFRESH_WINDOW_SECONDS",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "KST",
    "LIVE_BASE_URL",
    "OAUTH_ISSUE_API_ID",
    "OAUTH_REVOKE_API_ID",
    "OAUTH_REVOKE_PATH",
    "OAUTH_TOKEN_PATH",
    "PAPER_BASE_URL",
    "V71TokenAuthError",
    "V71TokenError",
    "V71TokenInfo",
    "V71TokenManager",
    "V71TokenRequestError",
]
