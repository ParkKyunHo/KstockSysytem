"""V71KiwoomClient -- Kiwoom REST transport for the 5 core APIs.

Spec sources:
  - KIWOOM_API_ANALYSIS.md §1~§7 (au10001 / ka10080 / ka10081 /
    kt10000~10003 / ka10075 / kt00018)
  - 04_ARCHITECTURE.md §7.1 (Kiwoom REST)
  - 07_SKILLS_SPEC.md §1 (kiwoom_api_skill Protocol -- this client is the
    transport that satisfies it; the skill-layer wiring lands in a
    follow-up unit)
  - 06_AGENTS_SPEC.md §1 V71 Architect verification (P0/P1 items absorbed)

Design summary (from architect review):
  - Single ``request()`` seam acquires the rate-limit token, fetches a
    Bearer (single-flight via ``V71TokenManager``), executes the HTTP call,
    and returns a typed ``V71KiwoomResponse``. Domain methods are typed
    wrappers that build the api_id-specific payload and delegate.
  - Errors split into transport (HTTP / JSON / network -- ``V71KiwoomTransportError``)
    and business (``return_code != 0`` -- ``V71KiwoomBusinessError`` carrying
    ``return_code`` / ``return_msg`` / ``api_id`` for ``error_mapper`` to
    branch on in P5-Kiwoom-3).
  - Out of scope (deferred):
      * 1700 (rate-limit) exponential backoff -- error_mapper layer
      * 8005 (token invalid) auto refresh+retry -- skill layer
      * cont_yn / next_key automatic pagination -- caller responsibility
      * kiwoom_api_skill.call_kiwoom_api NotImpl wiring -- separate unit
      * ExchangeAdapter Protocol (get_orderbook / send_order /
        get_order_status) -- needs ka10004 + dataclass adaptation
  - Security: HTTPS scheme enforced; httpx ``trust_env=False`` to ignore
    rogue proxy env vars; transport-error message scrubs any echoed-back
    bearer token (token_manager pattern).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from src.core.v71.exchange.rate_limiter import V71RateLimiter
from src.core.v71.exchange.token_manager import V71TokenManager
from src.core.v71.v71_constants import V71Constants
from src.utils.logger import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

LIVE_BASE_URL = "https://api.kiwoom.com"
PAPER_BASE_URL = "https://mockapi.kiwoom.com"

CHART_PATH = "/api/dostk/chart"
ORDER_PATH = "/api/dostk/ordr"
ACCOUNT_PATH = "/api/dostk/acnt"

API_ID_MINUTE_CHART = "ka10080"
API_ID_DAILY_CHART = "ka10081"
API_ID_BUY = "kt10000"
API_ID_SELL = "kt10001"
API_ID_MODIFY = "kt10002"
API_ID_CANCEL = "kt10003"
API_ID_PENDING_ORDERS = "ka10075"
API_ID_ACCOUNT_BALANCE = "kt00018"

DEFAULT_REQUEST_TIMEOUT_SECONDS = float(V71Constants.API_TIMEOUT_SECONDS)

# Mask helper (mirrors token_manager._mask_token; kept local to avoid
# importing a private helper across modules).
_MASK_REVEAL_PREFIX = 4
_MASK_REVEAL_SUFFIX = 4
_MASK_MIN_LENGTH = _MASK_REVEAL_PREFIX + _MASK_REVEAL_SUFFIX


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V71KiwoomError(Exception):
    """Base class for V7.1 Kiwoom client failures."""


class V71KiwoomTransportError(V71KiwoomError):
    """Network / HTTP / JSON failure -- never reached the business layer."""


class V71KiwoomBusinessError(V71KiwoomError):
    """Server returned 200 but ``return_code != 0``.

    The instance attributes are the contract that ``error_mapper`` (P5-Kiwoom-3)
    consumes to branch on Kiwoom error codes -- 1700 (rate-limit), 8005
    (token invalid), 8010 (IP mismatch), 8030 / 8031 (paper / live mismatch).
    """

    def __init__(
        self,
        message: str,
        *,
        return_code: int,
        return_msg: str,
        api_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.return_code = return_code
        self.return_msg = return_msg
        self.api_id = api_id


# ---------------------------------------------------------------------------
# Trade type (Kiwoom ``trde_tp`` direct mapping)
# ---------------------------------------------------------------------------


class V71KiwoomTradeType(Enum):
    """Direct mapping of Kiwoom's ``trde_tp`` field. P5 ships LIMIT + MARKET;
    BEST_LIMIT (``"6"``) and PRIORITY (``"7"``) ship in a follow-up PR
    when 02_TRADING_RULES needs them.

    Distinct from ``V71OrderType`` (kiwoom_api_skill.py) which is an
    abstract pricing mode -- this enum carries the wire-level code value.
    """

    LIMIT = "0"   # 보통 (지정가)
    MARKET = "3"  # 시장가


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71KiwoomResponse:
    """Typed envelope for a successful Kiwoom REST call.

    ``data`` is the JSON body with the ``return_code`` / ``return_msg``
    envelope keys removed -- callers parse the payload itself.
    ``cont_yn`` and ``next_key`` are the pagination headers Kiwoom returns
    on long lists (ka10075, kt00018, ka10086 etc.). This client does NOT
    auto-paginate; the caller is responsible for looping while ``cont_yn ==
    "Y"`` and feeding ``next_key`` back into the next request.
    """

    success: bool
    api_id: str
    data: dict | None
    return_code: int
    return_msg: str
    cont_yn: str
    next_key: str
    duration_ms: int


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mask_secret(value: str) -> str:
    """Log-safe partial reveal -- 4 prefix + 4 suffix, ``****`` otherwise."""
    if not value or len(value) < _MASK_MIN_LENGTH:
        return "****"
    return f"{value[:_MASK_REVEAL_PREFIX]}****{value[-_MASK_REVEAL_SUFFIX:]}"


def _scrub_response(text: str | None, token: str | None) -> str:
    """Trim to 200 chars and redact any echoed-back bearer token.

    Some upstream gateways include parts of the request -- including
    Authorization headers -- in 4xx error bodies. Defensive scrubbing
    keeps the credential out of exception messages and logs.
    """
    if not text:
        return ""
    scrubbed = text[:200]
    if token and token in scrubbed:
        scrubbed = scrubbed.replace(token, _mask_secret(token))
    return scrubbed


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class V71KiwoomClient:
    """REST transport for the 5 core Kiwoom APIs.

    Lifecycle:
      - Construction is cheap; no network calls.
      - Each public call: ``rate_limiter.acquire()`` -> ``token_manager.get_token()`` ->
        ``http.request()`` -> ``V71KiwoomResponse`` (or raise).
      - ``aclose()`` only closes a lazily-created HTTP client; an externally
        injected client survives for the caller to manage.

    DI slots (``V7.1 Architect`` review):
      - ``token_manager``: V71TokenManager instance providing the Bearer token.
      - ``rate_limiter``: V71RateLimiter throttling at 4.5/sec live (0.33/sec paper).
      - ``http_client``: optional pre-built httpx.AsyncClient (test fixtures
        use ``httpx.MockTransport``-backed clients here).
    """

    def __init__(
        self,
        *,
        token_manager: V71TokenManager,
        rate_limiter: V71RateLimiter,
        is_paper: bool = False,
        base_url: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        request_timeout: float = DEFAULT_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        if request_timeout <= 0:
            raise ValueError("request_timeout must be > 0")

        resolved_base = (
            base_url or (PAPER_BASE_URL if is_paper else LIVE_BASE_URL)
        ).rstrip("/")
        if not resolved_base.lower().startswith("https://"):
            raise ValueError(
                f"base_url must use https:// (got {resolved_base!r}); "
                "Kiwoom credentials must never travel over cleartext"
            )

        self._token_manager = token_manager
        self._rate_limiter = rate_limiter
        self._is_paper = is_paper
        self._base_url = resolved_base
        self._request_timeout = request_timeout
        self._http_client = http_client
        self._owns_client = http_client is None
        # Single-flight lock so the lazy-init path doesn't leak a parallel
        # AsyncClient when two callers race past the ``is None`` check.
        self._client_lock = asyncio.Lock()

    # ----- Properties --------------------------------------------------

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def is_paper(self) -> bool:
        return self._is_paper

    # ----- Lifecycle ---------------------------------------------------

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self) -> V71KiwoomClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return (
            f"V71KiwoomClient(is_paper={self._is_paper}, "
            f"base_url={self._base_url!r})"
        )

    # ----- Internal ----------------------------------------------------

    async def _ensure_client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        # Race-safe lazy creation: re-check under the lock so two concurrent
        # callers can't both build an AsyncClient and leak the loser.
        async with self._client_lock:
            if self._http_client is None:
                self._http_client = httpx.AsyncClient(
                    timeout=self._request_timeout,
                    trust_env=False,
                )
                self._owns_client = True
            return self._http_client

    # ----- Raw seam ----------------------------------------------------

    async def request(
        self,
        *,
        api_id: str,
        endpoint: str,
        payload: Mapping[str, Any],
        method: str = "POST",
        cont_yn: str = "N",
        next_key: str = "",
    ) -> V71KiwoomResponse:
        """Single seam for all Kiwoom REST calls.

        The 5 domain methods below are convenience wrappers around this. New
        APIs (e.g. ka10004 호가, ka10054 VI 발동종목) can use ``request``
        directly until they earn a typed wrapper.

        Raises:
          ``V71KiwoomTransportError``: network / 4xx / 5xx / non-JSON response.
          ``V71KiwoomBusinessError``: 200 response with ``return_code != 0``.
            The exception attributes (``return_code`` / ``return_msg`` /
            ``api_id``) are the input ``error_mapper`` (P5-Kiwoom-3)
            consumes to branch into ``V71RateLimitExceeded`` / ``V71TokenAuthError``
            / etc.
        """
        await self._rate_limiter.acquire()
        token = await self._token_manager.get_token()

        url = f"{self._base_url}{endpoint}"
        headers = {
            "api-id": api_id,
            "authorization": f"Bearer {token}",
            "Content-Type": "application/json;charset=UTF-8",
            "cont-yn": cont_yn,
            "next-key": next_key,
        }

        client = await self._ensure_client()
        start = time.monotonic()
        try:
            resp = await client.request(
                method,
                url,
                headers=headers,
                json=dict(payload),
                timeout=self._request_timeout,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "v71_kiwoom_transport_error",
                api_id=api_id,
                error=type(exc).__name__,
            )
            raise V71KiwoomTransportError(
                f"Kiwoom transport failure ({api_id}): {type(exc).__name__}"
            ) from exc

        duration_ms = int((time.monotonic() - start) * 1000)

        if resp.status_code >= 400:
            scrubbed = _scrub_response(resp.text, token)
            logger.warning(
                "v71_kiwoom_http_error",
                api_id=api_id,
                status_code=resp.status_code,
                duration_ms=duration_ms,
            )
            raise V71KiwoomTransportError(
                f"Kiwoom HTTP {resp.status_code} ({api_id}): {scrubbed}"
            )

        try:
            body = resp.json()
        except ValueError as exc:
            scrubbed = _scrub_response(resp.text, token)
            raise V71KiwoomTransportError(
                f"Kiwoom response not JSON ({api_id}): {scrubbed}"
            ) from exc

        if not isinstance(body, dict):
            raise V71KiwoomTransportError(
                f"Kiwoom response is not an object ({api_id})"
            )

        return_code = int(body.get("return_code", 0))
        return_msg = str(body.get("return_msg", ""))
        data = {k: v for k, v in body.items() if k not in ("return_code", "return_msg")}

        cont_yn_resp = resp.headers.get("cont-yn", "N")
        next_key_resp = resp.headers.get("next-key", "")

        if return_code != 0:
            logger.info(
                "v71_kiwoom_business_error",
                api_id=api_id,
                return_code=return_code,
                duration_ms=duration_ms,
            )
            raise V71KiwoomBusinessError(
                f"Kiwoom return_code={return_code} ({api_id}): {return_msg}",
                return_code=return_code,
                return_msg=return_msg,
                api_id=api_id,
            )

        logger.debug(
            "v71_kiwoom_request_ok",
            api_id=api_id,
            duration_ms=duration_ms,
            cont_yn=cont_yn_resp,
        )

        return V71KiwoomResponse(
            success=True,
            api_id=api_id,
            data=data,
            return_code=return_code,
            return_msg=return_msg,
            cont_yn=cont_yn_resp,
            next_key=next_key_resp,
            duration_ms=duration_ms,
        )

    # ----- Domain methods (typed wrappers) -----------------------------

    async def get_minute_chart(
        self,
        *,
        stock_code: str,
        tic_scope: str = "3",
        upd_stkpc_tp: str = "1",
        cont_yn: str = "N",
        next_key: str = "",
    ) -> V71KiwoomResponse:
        """ka10080 분봉차트. ``tic_scope`` 단위: 1/3/5/10/15/30/45/60 (분)."""
        return await self.request(
            api_id=API_ID_MINUTE_CHART,
            endpoint=CHART_PATH,
            payload={
                "stk_cd": stock_code,
                "tic_scope": tic_scope,
                "upd_stkpc_tp": upd_stkpc_tp,
            },
            cont_yn=cont_yn,
            next_key=next_key,
        )

    async def get_daily_chart(
        self,
        *,
        stock_code: str,
        base_date: str,
        upd_stkpc_tp: str = "1",
        cont_yn: str = "N",
        next_key: str = "",
    ) -> V71KiwoomResponse:
        """ka10081 일봉차트. ``base_date`` 형식: YYYYMMDD."""
        return await self.request(
            api_id=API_ID_DAILY_CHART,
            endpoint=CHART_PATH,
            payload={
                "stk_cd": stock_code,
                "base_dt": base_date,
                "upd_stkpc_tp": upd_stkpc_tp,
            },
            cont_yn=cont_yn,
            next_key=next_key,
        )

    async def place_buy_order(
        self,
        *,
        stock_code: str,
        quantity: int,
        price: int | None,
        trade_type: V71KiwoomTradeType,
        dmst_stex_tp: str = "KRX",
    ) -> V71KiwoomResponse:
        """kt10000 매수주문. LIMIT 시 ``price > 0`` 필수, MARKET 시 ``price`` 무시.

        WARNING: 본 메서드는 자동 retry하지 않습니다. ``V71KiwoomTransportError``
        발생 시 주문이 실제로 접수되었는지 ``get_pending_orders`` (ka10075) 또는
        ``get_account_balance`` (kt00018)로 확인 후에만 재시도하십시오. Kiwoom
        REST에는 ``client_order_id`` 필드가 없어 자동 멱등성을 보장할 수 없으며,
        맹목적 retry는 이중 주문을 만들 수 있습니다.
        """
        return await self.request(
            api_id=API_ID_BUY,
            endpoint=ORDER_PATH,
            payload=self._build_order_payload(
                stock_code=stock_code,
                quantity=quantity,
                price=price,
                trade_type=trade_type,
                dmst_stex_tp=dmst_stex_tp,
            ),
        )

    async def place_sell_order(
        self,
        *,
        stock_code: str,
        quantity: int,
        price: int | None,
        trade_type: V71KiwoomTradeType,
        dmst_stex_tp: str = "KRX",
    ) -> V71KiwoomResponse:
        """kt10001 매도주문. 형식은 kt10000과 동일.

        WARNING: ``place_buy_order``의 retry 경고를 동일하게 적용. transport
        에러 후 맹목적 retry는 이중 매도를 만들 수 있습니다.
        """
        return await self.request(
            api_id=API_ID_SELL,
            endpoint=ORDER_PATH,
            payload=self._build_order_payload(
                stock_code=stock_code,
                quantity=quantity,
                price=price,
                trade_type=trade_type,
                dmst_stex_tp=dmst_stex_tp,
            ),
        )

    @staticmethod
    def _build_order_payload(
        *,
        stock_code: str,
        quantity: int,
        price: int | None,
        trade_type: V71KiwoomTradeType,
        dmst_stex_tp: str,
    ) -> dict[str, Any]:
        if quantity <= 0:
            raise ValueError("quantity must be > 0")
        if trade_type == V71KiwoomTradeType.LIMIT and (price is None or price <= 0):
            raise ValueError("LIMIT order requires price > 0")
        body: dict[str, Any] = {
            "dmst_stex_tp": dmst_stex_tp,
            "stk_cd": stock_code,
            "ord_qty": str(quantity),
            "trde_tp": trade_type.value,
        }
        if trade_type == V71KiwoomTradeType.LIMIT:
            body["ord_uv"] = str(price)
        return body

    async def modify_order(
        self,
        *,
        orig_order_no: str,
        stock_code: str,
        modify_qty: int,
        modify_price: int,
        dmst_stex_tp: str = "KRX",
    ) -> V71KiwoomResponse:
        """kt10002 정정주문."""
        if not orig_order_no:
            raise ValueError("orig_order_no is required")
        if modify_qty <= 0:
            raise ValueError("modify_qty must be > 0")
        if modify_price <= 0:
            raise ValueError("modify_price must be > 0")
        return await self.request(
            api_id=API_ID_MODIFY,
            endpoint=ORDER_PATH,
            payload={
                "dmst_stex_tp": dmst_stex_tp,
                "orig_ord_no": orig_order_no,
                "stk_cd": stock_code,
                "mdfy_qty": str(modify_qty),
                "mdfy_uv": str(modify_price),
            },
        )

    async def cancel_order(
        self,
        *,
        orig_order_no: str,
        stock_code: str,
        cancel_qty: int = 0,
        dmst_stex_tp: str = "KRX",
    ) -> V71KiwoomResponse:
        """kt10003 취소주문. ``cancel_qty=0`` 은 잔량 전부 취소 (Kiwoom 사양)."""
        if not orig_order_no:
            raise ValueError("orig_order_no is required")
        if cancel_qty < 0:
            raise ValueError("cancel_qty must be >= 0 (0 means cancel remainder)")
        return await self.request(
            api_id=API_ID_CANCEL,
            endpoint=ORDER_PATH,
            payload={
                "dmst_stex_tp": dmst_stex_tp,
                "orig_ord_no": orig_order_no,
                "stk_cd": stock_code,
                "cncl_qty": str(cancel_qty),
            },
        )

    async def get_pending_orders(
        self,
        *,
        all_stk_tp: str = "0",
        trde_tp: str = "0",
        stex_tp: str = "0",
        stock_code: str | None = None,
        cont_yn: str = "N",
        next_key: str = "",
    ) -> V71KiwoomResponse:
        """ka10075 미체결조회.

        ``all_stk_tp``: 0=전체 / 1=종목 (1이면 ``stock_code`` 필요).
        ``trde_tp``: 0=전체 / 1=매도 / 2=매수.
        ``stex_tp``: 0=통합 / 1=KRX / 2=NXT.
        """
        payload: dict[str, Any] = {
            "all_stk_tp": all_stk_tp,
            "trde_tp": trde_tp,
            "stex_tp": stex_tp,
        }
        if stock_code:
            payload["stk_cd"] = stock_code
        return await self.request(
            api_id=API_ID_PENDING_ORDERS,
            endpoint=ACCOUNT_PATH,
            payload=payload,
            cont_yn=cont_yn,
            next_key=next_key,
        )

    async def get_account_balance(
        self,
        *,
        qry_tp: str = "1",
        dmst_stex_tp: str = "KRX",
        cont_yn: str = "N",
        next_key: str = "",
    ) -> V71KiwoomResponse:
        """kt00018 계좌평가잔고 (Reconciler 핵심).

        ``qry_tp``: 1=합산 / 2=개별.
        """
        return await self.request(
            api_id=API_ID_ACCOUNT_BALANCE,
            endpoint=ACCOUNT_PATH,
            payload={
                "qry_tp": qry_tp,
                "dmst_stex_tp": dmst_stex_tp,
            },
            cont_yn=cont_yn,
            next_key=next_key,
        )


__all__ = [
    "ACCOUNT_PATH",
    "API_ID_ACCOUNT_BALANCE",
    "API_ID_BUY",
    "API_ID_CANCEL",
    "API_ID_DAILY_CHART",
    "API_ID_MINUTE_CHART",
    "API_ID_MODIFY",
    "API_ID_PENDING_ORDERS",
    "API_ID_SELL",
    "CHART_PATH",
    "DEFAULT_REQUEST_TIMEOUT_SECONDS",
    "LIVE_BASE_URL",
    "ORDER_PATH",
    "PAPER_BASE_URL",
    "V71KiwoomBusinessError",
    "V71KiwoomClient",
    "V71KiwoomError",
    "V71KiwoomResponse",
    "V71KiwoomTradeType",
    "V71KiwoomTransportError",
]
