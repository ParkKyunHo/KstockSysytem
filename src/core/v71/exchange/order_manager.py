"""V71OrderManager -- Kiwoom order submit + v71_orders DB INSERT + WS reconcile.

Spec sources:
  - KIWOOM_API_ANALYSIS.md §5 (kt10000 매수 / kt10001 매도 / kt10002 정정 /
    kt10003 취소) + §9 (WebSocket 00 주문체결 매칭, 9203 ord_no / 913 상태 /
    910 체결가 / 911 체결량 / 902 미체결 / 904 원주문 / 919 거부사유)
  - 02_TRADING_RULES.md §4 (매수 실행 -- retry orchestration은 caller 책임,
    본 단위는 단일 발주만)
  - 02_TRADING_RULES.md §6 (평단가 -- 본 단위 미구현, V71PositionManager 위임)
  - 03_DATA_MODEL.md §2.4 (v71_orders 테이블, migration 018, kiwoom_order_no
    NOT NULL UNIQUE + kiwoom_orig_order_no nullable)
  - 06_AGENTS_SPEC.md §1 (V71 Architect verification, P0/P1/P2 항목 모두 반영)
  - 12_SECURITY.md §6 (시크릿 / PII 로그 정책 -- raw payload에 토큰 미포함,
    logger 메시지에 가격/수량 노출 최소화)

Design summary (architect-approved):
  * submit_order: kiwoom REST 호출 → ord_no 확정 후 INSERT. NOT NULL UNIQUE
    충돌을 원천 회피 (kiwoom 응답 받은 직후에만 INSERT). transport / business
    error 시 DB 미변경 → caller가 ka10075 (미체결) 또는 kt00018 (잔고)으로
    상태 확인 후 명시적 재시도 결정. Kiwoom REST에 client_order_id 필드가
    없어 자동 retry는 이중 주문 위험 (KIWOOM_API_ANALYSIS.md §1100 line).
  * cancel_order / modify_order: 키움이 새 ord_no를 반환하므로 *새 row*
    INSERT (kiwoom_orig_order_no=원주문, direction=원주문 direction 복제).
    원주문 row의 state는 WebSocket 00 이벤트 ("취소" / "확인") 처리 시 갱신.
    migration 018 (line 46) 이 명시적으로 이 패턴 지원.
  * on_websocket_order_event: 9203 (ord_no) 매칭 후 atomic UPDATE
    (filled_quantity 누적 + filled_avg_price 가중평균 + state 변경) -- 단일
    SQL UPDATE + per-order asyncio.Lock으로 부분 체결 race 방지. 매칭 실패
    (외부 도구 발주 등) → on_manual_order 콜백 (선택).
  * 평단가 갱신은 V71PositionManager 위임. position_id가 있는 fill 이벤트는
    V71OrderFillEvent로 정규화하여 on_position_fill 콜백에 전달. avg_price_skill
    호출은 후속 단위 책임.
  * 콜백 isolation: 모든 콜백 호출은 try/except + logger.error (raise 안 함)
    -- frame locals 미노출 (Security M1, kiwoom_websocket.py 패턴 일관).

Out of scope (architect-confirmed, follow-up units):
  * 매수 retry orchestration (지정가 1호가 위 → 5초 × 3회 → 시장가, 02 §4.2):
    BoxEntryExecutor 또는 OrderRetryOrchestrator 후속 단위 책임. 본 단위는
    단일 발주만 처리한다.
  * 평단가 + 이벤트 리셋 + 손절선 단계 (02 §6 / §5.4): V71PositionManager 단위
    avg_price_skill / exit_calc_skill 호출 (PRD §7.4 / §7.3). 본 단위는
    V71OrderFillEvent 만 발행한다.
  * 알림 발송 (notification_skill, PRD §7.6): orchestrator 책임.
  * 키움 잔고 정합성 (kt00018, 시나리오 A/B/C/D/E): V71Reconciler (P5-Kiwoom-6)
    후속 단위 책임.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from types import MappingProxyType
from typing import Any, Final
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.v71.exchange.error_mapper import (
    map_business_error,
)
from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomResponse,
    V71KiwoomTradeType,
    V71KiwoomTransportError,
)
from src.core.v71.exchange.kiwoom_websocket import (
    V71KiwoomChannelType,
    V71WebSocketMessage,
)
from src.database.models_v71 import (
    OrderDirection,
    OrderState,
    OrderTradeType,
    V71Order,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Wire-level constants (KIWOOM_API_ANALYSIS.md §9)
#
# These are NOT trading-rule magic numbers; they are wire codes Kiwoom uses
# inside WebSocket 00 (주문체결) frames. Living here (next to the consumer)
# instead of in V71Constants keeps the trading-rule constants file focused on
# 02_TRADING_RULES.md content. (Architect P2.12 결정)
# ---------------------------------------------------------------------------


WS_FIELD: Mapping[str, str] = MappingProxyType({
    "ORDER_NO": "9203",
    "ORDER_STATE": "913",
    "BUY_SELL_TYPE": "907",       # "1" 매도, "2" 매수
    "FILL_PRICE": "910",
    "FILL_QUANTITY": "911",
    "REMAINING_QUANTITY": "902",
    "ORIGINAL_ORDER_NO": "904",
    "REJECT_REASON": "919",
    "STOCK_CODE": "9001",
})


KIWOOM_STATE_ACCEPTED = "접수"
KIWOOM_STATE_FILLED = "체결"
KIWOOM_STATE_CONFIRMED = "확인"   # 정정/취소 확인
KIWOOM_STATE_CANCELLED = "취소"
KIWOOM_STATE_REJECTED = "거부"


# OrderTradeType (domain) -> V71KiwoomTradeType (wire). Trade types not in
# this map are explicitly unsupported by V71OrderManager; the constructor of
# V71OrderRequest rejects them up front so callers fail fast.
_TRADE_TYPE_TO_KIWOOM: Mapping[OrderTradeType, V71KiwoomTradeType] = MappingProxyType({
    OrderTradeType.LIMIT: V71KiwoomTradeType.LIMIT,
    OrderTradeType.MARKET: V71KiwoomTradeType.MARKET,
})


# Exchange code whitelist (KIWOOM_API_ANALYSIS.md §5 — KRX / NXT / SOR only).
# Free-form strings would silently propagate to Kiwoom and surface as
# 8030/8031 mismatch errors hours later; reject at the domain boundary.
VALID_EXCHANGES: Final[frozenset[str]] = frozenset({"KRX", "NXT", "SOR"})


# Response keys the audit copy must redact even if Kiwoom were ever to echo
# them back. Order responses (kt10000~10003) never carry these today; the
# defence-in-depth is so future helpers (kt00018 reconciler) reusing
# ``_sanitize_response`` cannot accidentally persist them.
_FORBIDDEN_RESPONSE_KEYS: Final[frozenset[str]] = frozenset({
    "token",
    "access_token",
    "Authorization",
    "authorization",
    "app_key",
    "appkey",
    "app_secret",
    "secretkey",
    "secret",
})


_REDACTED = "***REDACTED***"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class V71OrderError(Exception):
    """Base class for V71OrderManager domain failures."""


class V71OrderSubmissionFailed(V71OrderError):
    """Kiwoom rejected the request (transport or business) -- v71_orders row
    NOT created. Callers verifying via ka10075 / kt00018 may retry once they
    have confirmed the broker-side state."""

    def __init__(
        self,
        message: str,
        *,
        api_id: str | None = None,
        return_code: int | None = None,
        return_msg: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.api_id = api_id
        self.return_code = return_code
        self.return_msg = return_msg
        self.__cause__ = cause


class V71OrderNotFoundError(V71OrderError):
    """v71_orders has no row matching the given kiwoom_order_no."""


class V71OrderUnsupportedError(V71OrderError):
    """Trade type or operation not supported by V71OrderManager today.

    The mapping ``_TRADE_TYPE_TO_KIWOOM`` only ships LIMIT + MARKET. Adding
    BEST_LIMIT / PRIORITY_LIMIT / CONDITIONAL / AFTER_HOURS is a separate PR
    that must update both this map and ``V71KiwoomTradeType``.
    """


# ---------------------------------------------------------------------------
# Value objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class V71OrderRequest:
    """Submit-order payload. Validated at construction so callers fail fast."""

    stock_code: str
    quantity: int
    price: int | None              # None = MARKET
    direction: OrderDirection      # BUY | SELL
    trade_type: OrderTradeType
    position_id: UUID | None = None
    box_id: UUID | None = None
    tracked_stock_id: UUID | None = None
    exchange: str = "KRX"

    def __post_init__(self) -> None:
        if not self.stock_code:
            raise ValueError("stock_code is required")
        if self.quantity <= 0:
            raise ValueError("quantity must be > 0")
        if self.direction not in (OrderDirection.BUY, OrderDirection.SELL):
            raise ValueError(f"unsupported direction {self.direction!r}")
        if self.trade_type not in _TRADE_TYPE_TO_KIWOOM:
            raise V71OrderUnsupportedError(
                f"trade_type {self.trade_type!r} not supported by V71OrderManager "
                "(LIMIT / MARKET only); BEST_LIMIT / PRIORITY_LIMIT / CONDITIONAL / "
                "AFTER_HOURS are deferred."
            )
        if self.trade_type == OrderTradeType.LIMIT and (
            self.price is None or self.price <= 0
        ):
            raise ValueError("LIMIT order requires price > 0")
        if self.trade_type == OrderTradeType.MARKET and self.price is not None:
            # The DB CHECK constraint (migration 018 line 86~89) requires
            # MARKET orders to have NULL price; reject ambiguous input early.
            raise ValueError("MARKET order must have price=None")
        if self.exchange not in VALID_EXCHANGES:
            # Security M2: free-form exchange strings would silently fall
            # through to Kiwoom and surface as 8030/8031 hours later.
            raise ValueError(
                f"exchange must be one of {sorted(VALID_EXCHANGES)}, "
                f"got {self.exchange!r}"
            )


@dataclass(frozen=True)
class V71OrderSubmitResult:
    """Outcome of submit / cancel / modify. Mirrors the row state at the
    moment the call returned (state may change again via WS 00 events)."""

    order_id: UUID
    kiwoom_order_no: str
    state: OrderState
    direction: OrderDirection
    stock_code: str
    quantity: int
    submitted_at: datetime


@dataclass(frozen=True)
class V71OrderFillEvent:
    """WS 00 체결 이벤트의 정규화된 표현. on_position_fill 콜백에 전달.

    `cumulative_filled_quantity`는 본 fill 적용 *후* 누적량. avg_price_skill
    (PRD §7.4)을 호출할 때 V71PositionManager가 이 fill 단위(`fill_price`,
    `fill_quantity`)를 사용해 가중평균을 갱신한다.
    """

    order_id: UUID
    kiwoom_order_no: str
    direction: OrderDirection
    stock_code: str
    fill_price: int
    fill_quantity: int
    cumulative_filled_quantity: int
    state: OrderState
    occurred_at: datetime
    position_id: UUID | None = None


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ManualOrderCallback = Callable[[V71WebSocketMessage], Awaitable[None]]
PositionFillCallback = Callable[[V71OrderFillEvent], Awaitable[None]]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_int(value: Any, *, default: int = 0, field_name: str | None = None) -> int:
    """Parse Kiwoom WS string field to int. Empty / None / invalid → default.

    Logs a warning when a non-empty input fails to parse so corrupted
    fills are not silently dropped (Security L1). The raw value is
    truncated before logging to avoid blowing up the log line.
    """
    if value is None:
        return default
    if isinstance(value, int):
        return value
    text = str(value).strip()
    if not text:
        return default
    # Kiwoom sometimes prefixes signs like "+200"; int() handles both.
    try:
        return int(text)
    except ValueError:
        logger.warning(
            "v71_order_ws_int_coerce_failed",
            field=field_name,
            raw_len=len(text),
        )
        return default


def _coerce_decimal(value: Any) -> Decimal | None:
    """Parse Kiwoom WS string price to Decimal. Empty / None → None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (ValueError, ArithmeticError):
        return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class V71OrderManager:
    """Lifecycle owner for V7.1 orders -- submit → DB INSERT → WS reconcile.

    DI slots (architect P1.5):
      - ``kiwoom_client``: V71KiwoomClient (P5-Kiwoom-2). Wire-level transport
        for kt10000 / kt10001 / kt10002 / kt10003.
      - ``db_session_factory``: zero-arg callable returning an
        ``AsyncContextManager[AsyncSession]`` (typically
        ``DatabaseManager.session``). Each call to a public method creates +
        commits its own session; long-lived transactions are intentionally
        avoided.
      - ``clock`` (optional): UTC clock for ``submitted_at`` / fill timestamps;
        deterministic in tests.
      - ``on_manual_order`` (optional): invoked when a WS 00 event references
        a kiwoom_order_no NOT in v71_orders -- caller handles the manual /
        外部-tool order (PRD 02 §7 시나리오).
      - ``on_position_fill`` (optional): invoked for every fill event whose
        v71_orders row has ``position_id IS NOT NULL`` -- caller (V71Position-
        Manager) recomputes the weighted avg via ``avg_price_skill``.

    Concurrency:
      ``on_websocket_order_event`` uses an in-memory ``asyncio.Lock`` keyed by
      ``v71_orders.id`` so concurrent partial-fill events for the same order
      serialize their atomic UPDATE. Different orders proceed in parallel.
    """

    def __init__(
        self,
        *,
        kiwoom_client: V71KiwoomClient,
        db_session_factory: SessionFactory,
        clock: Callable[[], datetime] | None = None,
        on_manual_order: ManualOrderCallback | None = None,
        on_position_fill: PositionFillCallback | None = None,
    ) -> None:
        self._client = kiwoom_client
        self._session_factory = db_session_factory
        self._clock = clock or _utcnow
        self._on_manual_order = on_manual_order
        self._on_position_fill = on_position_fill

        # Per-order Lock cache for concurrent fill serialization.
        self._fill_locks: dict[UUID, asyncio.Lock] = {}
        self._fill_locks_guard = asyncio.Lock()

    def __repr__(self) -> str:
        # PII / lambda objects deliberately excluded -- only the wire client.
        return f"V71OrderManager(kiwoom_client={self._client!r})"

    # ---------------------- Public API: submit -------------------------

    async def submit_order(self, request: V71OrderRequest) -> V71OrderSubmitResult:
        """Place a buy / sell order via Kiwoom + INSERT v71_orders row.

        Sequence:
          1. Translate ``OrderTradeType`` → ``V71KiwoomTradeType`` (already
             validated in ``V71OrderRequest.__post_init__``).
          2. Call kt10000 (BUY) or kt10001 (SELL) via V71KiwoomClient.
          3. Extract ``ord_no`` from the response payload.
          4. INSERT v71_orders row with state=SUBMITTED + ``kiwoom_order_no``
             populated from the ord_no.

        Failure semantics:
          - ``V71KiwoomTransportError`` → ``V71OrderSubmissionFailed`` (DB
            unchanged).
          - ``V71KiwoomBusinessError`` → ``V71OrderSubmissionFailed`` (DB
            unchanged); ``return_code`` propagated for orchestrator branching.
          - ``IntegrityError`` (race with WS event INSERT'ing first) →
            ``V71OrderSubmissionFailed(reason="duplicate_kiwoom_order_no")``
            (DB unchanged); reconciler resolves.

        WARNING: This method does NOT auto-retry on transport failure. The
        caller MUST verify via ka10075 / kt00018 that the broker did not
        actually accept the order before resubmitting -- Kiwoom REST has no
        client_order_id, so blind retry can produce duplicate fills.
        """
        kiwoom_trade_type = _TRADE_TYPE_TO_KIWOOM[request.trade_type]

        try:
            if request.direction == OrderDirection.BUY:
                response = await self._client.place_buy_order(
                    stock_code=request.stock_code,
                    quantity=request.quantity,
                    price=request.price,
                    trade_type=kiwoom_trade_type,
                    dmst_stex_tp=request.exchange,
                )
            else:
                response = await self._client.place_sell_order(
                    stock_code=request.stock_code,
                    quantity=request.quantity,
                    price=request.price,
                    trade_type=kiwoom_trade_type,
                    dmst_stex_tp=request.exchange,
                )
        except V71KiwoomTransportError as exc:
            logger.warning(
                "v71_order_submit_transport_error",
                stock_code=request.stock_code,
                direction=request.direction.value,
                error=type(exc).__name__,
            )
            raise V71OrderSubmissionFailed(
                f"submit transport error ({request.direction.value} "
                f"{request.stock_code}): {type(exc).__name__}",
                cause=exc,
            ) from exc
        except V71KiwoomBusinessError as exc:
            mapped = map_business_error(exc)
            logger.warning(
                "v71_order_submit_business_error",
                stock_code=request.stock_code,
                direction=request.direction.value,
                api_id=exc.api_id,
                return_code=exc.return_code,
                severity=mapped.severity,
            )
            raise V71OrderSubmissionFailed(
                f"submit business error ({request.direction.value} "
                f"{request.stock_code}): code={exc.return_code}",
                api_id=exc.api_id,
                return_code=exc.return_code,
                return_msg=exc.return_msg,
                cause=exc,
            ) from exc

        kiwoom_order_no = self._extract_ord_no(response)

        order_id = uuid4()
        submitted_at = self._clock()
        try:
            async with self._session_factory() as session:
                row = V71Order(
                    id=order_id,
                    kiwoom_order_no=kiwoom_order_no,
                    kiwoom_orig_order_no=None,
                    position_id=request.position_id,
                    box_id=request.box_id,
                    tracked_stock_id=request.tracked_stock_id,
                    stock_code=request.stock_code,
                    direction=request.direction,
                    trade_type=request.trade_type,
                    quantity=request.quantity,
                    price=(Decimal(request.price) if request.price is not None else None),
                    exchange=request.exchange,
                    state=OrderState.SUBMITTED,
                    filled_quantity=0,
                    filled_avg_price=None,
                    retry_attempt=1,
                    submitted_at=submitted_at,
                    kiwoom_raw_request=self._build_raw_request_audit(
                        request=request,
                        kiwoom_trade_type=kiwoom_trade_type,
                    ),
                    kiwoom_raw_response=self._sanitize_response(response),
                )
                session.add(row)
                await session.flush()  # surface IntegrityError before commit
        except IntegrityError as exc:
            # Race: a WS event raced ahead and INSERT'd this ord_no first
            # (or a duplicate submit). Leave reconciler to resolve.
            logger.error(
                "v71_order_insert_duplicate_kiwoom_order_no",
                kiwoom_order_no=kiwoom_order_no,
                stock_code=request.stock_code,
            )
            raise V71OrderSubmissionFailed(
                f"duplicate kiwoom_order_no={kiwoom_order_no} "
                f"(stock={request.stock_code}); reconciler will resolve",
                cause=exc,
            ) from exc

        logger.info(
            "v71_order_submitted",
            kiwoom_order_no=kiwoom_order_no,
            stock_code=request.stock_code,
            direction=request.direction.value,
            trade_type=request.trade_type.value,
        )

        return V71OrderSubmitResult(
            order_id=order_id,
            kiwoom_order_no=kiwoom_order_no,
            state=OrderState.SUBMITTED,
            direction=request.direction,
            stock_code=request.stock_code,
            quantity=request.quantity,
            submitted_at=submitted_at,
        )

    # ---------------------- Public API: cancel / modify ----------------

    async def cancel_order(
        self,
        *,
        kiwoom_order_no: str,
        stock_code: str,
        cancel_qty: int = 0,
        exchange: str = "KRX",
    ) -> V71OrderSubmitResult:
        """kt10003 cancel. Inserts a *new* v71_orders row representing the
        cancel request (kiwoom_orig_order_no=원주문, direction inherited).

        ``cancel_qty=0`` means "cancel remainder" per Kiwoom spec
        (KIWOOM_API_ANALYSIS.md §5).
        """
        if not kiwoom_order_no:
            raise ValueError("kiwoom_order_no is required")
        if cancel_qty < 0:
            raise ValueError("cancel_qty must be >= 0 (0 means cancel remainder)")
        if exchange not in VALID_EXCHANGES:
            raise ValueError(
                f"exchange must be one of {sorted(VALID_EXCHANGES)}, "
                f"got {exchange!r}"
            )

        original = await self._fetch_order_by_kiwoom_no(kiwoom_order_no)
        if original is None:
            raise V71OrderNotFoundError(
                f"original order kiwoom_order_no={kiwoom_order_no} not found"
            )

        try:
            response = await self._client.cancel_order(
                orig_order_no=kiwoom_order_no,
                stock_code=stock_code,
                cancel_qty=cancel_qty,
                dmst_stex_tp=exchange,
            )
        except V71KiwoomTransportError as exc:
            logger.warning(
                "v71_order_cancel_transport_error",
                kiwoom_order_no=kiwoom_order_no,
                error=type(exc).__name__,
            )
            raise V71OrderSubmissionFailed(
                f"cancel transport error (kiwoom_order_no={kiwoom_order_no}): "
                f"{type(exc).__name__}",
                cause=exc,
            ) from exc
        except V71KiwoomBusinessError as exc:
            mapped = map_business_error(exc)
            logger.warning(
                "v71_order_cancel_business_error",
                kiwoom_order_no=kiwoom_order_no,
                api_id=exc.api_id,
                return_code=exc.return_code,
                severity=mapped.severity,
            )
            raise V71OrderSubmissionFailed(
                f"cancel business error (kiwoom_order_no={kiwoom_order_no}): "
                f"code={exc.return_code}",
                api_id=exc.api_id,
                return_code=exc.return_code,
                return_msg=exc.return_msg,
                cause=exc,
            ) from exc

        new_kiwoom_order_no = self._extract_ord_no(response)
        # Cancel order itself: its OWN row is "CANCELLED" because the cancel
        # request semantically completes immediately on broker acceptance.
        # The original-order's state is updated by a subsequent WS 00 event
        # ("취소" 한글 상태) inside on_websocket_order_event.
        return await self._insert_derivative_row(
            kiwoom_order_no=new_kiwoom_order_no,
            kiwoom_orig_order_no=kiwoom_order_no,
            original=original,
            quantity=cancel_qty if cancel_qty > 0 else original.quantity,
            price=None,
            trade_type=OrderTradeType.MARKET,  # cancel uses no price
            state=OrderState.CANCELLED,
            response=response,
        )

    async def modify_order(
        self,
        *,
        kiwoom_order_no: str,
        stock_code: str,
        new_quantity: int,
        new_price: int,
        exchange: str = "KRX",
    ) -> V71OrderSubmitResult:
        """kt10002 modify. Inserts a *new* v71_orders row representing the
        modified order (kiwoom_orig_order_no=원주문, direction inherited from
        original -- modify cannot change BUY↔SELL per Kiwoom spec).
        """
        if not kiwoom_order_no:
            raise ValueError("kiwoom_order_no is required")
        if new_quantity <= 0:
            raise ValueError("new_quantity must be > 0")
        if new_price <= 0:
            raise ValueError("new_price must be > 0")
        if exchange not in VALID_EXCHANGES:
            raise ValueError(
                f"exchange must be one of {sorted(VALID_EXCHANGES)}, "
                f"got {exchange!r}"
            )

        original = await self._fetch_order_by_kiwoom_no(kiwoom_order_no)
        if original is None:
            raise V71OrderNotFoundError(
                f"original order kiwoom_order_no={kiwoom_order_no} not found"
            )

        try:
            response = await self._client.modify_order(
                orig_order_no=kiwoom_order_no,
                stock_code=stock_code,
                modify_qty=new_quantity,
                modify_price=new_price,
                dmst_stex_tp=exchange,
            )
        except V71KiwoomTransportError as exc:
            logger.warning(
                "v71_order_modify_transport_error",
                kiwoom_order_no=kiwoom_order_no,
                error=type(exc).__name__,
            )
            raise V71OrderSubmissionFailed(
                f"modify transport error (kiwoom_order_no={kiwoom_order_no}): "
                f"{type(exc).__name__}",
                cause=exc,
            ) from exc
        except V71KiwoomBusinessError as exc:
            mapped = map_business_error(exc)
            logger.warning(
                "v71_order_modify_business_error",
                kiwoom_order_no=kiwoom_order_no,
                api_id=exc.api_id,
                return_code=exc.return_code,
                severity=mapped.severity,
            )
            raise V71OrderSubmissionFailed(
                f"modify business error (kiwoom_order_no={kiwoom_order_no}): "
                f"code={exc.return_code}",
                api_id=exc.api_id,
                return_code=exc.return_code,
                return_msg=exc.return_msg,
                cause=exc,
            ) from exc

        new_kiwoom_order_no = self._extract_ord_no(response)
        # Modify creates a fresh SUBMITTED order. Original row is updated to
        # CANCELLED (or partial) when WS 00 arrives with "확인" state.
        return await self._insert_derivative_row(
            kiwoom_order_no=new_kiwoom_order_no,
            kiwoom_orig_order_no=kiwoom_order_no,
            original=original,
            quantity=new_quantity,
            price=new_price,
            trade_type=OrderTradeType.LIMIT,  # modify always reprices to LIMIT
            state=OrderState.SUBMITTED,
            response=response,
        )

    # ---------------------- Public API: WS reconcile -------------------

    async def on_websocket_order_event(self, msg: V71WebSocketMessage) -> None:
        """Handle a Kiwoom WebSocket 00 (주문체결) event.

        Behaviour:
          1. Reject (silently) any non-ORDER_EXECUTION channel.
          2. Look up v71_orders by ``9203`` (ord_no). Missing → on_manual_order.
          3. Atomic UPDATE row state / filled_quantity (cumulative) /
             filled_avg_price (weighted average) under per-order asyncio.Lock.
          4. If position_id present and this fill changed filled quantity,
             emit a V71OrderFillEvent through on_position_fill (isolated --
             handler exceptions become logger.error, never re-raised).
        """
        if msg.channel is not V71KiwoomChannelType.ORDER_EXECUTION:
            return

        kiwoom_order_no = (msg.values.get(WS_FIELD["ORDER_NO"]) or "").strip()
        if not kiwoom_order_no:
            logger.warning(
                "v71_order_ws_event_missing_ord_no",
                received_at=msg.received_at.isoformat(),
            )
            return

        order_state_kr = (msg.values.get(WS_FIELD["ORDER_STATE"]) or "").strip()
        fill_qty = _coerce_int(
            msg.values.get(WS_FIELD["FILL_QUANTITY"]), field_name="fill_quantity"
        )
        fill_price = _coerce_int(
            msg.values.get(WS_FIELD["FILL_PRICE"]), field_name="fill_price"
        )
        remaining = _coerce_int(
            msg.values.get(WS_FIELD["REMAINING_QUANTITY"]),
            field_name="remaining_quantity",
        )
        reject_reason = (msg.values.get(WS_FIELD["REJECT_REASON"]) or "").strip() or None

        # Locate the order row first (no lock needed for SELECT).
        existing = await self._fetch_order_by_kiwoom_no(kiwoom_order_no)
        if existing is None:
            await self._notify_manual_order(msg, kiwoom_order_no=kiwoom_order_no)
            return

        order_id = existing.id
        is_terminal = False

        async with await self._lock_for(order_id):  # noqa: SIM117 (lock + session lifecycles are intentionally distinct)
            # Re-fetch under the lock so concurrent partial-fill events
            # serialise their reads + writes.
            async with self._session_factory() as session:
                row = await session.get(V71Order, order_id)
                if row is None:
                    # Vanished between SELECT and re-read; treat as manual.
                    await self._notify_manual_order(
                        msg, kiwoom_order_no=kiwoom_order_no
                    )
                    return

                fill_event: V71OrderFillEvent | None = None

                if order_state_kr == KIWOOM_STATE_FILLED and fill_qty > 0:
                    new_filled = row.filled_quantity + fill_qty
                    new_avg = self._weighted_average(
                        prior_filled=row.filled_quantity,
                        prior_avg=row.filled_avg_price,
                        new_qty=fill_qty,
                        new_price=fill_price,
                    )
                    new_state = (
                        OrderState.FILLED if remaining == 0 else OrderState.PARTIAL
                    )
                    row.filled_quantity = new_filled
                    row.filled_avg_price = new_avg
                    row.state = new_state
                    if new_state == OrderState.FILLED:
                        row.filled_at = self._clock()
                    fill_event = V71OrderFillEvent(
                        order_id=row.id,
                        kiwoom_order_no=row.kiwoom_order_no,
                        direction=row.direction,
                        stock_code=row.stock_code,
                        fill_price=fill_price,
                        fill_quantity=fill_qty,
                        cumulative_filled_quantity=new_filled,
                        state=new_state,
                        occurred_at=self._clock(),
                        position_id=row.position_id,
                    )
                elif order_state_kr == KIWOOM_STATE_CANCELLED:
                    row.state = OrderState.CANCELLED
                    row.cancelled_at = self._clock()
                    if reject_reason:
                        # Security L3: VARCHAR(100) column truncates silently;
                        # warn so post-mortem readers know the audit string
                        # may be incomplete (full reason still in
                        # kiwoom_raw_response when WS provides it).
                        if len(reject_reason) > 100:
                            logger.info(
                                "v71_order_cancel_reason_truncated",
                                kiwoom_order_no=kiwoom_order_no,
                                original_len=len(reject_reason),
                            )
                        row.cancel_reason = reject_reason[:100]
                elif order_state_kr == KIWOOM_STATE_REJECTED:
                    row.state = OrderState.REJECTED
                    row.rejected_at = self._clock()
                    row.reject_reason = reject_reason
                elif order_state_kr == KIWOOM_STATE_CONFIRMED:
                    # 확인 = broker-side ack of a modify / cancel that was
                    # already submitted via cancel_order / modify_order.
                    # Two cases:
                    #   * row.state == SUBMITTED (no fills yet) -> the
                    #     original order is fully replaced -> CANCELLED.
                    #   * row.state == PARTIAL (some fills happened before
                    #     the modify/cancel landed) -> keep PARTIAL but
                    #     stamp ``cancelled_at`` to mark the moment the
                    #     remainder stopped being fillable on this row.
                    #     The replacement order's life continues on the
                    #     derivative row (kiwoom_orig_order_no -> this row).
                    row.cancelled_at = self._clock()
                    if row.state == OrderState.SUBMITTED:
                        row.state = OrderState.CANCELLED
                elif order_state_kr == KIWOOM_STATE_ACCEPTED:
                    # 접수 -- v71_orders already records SUBMITTED. Nothing to do.
                    pass
                else:
                    logger.warning(
                        "v71_order_ws_unknown_state",
                        kiwoom_order_no=kiwoom_order_no,
                        state=order_state_kr,
                    )

                if row.state in (
                    OrderState.FILLED,
                    OrderState.CANCELLED,
                    OrderState.REJECTED,
                ):
                    is_terminal = True
                # session.commit() handled by the context manager.

        # Security H1: drop the per-order lock from the cache once the order
        # has reached a terminal state. Doing so AFTER releasing the lock
        # avoids any chance of deadlock with a concurrent ``_lock_for`` call
        # that's still waiting on this lock.
        if is_terminal:
            async with self._fill_locks_guard:
                self._fill_locks.pop(order_id, None)

        if fill_event is not None and fill_event.position_id is not None:
            await self._notify_position_fill(fill_event)

    # ---------------------- Internals: order helpers -------------------

    async def _fetch_order_by_kiwoom_no(
        self, kiwoom_order_no: str
    ) -> V71Order | None:
        async with self._session_factory() as session:
            stmt = select(V71Order).where(
                V71Order.kiwoom_order_no == kiwoom_order_no
            )
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def _insert_derivative_row(
        self,
        *,
        kiwoom_order_no: str,
        kiwoom_orig_order_no: str,
        original: V71Order,
        quantity: int,
        price: int | None,
        trade_type: OrderTradeType,
        state: OrderState,
        response: V71KiwoomResponse,
    ) -> V71OrderSubmitResult:
        """Insert a row representing a derivative (cancel / modify) order.

        Direction is inherited from the original; modify cannot flip BUY↔SELL
        per Kiwoom spec (KIWOOM_API_ANALYSIS.md §5 kt10002 body has no
        direction field).
        """
        order_id = uuid4()
        submitted_at = self._clock()
        try:
            async with self._session_factory() as session:
                row = V71Order(
                    id=order_id,
                    kiwoom_order_no=kiwoom_order_no,
                    kiwoom_orig_order_no=kiwoom_orig_order_no,
                    position_id=original.position_id,
                    box_id=original.box_id,
                    tracked_stock_id=original.tracked_stock_id,
                    stock_code=original.stock_code,
                    direction=original.direction,  # inherited
                    trade_type=trade_type,
                    quantity=quantity,
                    price=(Decimal(price) if price is not None else None),
                    exchange=original.exchange,
                    state=state,
                    filled_quantity=0,
                    filled_avg_price=None,
                    retry_attempt=1,
                    submitted_at=submitted_at,
                    cancelled_at=submitted_at if state == OrderState.CANCELLED else None,
                    kiwoom_raw_request=None,
                    kiwoom_raw_response=self._sanitize_response(response),
                )
                session.add(row)
                await session.flush()
        except IntegrityError as exc:
            logger.error(
                "v71_order_derivative_insert_duplicate",
                kiwoom_order_no=kiwoom_order_no,
                kiwoom_orig_order_no=kiwoom_orig_order_no,
            )
            raise V71OrderSubmissionFailed(
                f"duplicate kiwoom_order_no={kiwoom_order_no} on derivative",
                cause=exc,
            ) from exc

        logger.info(
            "v71_order_derivative_inserted",
            kiwoom_order_no=kiwoom_order_no,
            kiwoom_orig_order_no=kiwoom_orig_order_no,
            state=state.value,
        )

        return V71OrderSubmitResult(
            order_id=order_id,
            kiwoom_order_no=kiwoom_order_no,
            state=state,
            direction=original.direction,
            stock_code=original.stock_code,
            quantity=quantity,
            submitted_at=submitted_at,
        )

    # ---------------------- Internals: WS helpers ----------------------

    async def _lock_for(self, order_id: UUID) -> asyncio.Lock:
        """Return the per-order Lock, creating one if necessary."""
        async with self._fill_locks_guard:
            lock = self._fill_locks.get(order_id)
            if lock is None:
                lock = asyncio.Lock()
                self._fill_locks[order_id] = lock
            return lock

    async def _notify_manual_order(
        self,
        msg: V71WebSocketMessage,
        *,
        kiwoom_order_no: str,
    ) -> None:
        """Invoke ``on_manual_order`` -- isolated so a buggy handler cannot
        starve the WS event loop."""
        if self._on_manual_order is None:
            logger.info(
                "v71_order_ws_unknown_no_handler",
                kiwoom_order_no=kiwoom_order_no,
            )
            return
        try:
            await self._on_manual_order(msg)
        except Exception as exc:  # noqa: BLE001 - handler isolation
            # Security M1: avoid logger.exception (frame locals may carry
            # quantities / prices); log the type only.
            logger.error(
                "v71_order_manual_callback_error",
                kiwoom_order_no=kiwoom_order_no,
                error=type(exc).__name__,
            )

    async def _notify_position_fill(self, event: V71OrderFillEvent) -> None:
        if self._on_position_fill is None:
            return
        try:
            await self._on_position_fill(event)
        except Exception as exc:  # noqa: BLE001 - handler isolation
            logger.error(
                "v71_order_position_fill_callback_error",
                kiwoom_order_no=event.kiwoom_order_no,
                position_id=str(event.position_id) if event.position_id else None,
                error=type(exc).__name__,
            )

    @staticmethod
    def _weighted_average(
        *,
        prior_filled: int,
        prior_avg: Decimal | None,
        new_qty: int,
        new_price: int,
    ) -> Decimal:
        """Cumulative weighted-average fill price.

        ``prior_avg`` is None when this is the first fill; the result is
        simply ``new_price`` rendered as Decimal. The DB column is
        ``NUMERIC(12, 2)``.
        """
        if prior_filled <= 0 or prior_avg is None:
            return Decimal(new_price)
        total_qty = prior_filled + new_qty
        if total_qty <= 0:
            return Decimal(new_price)
        numerator = (prior_avg * Decimal(prior_filled)) + (
            Decimal(new_price) * Decimal(new_qty)
        )
        return numerator / Decimal(total_qty)

    @staticmethod
    def _extract_ord_no(response: V71KiwoomResponse) -> str:
        """Pull ord_no out of a Kiwoom order response (kt10000~10003)."""
        data = response.data or {}
        ord_no = data.get("ord_no") or data.get("ord_no_b") or data.get("base_orig_ord_no")
        if not ord_no:
            raise V71OrderSubmissionFailed(
                f"Kiwoom response missing ord_no (api_id={response.api_id})"
            )
        return str(ord_no)

    @staticmethod
    def _build_raw_request_audit(
        *,
        request: V71OrderRequest,
        kiwoom_trade_type: V71KiwoomTradeType,
    ) -> dict[str, Any]:
        """Audit copy of the outbound payload (no token / API key included --
        kiwoom_client owns the auth header out-of-band)."""
        return {
            "stock_code": request.stock_code,
            "quantity": request.quantity,
            "price": request.price,
            "direction": request.direction.value,
            "trade_type": request.trade_type.value,
            "kiwoom_trade_type": kiwoom_trade_type.value,
            "exchange": request.exchange,
            "position_id": str(request.position_id) if request.position_id else None,
            "box_id": str(request.box_id) if request.box_id else None,
            "tracked_stock_id": (
                str(request.tracked_stock_id) if request.tracked_stock_id else None
            ),
        }

    @staticmethod
    def _sanitize_response(response: V71KiwoomResponse) -> dict[str, Any]:
        """Audit copy of the inbound payload.

        ``data`` already excludes the ``return_code`` / ``return_msg``
        envelope (see V71KiwoomClient.request); this helper additionally:

        * Deep-copies the data dict so a caller mutating ``response.data``
          after submit cannot retroactively change a persisted audit row
          (Security M1.1).
        * Redacts any forbidden key (token / app_secret / Authorization /
          ...) at the top level. Order responses (kt10000~10003) never
          carry these today but the helper is generic enough that future
          reuse with kt00018 / au10001 must not leak credentials by
          accident (Security M1.2 — defence in depth).
        """
        raw_data = response.data or {}
        try:
            data_copy = copy.deepcopy(raw_data)
        except Exception:  # noqa: BLE001 - audit must never crash the caller
            # Final fallback: shallow copy with redacted forbidden keys.
            # Failing the entire submit because the audit clone itself
            # raised would violate the "Always Run" rule (헌법 §4).
            data_copy = dict(raw_data)
        if isinstance(data_copy, dict):
            for key in list(data_copy.keys()):
                if key in _FORBIDDEN_RESPONSE_KEYS:
                    data_copy[key] = _REDACTED
        return {
            "api_id": response.api_id,
            "return_code": response.return_code,
            "return_msg": response.return_msg,
            "duration_ms": response.duration_ms,
            "data": data_copy,
        }


__all__ = [
    "KIWOOM_STATE_ACCEPTED",
    "KIWOOM_STATE_CANCELLED",
    "KIWOOM_STATE_CONFIRMED",
    "KIWOOM_STATE_FILLED",
    "KIWOOM_STATE_REJECTED",
    "ManualOrderCallback",
    "PositionFillCallback",
    "SessionFactory",
    "V71OrderError",
    "V71OrderFillEvent",
    "V71OrderManager",
    "V71OrderNotFoundError",
    "V71OrderRequest",
    "V71OrderSubmissionFailed",
    "V71OrderSubmitResult",
    "V71OrderUnsupportedError",
    "WS_FIELD",
]
