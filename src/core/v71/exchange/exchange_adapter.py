"""V71KiwoomExchangeAdapter -- ExchangeAdapter Protocol implementation.

Spec sources:
  - 07_SKILLS_SPEC.md §1 (kiwoom_api_skill -- ExchangeAdapter Protocol +
    V71Orderbook / V71OrderResult / V71OrderStatus / V71OrderSide /
    V71OrderType dataclasses)
  - 02_TRADING_RULES.md §4 (매수 retry policy lives in the executor, not
    here -- the adapter is a thin transport bridge)
  - 02_TRADING_RULES.md §6 (평단가 -- send_order delegates to
    V71OrderManager so the v71_orders INSERT + WS reconcile paths stay
    intact)
  - 02_TRADING_RULES.md §7 (정합성 -- bypassing V71OrderManager would
    blind the reconciler; adapter must NOT use the raw V71KiwoomClient
    place_*_order seam)
  - 06_AGENTS_SPEC.md §1 (V71 Architect -- options A/B/C analysis;
    architect chose option B = V71OrderManager 통합)
  - KIWOOM_API_ANALYSIS.md §2 + §보조 (ka10001 주식기본정보 / ka10004
    주식호가요청 wire-level field assumptions)

Design summary:
  * Adapter holds two collaborators -- ``V71KiwoomClient`` for read-only
    market data (호가 / 현재가 via ka10004 / ka10001) and
    ``V71OrderManager`` for order lifecycle (submit / cancel / status).
  * Same-instance invariant: the order_manager's internal client must
    be the same V71KiwoomClient handed in as ``kiwoom_client``. Otherwise
    we'd run two token caches + two rate limiters and silently overshoot
    the 4.5/sec broker limit.
  * send_order: builds a V71OrderRequest + delegates to
    V71OrderManager.submit_order. The DB INSERT + WS 00 매칭 + on_position_fill
    callback all happen inside V71OrderManager -- the adapter only
    translates the result back into the executor-facing V71OrderResult.
  * cancel_order: V71OrderManager.cancel_order(kiwoom_order_no=...).
    The new derivative row + WS-driven state of the original row stay
    consistent.
  * get_order_status: DB-first via V71OrderManager.get_order_state, with
    a Kiwoom ka10075 fallback when the order isn't yet (or no longer)
    in v71_orders -- e.g. external orders the adapter never saw submit.

Field-assumption note (P7 paper smoke -- TODO comments inline):
  ka10004 / ka10001 response field names are the architect-approved best
  guesses based on KIWOOM_API_ANALYSIS.md and Kiwoom's general naming
  pattern. Verifying / correcting these against the live broker happens
  in the Phase 7 paper-smoke unit -- the assumptions live in
  ``_FIELDS_KA10004`` / ``_FIELDS_KA10001`` so a single edit per file
  flows through.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from src.core.v71.exchange.kiwoom_client import V71KiwoomClient
from src.core.v71.exchange.order_manager import (
    V71OrderError,
    V71OrderManager,
    V71OrderRequest,
    V71OrderSubmissionFailed,
    V71OrderUnsupportedError,
)
from src.core.v71.skills.kiwoom_api_skill import (
    ExchangeAdapter,
    KiwoomAPIError,
    KiwoomAuthError,
    KiwoomRateLimitError,
    KiwoomTimeoutError,
    OrderRejectedError,
    V71Orderbook,
    V71OrderResult,
    V71OrderSide,
    V71OrderStatus,
    V71OrderType,
)
from src.database.models_v71 import (
    OrderDirection,
    OrderState,
    OrderTradeType,
    V71Order,
)

# ---------------------------------------------------------------------------
# Wire-field assumptions (P7-paper-smoke verifies)
# ---------------------------------------------------------------------------
#
# TODO(P7-paper-smoke): confirm these field names against the live ka10001
# / ka10004 responses and update here if Kiwoom uses different keys.

_FIELDS_KA10004: Mapping[str, str] = MappingProxyType({
    # Best-bid (매수 1호가) + best-ask (매도 1호가). Kiwoom's typical
    # field naming pattern; confirm in P7 smoke.
    "BID_1": "buy_fpr_bid",
    "ASK_1": "sel_fpr_bid",
    # Last traded price -- ka10004 may or may not include this; the
    # adapter falls back to ka10001 if missing.
    "LAST_PRICE": "cur_prc",
})

_FIELDS_KA10001: Mapping[str, str] = MappingProxyType({
    "CURRENT_PRICE": "cur_prc",
    "STOCK_NAME": "stk_nm",
})


# ---------------------------------------------------------------------------
# Direction / type mapping (V7.1 enum ↔ executor surface enum)
# ---------------------------------------------------------------------------


_SIDE_TO_DIRECTION: Final[Mapping[V71OrderSide, OrderDirection]] = (
    MappingProxyType({
        V71OrderSide.BUY: OrderDirection.BUY,
        V71OrderSide.SELL: OrderDirection.SELL,
    })
)

_DIRECTION_TO_SIDE: Final[Mapping[OrderDirection, V71OrderSide]] = (
    MappingProxyType({
        OrderDirection.BUY: V71OrderSide.BUY,
        OrderDirection.SELL: V71OrderSide.SELL,
    })
)

_TYPE_TO_TRADE: Final[Mapping[V71OrderType, OrderTradeType]] = (
    MappingProxyType({
        V71OrderType.LIMIT: OrderTradeType.LIMIT,
        V71OrderType.MARKET: OrderTradeType.MARKET,
    })
)


def _coerce_int(raw: Any) -> int | None:
    """Parse a Kiwoom numeric field. Returns None if missing / unparseable
    so the caller can decide whether absence is fatal."""
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    text = str(raw).strip()
    if not text:
        return None
    try:
        # Kiwoom often prefixes signed values like "+1500" / "-200".
        return int(text)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class V71KiwoomExchangeAdapter(ExchangeAdapter):
    """Concrete ExchangeAdapter backed by V71KiwoomClient + V71OrderManager.

    Architect-approved (Q1=B): orders flow through V71OrderManager so the
    V7.1 trading rules (§4 retry, §6 평단가 reset, §7 정합성) stay intact.
    Read-only market data flows through V71KiwoomClient directly.
    """

    def __init__(
        self,
        *,
        kiwoom_client: V71KiwoomClient,
        order_manager: V71OrderManager,
    ) -> None:
        # Same-instance invariant (architect P1.5): the order_manager
        # already owns a V71KiwoomClient (token + rate-limiter); the
        # adapter must reuse the same instance so we don't double the
        # 4.5/sec broker quota.
        if getattr(order_manager, "_client", None) is not kiwoom_client:
            raise ValueError(
                "V71KiwoomExchangeAdapter: kiwoom_client must be the same "
                "instance V71OrderManager uses (token / rate-limiter "
                "consistency); call site bug."
            )
        self._client = kiwoom_client
        self._order_manager = order_manager

    def __repr__(self) -> str:
        return (
            f"V71KiwoomExchangeAdapter(kiwoom_client={self._client!r}, "
            f"order_manager={self._order_manager!r})"
        )

    # ---------------------- Read-only market data ----------------------

    async def get_orderbook(self, stock_code: str) -> V71Orderbook:
        """ka10004 호가 → V71Orderbook(bid_1, ask_1, last_price).

        Raises ``KiwoomAPIError`` (or a subclass) when the broker call
        fails or the response is missing required fields.
        """
        if not stock_code:
            raise KiwoomAPIError("get_orderbook: stock_code is required")

        response = await self._call(
            self._client.get_orderbook(stock_code=stock_code),
            context_msg=f"get_orderbook({stock_code})",
        )

        data = response.data or {}
        bid_1 = _coerce_int(data.get(_FIELDS_KA10004["BID_1"]))
        ask_1 = _coerce_int(data.get(_FIELDS_KA10004["ASK_1"]))
        last = _coerce_int(data.get(_FIELDS_KA10004["LAST_PRICE"]))

        if bid_1 is None or ask_1 is None:
            raise KiwoomAPIError(
                f"get_orderbook({stock_code}): missing bid_1/ask_1 in "
                f"ka10004 response (keys present: {sorted(data.keys())[:10]})"
            )

        if last is None:
            # ka10004 may omit cur_prc; fall back to ka10001 so the
            # executor still gets a valid last_price.
            stock_response = await self._call(
                self._client.get_stock_info(stock_code=stock_code),
                context_msg=f"get_orderbook->stock_info({stock_code})",
            )
            stock_data = stock_response.data or {}
            last = _coerce_int(
                stock_data.get(_FIELDS_KA10001["CURRENT_PRICE"]),
            )
            if last is None:
                raise KiwoomAPIError(
                    f"get_orderbook({stock_code}): no last_price available "
                    "from ka10004 or ka10001 fallback"
                )

        return V71Orderbook(
            stock_code=stock_code, bid_1=bid_1, ask_1=ask_1, last_price=last,
        )

    async def get_current_price(self, stock_code: str) -> int:
        """ka10001 주식기본정보 → cur_prc (int)."""
        if not stock_code:
            raise KiwoomAPIError("get_current_price: stock_code is required")
        response = await self._call(
            self._client.get_stock_info(stock_code=stock_code),
            context_msg=f"get_current_price({stock_code})",
        )
        data = response.data or {}
        price = _coerce_int(data.get(_FIELDS_KA10001["CURRENT_PRICE"]))
        if price is None:
            raise KiwoomAPIError(
                f"get_current_price({stock_code}): missing cur_prc in "
                "ka10001 response"
            )
        return price

    # ---------------------- Order lifecycle ----------------------------

    async def send_order(
        self,
        *,
        stock_code: str,
        side: V71OrderSide,
        quantity: int,
        price: int,
        order_type: V71OrderType,
    ) -> V71OrderResult:
        """Submit via V71OrderManager so DB INSERT + WS reconcile + the
        on_position_fill callback path all stay intact (architect Q1=B).
        """
        direction = _SIDE_TO_DIRECTION.get(side)
        if direction is None:
            raise KiwoomAPIError(f"send_order: unsupported side {side!r}")
        trade_type = _TYPE_TO_TRADE.get(order_type)
        if trade_type is None:
            raise KiwoomAPIError(
                f"send_order: unsupported order_type {order_type!r}"
            )

        try:
            request = V71OrderRequest(
                stock_code=stock_code,
                quantity=quantity,
                price=price if trade_type == OrderTradeType.LIMIT else None,
                direction=direction,
                trade_type=trade_type,
            )
        except V71OrderUnsupportedError as exc:
            raise KiwoomAPIError(
                f"send_order({stock_code}): unsupported -- {exc}",
            ) from exc
        except ValueError as exc:
            raise KiwoomAPIError(
                f"send_order({stock_code}): invalid input -- {exc}",
            ) from exc

        try:
            submit = await self._order_manager.submit_order(request)
        except V71OrderSubmissionFailed as exc:
            # Architect Q8: lower-layer typed errors must surface as the
            # KiwoomAPIError-family the executor already handles. We
            # preserve return_code so a caller can still policy-branch.
            raise self._wrap_order_failure(
                exc, context_msg=f"send_order({stock_code})",
            ) from exc
        except V71OrderError as exc:
            raise OrderRejectedError(
                f"send_order({stock_code}): order error -- {exc}",
            ) from exc

        return V71OrderResult(
            order_id=submit.kiwoom_order_no,
            stock_code=submit.stock_code,
            side=_DIRECTION_TO_SIDE[submit.direction],
            order_type=order_type,
            requested_quantity=submit.quantity,
            requested_price=price,
            filled_quantity=0,
            avg_fill_price=0,
        )

    async def cancel_order(
        self, *, order_id: str, stock_code: str,
    ) -> V71OrderResult:
        """V71OrderManager.cancel_order so the original-order audit
        chain (kiwoom_orig_order_no) stays consistent."""
        if not order_id:
            raise KiwoomAPIError("cancel_order: order_id is required")
        if not stock_code:
            raise KiwoomAPIError("cancel_order: stock_code is required")

        try:
            submit = await self._order_manager.cancel_order(
                kiwoom_order_no=order_id, stock_code=stock_code,
            )
        except V71OrderSubmissionFailed as exc:
            raise self._wrap_order_failure(
                exc, context_msg=f"cancel_order({order_id})",
            ) from exc
        except V71OrderError as exc:
            raise OrderRejectedError(
                f"cancel_order({order_id}): order error -- {exc}",
            ) from exc

        return V71OrderResult(
            order_id=submit.kiwoom_order_no,
            stock_code=submit.stock_code,
            side=_DIRECTION_TO_SIDE[submit.direction],
            order_type=V71OrderType.MARKET,  # cancel rows have no price
            requested_quantity=submit.quantity,
            requested_price=0,
            filled_quantity=0,
            avg_fill_price=0,
        )

    async def get_order_status(self, order_id: str) -> V71OrderStatus:
        """DB-first via V71OrderManager.get_order_state; ka10075 fallback
        for orders the adapter never saw submit (external tooling)."""
        if not order_id:
            raise KiwoomAPIError("get_order_status: order_id is required")

        row = await self._order_manager.get_order_state(order_id)
        if row is not None:
            return self._row_to_status(row)

        # DB miss -- check broker pending list. Anything else (filled /
        # cancelled in broker but absent from DB) needs reconciler attention,
        # but the executor only asks "is_open" / "is_cancelled" -- broker
        # pending presence is an honest answer.
        response = await self._call(
            self._client.get_pending_orders(),
            context_msg=f"get_order_status({order_id})",
        )
        for item in (response.data or {}).get("oso") or []:
            if not isinstance(item, dict):
                continue
            if str(item.get("ord_no", "")).strip() != order_id:
                continue
            return V71OrderStatus(
                order_id=order_id,
                stock_code=str(item.get("stk_cd", "")).strip(),
                requested_quantity=_coerce_int(item.get("ord_qty")) or 0,
                filled_quantity=_coerce_int(item.get("cntr_qty")) or 0,
                avg_fill_price=_coerce_int(item.get("cntr_pric")) or 0,
                is_open=True,
                is_cancelled=False,
            )

        # Not in DB and not in broker pending. From the executor's
        # perspective the order is no longer fillable -- treat as
        # cancelled so the caller can move on.
        return V71OrderStatus(
            order_id=order_id,
            stock_code="",
            requested_quantity=0,
            filled_quantity=0,
            avg_fill_price=0,
            is_open=False,
            is_cancelled=True,
        )

    # ---------------------- Helpers ------------------------------------

    @staticmethod
    def _row_to_status(row: V71Order) -> V71OrderStatus:
        return V71OrderStatus(
            order_id=row.kiwoom_order_no,
            stock_code=row.stock_code,
            requested_quantity=row.quantity,
            filled_quantity=row.filled_quantity,
            avg_fill_price=int(row.filled_avg_price or 0),
            is_open=row.state in (OrderState.SUBMITTED, OrderState.PARTIAL),
            is_cancelled=row.state == OrderState.CANCELLED,
        )

    @staticmethod
    def _wrap_order_failure(
        exc: V71OrderSubmissionFailed, *, context_msg: str,
    ) -> KiwoomAPIError:
        """Map a V71OrderSubmissionFailed into the KiwoomAPIError family
        the executor already branches on. ``return_code`` (if set on the
        wrapped error) drives rate-limit / auth identification."""
        return_code = getattr(exc, "return_code", None)
        message = f"{context_msg}: {exc}"
        if return_code == 1700:
            return KiwoomRateLimitError(message)
        if return_code == 8005:
            return KiwoomAuthError(message)
        # Transport-level failures fold into KiwoomTimeoutError per the
        # contract used by skills/kiwoom_api_skill.
        if return_code is None:
            return KiwoomTimeoutError(message)
        return OrderRejectedError(message)

    async def _call(
        self, awaitable: Any, *, context_msg: str,
    ):
        """Invoke a V71KiwoomClient call and translate its typed errors
        into the KiwoomAPIError family. Local import keeps the module's
        top-level exception list tied to the adapter surface."""
        from src.core.v71.exchange.error_mapper import (
            V71KiwoomRateLimitError,
            V71KiwoomTokenInvalidError,
            map_business_error,
        )
        from src.core.v71.exchange.kiwoom_client import (
            V71KiwoomBusinessError,
            V71KiwoomTransportError,
        )

        try:
            return await awaitable
        except V71KiwoomTransportError as exc:
            raise KiwoomTimeoutError(
                f"{context_msg}: {type(exc).__name__}: {exc}",
            ) from exc
        except V71KiwoomBusinessError as exc:
            mapped = map_business_error(exc)
            message = (
                f"{context_msg}: code={exc.return_code} "
                f"({exc.api_id or 'unknown_api'}) -- {exc.return_msg}"
            )
            if isinstance(mapped, V71KiwoomRateLimitError):
                raise KiwoomRateLimitError(message) from exc
            if isinstance(mapped, V71KiwoomTokenInvalidError):
                raise KiwoomAuthError(message) from exc
            raise KiwoomAPIError(message) from exc


__all__ = [
    "V71KiwoomExchangeAdapter",
]
