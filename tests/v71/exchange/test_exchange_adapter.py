"""Unit tests for ``src/core/v71/exchange/exchange_adapter.py``.

Spec sources:
  - 06_AGENTS_SPEC.md §5 Test Strategy verification (architect Q1=B)
  - 02_TRADING_RULES.md §6 (V71OrderManager 위임으로 평단가 / WS 매칭 보존)
  - 02_TRADING_RULES.md §7 (정합성 — adapter가 V71OrderManager 우회 X)
  - 12_SECURITY.md §6 (PII / token 미노출)
"""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from src.core.v71.exchange.exchange_adapter import (
    V71KiwoomExchangeAdapter,
    _coerce_int,
)
from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomResponse,
    V71KiwoomTransportError,
)
from src.core.v71.exchange.order_manager import (
    V71OrderManager,
    V71OrderSubmissionFailed,
    V71OrderSubmitResult,
)
from src.core.v71.skills.kiwoom_api_skill import (
    KiwoomAPIError,
    KiwoomAuthError,
    KiwoomRateLimitError,
    KiwoomTimeoutError,
    V71OrderSide,
    V71OrderType,
)
from src.database.models_v71 import (
    OrderDirection,
    OrderState,
    OrderTradeType,
    V71Order,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_response(
    *,
    api_id: str = "ka10004",
    data: dict | None = None,
    return_code: int = 0,
) -> V71KiwoomResponse:
    return V71KiwoomResponse(
        success=True,
        api_id=api_id,
        data=data or {},
        return_code=return_code,
        return_msg="OK",
        cont_yn="N",
        next_key="",
        duration_ms=10,
    )


@pytest.fixture
def kiwoom_client_mock():
    return AsyncMock(spec=V71KiwoomClient)


@pytest.fixture
def order_manager_mock(kiwoom_client_mock):
    """AsyncMock V71OrderManager with the same-instance invariant
    satisfied (its ``_client`` attribute points at the same client mock)."""
    om = AsyncMock(spec=V71OrderManager)
    om._client = kiwoom_client_mock
    return om


@pytest.fixture
def adapter(kiwoom_client_mock, order_manager_mock):
    return V71KiwoomExchangeAdapter(
        kiwoom_client=kiwoom_client_mock,
        order_manager=order_manager_mock,
    )


def _make_submit_result(
    *,
    kiwoom_order_no: str = "ORDER12345",
    direction: OrderDirection = OrderDirection.BUY,
    stock_code: str = "005930",
    quantity: int = 10,
    state: OrderState = OrderState.SUBMITTED,
) -> V71OrderSubmitResult:
    return V71OrderSubmitResult(
        order_id=uuid4(),
        kiwoom_order_no=kiwoom_order_no,
        state=state,
        direction=direction,
        stock_code=stock_code,
        quantity=quantity,
        submitted_at=datetime(2026, 4, 28, 9, 30, tzinfo=timezone.utc),
    )


def _make_v71_order(
    *,
    kiwoom_order_no: str = "ORDER12345",
    stock_code: str = "005930",
    direction: OrderDirection = OrderDirection.BUY,
    state: OrderState = OrderState.SUBMITTED,
    quantity: int = 10,
    filled_quantity: int = 0,
    filled_avg_price: int | None = None,
) -> V71Order:
    from decimal import Decimal
    return V71Order(
        id=uuid4(),
        kiwoom_order_no=kiwoom_order_no,
        stock_code=stock_code,
        direction=direction,
        trade_type=OrderTradeType.LIMIT,
        quantity=quantity,
        price=Decimal(70000),
        state=state,
        filled_quantity=filled_quantity,
        filled_avg_price=Decimal(filled_avg_price) if filled_avg_price else None,
    )


# ---------------------------------------------------------------------------
# Group A: same-instance invariant (2 cases)
# ---------------------------------------------------------------------------


class TestSameInstanceInvariant:
    def test_passes_when_order_manager_uses_same_client(
        self, kiwoom_client_mock, order_manager_mock,
    ):
        adapter = V71KiwoomExchangeAdapter(
            kiwoom_client=kiwoom_client_mock,
            order_manager=order_manager_mock,
        )
        assert adapter is not None

    def test_raises_when_order_manager_uses_different_client(
        self, kiwoom_client_mock,
    ):
        other_client = AsyncMock(spec=V71KiwoomClient)
        bad_om = AsyncMock(spec=V71OrderManager)
        bad_om._client = other_client  # different instance!

        with pytest.raises(ValueError, match="same instance"):
            V71KiwoomExchangeAdapter(
                kiwoom_client=kiwoom_client_mock,
                order_manager=bad_om,
            )


# ---------------------------------------------------------------------------
# Group B: get_orderbook (5 cases)
# ---------------------------------------------------------------------------


class TestGetOrderbook:
    async def test_returns_orderbook_from_ka10004(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_orderbook.return_value = _make_response(
            data={
                "buy_fpr_bid": "73000",
                "sel_fpr_bid": "73100",
                "cur_prc": "73050",
            },
        )
        result = await adapter.get_orderbook("005930")

        assert result.stock_code == "005930"
        assert result.bid_1 == 73000
        assert result.ask_1 == 73100
        assert result.last_price == 73050

    async def test_falls_back_to_ka10001_when_cur_prc_missing(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_orderbook.return_value = _make_response(
            data={"buy_fpr_bid": "73000", "sel_fpr_bid": "73100"},
        )
        kiwoom_client_mock.get_stock_info.return_value = _make_response(
            api_id="ka10001",
            data={"cur_prc": "73050"},
        )

        result = await adapter.get_orderbook("005930")

        assert result.last_price == 73050
        kiwoom_client_mock.get_stock_info.assert_awaited_once()

    async def test_raises_when_bid_missing(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_orderbook.return_value = _make_response(
            data={"sel_fpr_bid": "73100"},
        )
        with pytest.raises(KiwoomAPIError, match="missing bid_1/ask_1"):
            await adapter.get_orderbook("005930")

    async def test_raises_when_empty_stock_code(self, adapter):
        with pytest.raises(KiwoomAPIError, match="stock_code is required"):
            await adapter.get_orderbook("")

    async def test_transport_error_wraps_to_timeout(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_orderbook.side_effect = (
            V71KiwoomTransportError("net")
        )
        with pytest.raises(KiwoomTimeoutError):
            await adapter.get_orderbook("005930")


# ---------------------------------------------------------------------------
# Group C: get_current_price (3 cases)
# ---------------------------------------------------------------------------


class TestGetCurrentPrice:
    async def test_returns_cur_prc_from_ka10001(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_stock_info.return_value = _make_response(
            api_id="ka10001",
            data={"cur_prc": "73500", "stk_nm": "삼성전자"},
        )
        price = await adapter.get_current_price("005930")
        assert price == 73500

    async def test_raises_when_cur_prc_missing(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_stock_info.return_value = _make_response(
            api_id="ka10001",
            data={"stk_nm": "삼성전자"},
        )
        with pytest.raises(KiwoomAPIError, match="missing cur_prc"):
            await adapter.get_current_price("005930")

    async def test_business_error_maps_to_rate_limit(
        self, adapter, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_stock_info.side_effect = V71KiwoomBusinessError(
            "rl", return_code=1700, return_msg="rate", api_id="ka10001",
        )
        with pytest.raises(KiwoomRateLimitError):
            await adapter.get_current_price("005930")


# ---------------------------------------------------------------------------
# Group D: send_order (6 cases)
# ---------------------------------------------------------------------------


class TestSendOrder:
    async def test_buy_limit_delegates_to_order_manager(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.submit_order.return_value = _make_submit_result(
            direction=OrderDirection.BUY,
        )

        result = await adapter.send_order(
            stock_code="005930",
            side=V71OrderSide.BUY,
            quantity=10,
            price=70000,
            order_type=V71OrderType.LIMIT,
        )

        order_manager_mock.submit_order.assert_awaited_once()
        request = order_manager_mock.submit_order.call_args.args[0]
        assert request.direction == OrderDirection.BUY
        assert request.trade_type == OrderTradeType.LIMIT
        assert request.price == 70000
        assert result.order_id == "ORDER12345"
        assert result.side == V71OrderSide.BUY
        assert result.requested_quantity == 10

    async def test_sell_market_passes_price_none_to_request(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.submit_order.return_value = _make_submit_result(
            direction=OrderDirection.SELL,
        )

        await adapter.send_order(
            stock_code="005930",
            side=V71OrderSide.SELL,
            quantity=5,
            price=70000,
            order_type=V71OrderType.MARKET,
        )

        request = order_manager_mock.submit_order.call_args.args[0]
        assert request.trade_type == OrderTradeType.MARKET
        assert request.price is None  # MARKET → None per V71OrderRequest

    async def test_v71_order_unsupported_wraps_to_kiwoom_api_error(
        self, adapter, order_manager_mock,
    ):
        # Trigger ValueError inside V71OrderRequest construction by passing
        # quantity=0 (V71OrderRequest.__post_init__ raises ValueError).
        with pytest.raises(KiwoomAPIError, match="invalid input"):
            await adapter.send_order(
                stock_code="005930",
                side=V71OrderSide.BUY,
                quantity=0,
                price=70000,
                order_type=V71OrderType.LIMIT,
            )
        order_manager_mock.submit_order.assert_not_awaited()

    async def test_submission_failed_1700_maps_to_rate_limit(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.submit_order.side_effect = V71OrderSubmissionFailed(
            "rate limit", api_id="kt10000", return_code=1700,
            return_msg="rl",
        )

        with pytest.raises(KiwoomRateLimitError):
            await adapter.send_order(
                stock_code="005930",
                side=V71OrderSide.BUY,
                quantity=10,
                price=70000,
                order_type=V71OrderType.LIMIT,
            )

    async def test_submission_failed_8005_maps_to_auth_error(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.submit_order.side_effect = V71OrderSubmissionFailed(
            "token", api_id="kt10000", return_code=8005, return_msg="exp",
        )

        with pytest.raises(KiwoomAuthError):
            await adapter.send_order(
                stock_code="005930",
                side=V71OrderSide.BUY,
                quantity=10,
                price=70000,
                order_type=V71OrderType.LIMIT,
            )

    async def test_submission_failed_no_return_code_maps_to_timeout(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.submit_order.side_effect = V71OrderSubmissionFailed(
            "transport"
        )

        with pytest.raises(KiwoomTimeoutError):
            await adapter.send_order(
                stock_code="005930",
                side=V71OrderSide.BUY,
                quantity=10,
                price=70000,
                order_type=V71OrderType.LIMIT,
            )


# ---------------------------------------------------------------------------
# Group E: cancel_order (3 cases)
# ---------------------------------------------------------------------------


class TestCancelOrder:
    async def test_delegates_to_order_manager(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.cancel_order.return_value = _make_submit_result(
            kiwoom_order_no="CXL99999",
            state=OrderState.CANCELLED,
        )

        result = await adapter.cancel_order(
            order_id="ORDER12345", stock_code="005930",
        )

        order_manager_mock.cancel_order.assert_awaited_once_with(
            kiwoom_order_no="ORDER12345", stock_code="005930",
        )
        assert result.order_id == "CXL99999"

    async def test_raises_for_empty_order_id(self, adapter):
        with pytest.raises(KiwoomAPIError, match="order_id is required"):
            await adapter.cancel_order(order_id="", stock_code="005930")

    async def test_submission_failed_maps_correctly(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.cancel_order.side_effect = V71OrderSubmissionFailed(
            "rl", api_id="kt10003", return_code=1700, return_msg="rate",
        )
        with pytest.raises(KiwoomRateLimitError):
            await adapter.cancel_order(
                order_id="ORDER12345", stock_code="005930",
            )


# ---------------------------------------------------------------------------
# Group F: get_order_status (5 cases)
# ---------------------------------------------------------------------------


class TestGetOrderStatus:
    async def test_db_first_returns_submitted_as_open(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.get_order_state.return_value = _make_v71_order(
            state=OrderState.SUBMITTED,
        )

        status = await adapter.get_order_status("ORDER12345")

        assert status.is_open is True
        assert status.is_cancelled is False
        assert status.requested_quantity == 10
        assert status.filled_quantity == 0

    async def test_db_first_returns_cancelled(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.get_order_state.return_value = _make_v71_order(
            state=OrderState.CANCELLED,
        )
        status = await adapter.get_order_status("ORDER12345")
        assert status.is_open is False
        assert status.is_cancelled is True

    async def test_db_first_returns_partial_with_fill_data(
        self, adapter, order_manager_mock,
    ):
        order_manager_mock.get_order_state.return_value = _make_v71_order(
            state=OrderState.PARTIAL,
            quantity=10, filled_quantity=4, filled_avg_price=73500,
        )
        status = await adapter.get_order_status("ORDER12345")
        assert status.is_open is True
        assert status.filled_quantity == 4
        assert status.avg_fill_price == 73500

    async def test_db_miss_falls_back_to_pending_orders(
        self, adapter, kiwoom_client_mock, order_manager_mock,
    ):
        order_manager_mock.get_order_state.return_value = None
        kiwoom_client_mock.get_pending_orders.return_value = _make_response(
            api_id="ka10075",
            data={"oso": [{
                "ord_no": "ORDER12345",
                "stk_cd": "005930",
                "ord_qty": "10",
                "cntr_qty": "0",
                "cntr_pric": "0",
            }]},
        )

        status = await adapter.get_order_status("ORDER12345")

        assert status.is_open is True
        assert status.is_cancelled is False
        assert status.stock_code == "005930"

    async def test_db_miss_and_pending_miss_returns_cancelled(
        self, adapter, kiwoom_client_mock, order_manager_mock,
    ):
        order_manager_mock.get_order_state.return_value = None
        kiwoom_client_mock.get_pending_orders.return_value = _make_response(
            api_id="ka10075",
            data={"oso": []},
        )

        status = await adapter.get_order_status("ORDER12345")

        assert status.is_open is False
        assert status.is_cancelled is True


# ---------------------------------------------------------------------------
# Group G: helpers (5 cases)
# ---------------------------------------------------------------------------


class TestHelpers:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("100", 100),
            ("+200", 200),
            ("-50", -50),
            ("", None),
            ("abc", None),
            (None, None),
            (42, 42),
        ],
    )
    def test_coerce_int(self, raw, expected):
        assert _coerce_int(raw) == expected
