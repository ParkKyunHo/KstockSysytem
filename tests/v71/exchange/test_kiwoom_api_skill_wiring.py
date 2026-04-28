"""Unit tests for ``src/core/v71/skills/kiwoom_api_skill.py`` P5-Kiwoom-Wire.

Spec sources:
  - 06_AGENTS_SPEC.md §5 Test Strategy verification (38-case plan)
  - 12_SECURITY.md §6 + Security review (M1 token echo / M2 ValueError wrap)
  - 07_SKILLS_SPEC.md §1 (kiwoom_api_skill canonical surface)
  - error_mapper severity policy (1700 / 8005 / 8010 / 8030 / 8031 / 1999)
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from src.core.v71.exchange.error_mapper import (
    V71KiwoomRateLimitError,
    V71KiwoomTokenInvalidError,
)
from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomResponse,
    V71KiwoomTradeType,
    V71KiwoomTransportError,
)
from src.core.v71.skills.kiwoom_api_skill import (
    KiwoomAPIContext,
    KiwoomAPIError,
    KiwoomAPIRequest,
    KiwoomAuthError,
    KiwoomRateLimitError,
    KiwoomTimeoutError,
    _filter_position_by_stock,
    _require_v71_client,
    call_kiwoom_api,
    cancel_order,
    get_balance,
    get_order_status,
    get_position,
    send_buy_order,
    send_sell_order,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_response(
    *,
    api_id: str = "kt10000",
    return_code: int = 0,
    return_msg: str = "OK",
    data: dict | None = None,
    cont_yn: str = "N",
    next_key: str = "",
    duration_ms: int = 12,
) -> V71KiwoomResponse:
    return V71KiwoomResponse(
        success=True,
        api_id=api_id,
        data=data or {},
        return_code=return_code,
        return_msg=return_msg,
        cont_yn=cont_yn,
        next_key=next_key,
        duration_ms=duration_ms,
    )


@pytest.fixture
def kiwoom_client_mock():
    """``spec=V71KiwoomClient`` so the isinstance guard in
    ``_require_v71_client`` accepts the mock."""
    client = AsyncMock(spec=V71KiwoomClient)
    return client


@pytest.fixture
def context(kiwoom_client_mock):
    return KiwoomAPIContext(
        client=kiwoom_client_mock,
        auth_manager=None,
        rate_limiter=None,
    )


# ---------------------------------------------------------------------------
# Group A: _require_v71_client guard (3 cases)
# ---------------------------------------------------------------------------


class TestRequireV71Client:
    def test_returns_client_for_v71_kiwoom_client(self, kiwoom_client_mock):
        ctx = KiwoomAPIContext(
            client=kiwoom_client_mock, auth_manager=None, rate_limiter=None,
        )
        assert _require_v71_client(ctx) is kiwoom_client_mock

    def test_raises_type_error_for_string(self):
        ctx = KiwoomAPIContext(
            client="not_a_client", auth_manager=None, rate_limiter=None,
        )
        with pytest.raises(TypeError, match="V71KiwoomClient"):
            _require_v71_client(ctx)

    def test_raises_type_error_for_none(self):
        ctx = KiwoomAPIContext(
            client=None, auth_manager=None, rate_limiter=None,
        )
        with pytest.raises(TypeError):
            _require_v71_client(ctx)


# ---------------------------------------------------------------------------
# Group B: call_kiwoom_api (4 cases)
# ---------------------------------------------------------------------------


class TestCallKiwoomApi:
    async def test_returns_kiwoom_response_on_success(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.request.return_value = _make_response(
            api_id="kt10000", data={"ord_no": "0001"},
        )
        request = KiwoomAPIRequest(
            endpoint="/api/dostk/ordr",
            method="POST",
            api_id="kt10000",
            payload={"stk_cd": "005930"},
        )

        result = await call_kiwoom_api(context, request)

        assert result.success is True
        assert result.data == {"ord_no": "0001"}
        kiwoom_client_mock.request.assert_awaited_once()

    async def test_transport_error_wraps_to_timeout_error(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.request.side_effect = V71KiwoomTransportError(
            "conn refused"
        )
        request = KiwoomAPIRequest(
            endpoint="/api/dostk/ordr", method="POST",
            api_id="kt10000", payload={},
        )

        with pytest.raises(KiwoomTimeoutError) as excinfo:
            await call_kiwoom_api(context, request)

        assert isinstance(excinfo.value.__cause__, V71KiwoomTransportError)
        assert excinfo.value.v71_mapped is None

    async def test_business_1700_maps_to_rate_limit(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.request.side_effect = V71KiwoomBusinessError(
            "rate limit", return_code=1700, return_msg="rl", api_id="kt10000",
        )
        request = KiwoomAPIRequest(
            endpoint="/api/dostk/ordr", method="POST",
            api_id="kt10000", payload={},
        )

        with pytest.raises(KiwoomRateLimitError) as excinfo:
            await call_kiwoom_api(context, request)

        assert isinstance(excinfo.value.v71_mapped, V71KiwoomRateLimitError)

    async def test_business_8005_maps_to_auth_error(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.request.side_effect = V71KiwoomBusinessError(
            "token", return_code=8005, return_msg="exp", api_id="kt10000",
        )
        request = KiwoomAPIRequest(
            endpoint="/api/dostk/ordr", method="POST",
            api_id="kt10000", payload={},
        )

        with pytest.raises(KiwoomAuthError) as excinfo:
            await call_kiwoom_api(context, request)

        assert isinstance(excinfo.value.v71_mapped, V71KiwoomTokenInvalidError)


# ---------------------------------------------------------------------------
# Group C: send_buy_order (5 cases)
# ---------------------------------------------------------------------------


class TestSendBuyOrder:
    async def test_limit_passes_price(self, context, kiwoom_client_mock):
        kiwoom_client_mock.place_buy_order.return_value = _make_response(
            data={"ord_no": "1"},
        )

        await send_buy_order(
            context, "005930", quantity=10, price=70000, order_type="LIMIT",
        )

        call_kwargs = kiwoom_client_mock.place_buy_order.call_args.kwargs
        assert call_kwargs["price"] == 70000
        assert call_kwargs["trade_type"] == V71KiwoomTradeType.LIMIT

    async def test_market_passes_price_none(self, context, kiwoom_client_mock):
        kiwoom_client_mock.place_buy_order.return_value = _make_response()

        await send_buy_order(
            context, "005930", quantity=10, price=70000, order_type="MARKET",
        )

        call_kwargs = kiwoom_client_mock.place_buy_order.call_args.kwargs
        assert call_kwargs["price"] is None

    async def test_invalid_order_type_raises_kiwoom_api_error(
        self, context, kiwoom_client_mock,
    ):
        with pytest.raises(KiwoomAPIError, match="order_type"):
            await send_buy_order(
                context, "005930", 10, 70000, order_type="INVALID",
            )
        kiwoom_client_mock.place_buy_order.assert_not_awaited()

    async def test_value_error_wrapped_to_kiwoom_api_error(
        self, context, kiwoom_client_mock,
    ):
        # Security M2: V71KiwoomClient ValueError must surface as
        # KiwoomAPIError, not bare ValueError.
        kiwoom_client_mock.place_buy_order.side_effect = ValueError(
            "quantity must be > 0"
        )

        with pytest.raises(KiwoomAPIError, match="invalid input"):
            await send_buy_order(context, "005930", 0, 70000, "LIMIT")

    async def test_business_1700_maps(self, context, kiwoom_client_mock):
        kiwoom_client_mock.place_buy_order.side_effect = V71KiwoomBusinessError(
            "rl", return_code=1700, return_msg="rate", api_id="kt10000",
        )

        with pytest.raises(KiwoomRateLimitError) as excinfo:
            await send_buy_order(context, "005930", 10, 70000, "LIMIT")

        assert isinstance(excinfo.value.v71_mapped, V71KiwoomRateLimitError)


# ---------------------------------------------------------------------------
# Group D: send_sell_order (3 cases)
# ---------------------------------------------------------------------------


class TestSendSellOrder:
    @pytest.mark.parametrize("order_type", ["LIMIT", "MARKET"])
    async def test_normal_paths(
        self, context, kiwoom_client_mock, order_type,
    ):
        kiwoom_client_mock.place_sell_order.return_value = _make_response()
        await send_sell_order(
            context, "005930", quantity=5, price=71000, order_type=order_type,
        )
        kiwoom_client_mock.place_sell_order.assert_awaited_once()

    async def test_invalid_order_type_raises(self, context):
        with pytest.raises(KiwoomAPIError):
            await send_sell_order(context, "005930", 5, 71000, "BAD")

    async def test_value_error_wrapped(self, context, kiwoom_client_mock):
        kiwoom_client_mock.place_sell_order.side_effect = ValueError(
            "LIMIT order requires price > 0"
        )
        with pytest.raises(KiwoomAPIError, match="invalid input"):
            await send_sell_order(context, "005930", 5, 0, "LIMIT")


# ---------------------------------------------------------------------------
# Group E: cancel_order (3 cases)
# ---------------------------------------------------------------------------


class TestCancelOrder:
    async def test_normal_cancel_passes_zero_qty(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.cancel_order.return_value = _make_response()

        await cancel_order(context, "ORD123", "005930")

        call_kwargs = kiwoom_client_mock.cancel_order.call_args.kwargs
        assert call_kwargs["cancel_qty"] == 0
        assert call_kwargs["orig_order_no"] == "ORD123"
        assert call_kwargs["stock_code"] == "005930"

    async def test_value_error_wrapped(self, context, kiwoom_client_mock):
        kiwoom_client_mock.cancel_order.side_effect = ValueError(
            "orig_order_no is required"
        )
        with pytest.raises(KiwoomAPIError, match="invalid input"):
            await cancel_order(context, "", "005930")

    async def test_business_error_mapped(self, context, kiwoom_client_mock):
        kiwoom_client_mock.cancel_order.side_effect = V71KiwoomBusinessError(
            "rate", return_code=1700, return_msg="rl", api_id="kt10003",
        )
        with pytest.raises(KiwoomRateLimitError):
            await cancel_order(context, "ORD123", "005930")


# ---------------------------------------------------------------------------
# Group F: get_balance (2 cases)
# ---------------------------------------------------------------------------


class TestGetBalance:
    async def test_returns_balance(self, context, kiwoom_client_mock):
        kiwoom_client_mock.get_account_balance.return_value = _make_response(
            data={"prsm_dpst_aset_amt": "1000000"},
        )
        result = await get_balance(context)
        assert result.success is True
        assert result.data["prsm_dpst_aset_amt"] == "1000000"

    async def test_transport_error_wrapped(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_account_balance.side_effect = (
            V71KiwoomTransportError("net")
        )
        with pytest.raises(KiwoomTimeoutError):
            await get_balance(context)


# ---------------------------------------------------------------------------
# Group G: get_position (4 cases)
# ---------------------------------------------------------------------------


class TestGetPosition:
    async def test_returns_full_response_when_no_filter(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_account_balance.return_value = _make_response(
            data={"acnt_evlt_remn_indv_tot": [
                {"stk_cd": "005930", "rmnd_qty": "100"},
                {"stk_cd": "000660", "rmnd_qty": "50"},
            ]},
        )
        result = await get_position(context, stock_code=None)
        assert "acnt_evlt_remn_indv_tot" in result.data

    async def test_returns_filtered_position(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_account_balance.return_value = _make_response(
            data={"acnt_evlt_remn_indv_tot": [
                {"stk_cd": "005930", "rmnd_qty": "100"},
            ]},
        )
        result = await get_position(context, stock_code="005930")
        assert result.data["position"]["stk_cd"] == "005930"

    async def test_returns_position_none_when_not_found(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_account_balance.return_value = _make_response(
            data={"acnt_evlt_remn_indv_tot": [
                {"stk_cd": "000660", "rmnd_qty": "50"},
            ]},
        )
        result = await get_position(context, stock_code="005930")
        assert result.success is True
        assert result.data["position"] is None

    async def test_returns_position_none_for_empty_holdings(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_account_balance.return_value = _make_response(
            data={"acnt_evlt_remn_indv_tot": []},
        )
        result = await get_position(context, stock_code="005930")
        assert result.data["position"] is None


# ---------------------------------------------------------------------------
# Group H: get_order_status (4 cases)
# ---------------------------------------------------------------------------


class TestGetOrderStatus:
    async def test_returns_found_when_order_pending(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_pending_orders.return_value = _make_response(
            api_id="ka10075",
            data={"oso": [{"ord_no": "ORD123", "ord_stt": "접수"}]},
        )
        result = await get_order_status(context, "ORD123")
        assert result.data["found"] is True
        assert result.data["order"]["ord_no"] == "ORD123"

    async def test_returns_not_found_when_absent(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_pending_orders.return_value = _make_response(
            api_id="ka10075",
            data={"oso": []},
        )
        result = await get_order_status(context, "ORD999")
        assert result.data["found"] is False
        assert result.data["order"] is None

    async def test_transport_error_wrapped(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_pending_orders.side_effect = (
            V71KiwoomTransportError("net")
        )
        with pytest.raises(KiwoomTimeoutError):
            await get_order_status(context, "ORD1")

    async def test_business_error_mapped(
        self, context, kiwoom_client_mock,
    ):
        kiwoom_client_mock.get_pending_orders.side_effect = (
            V71KiwoomBusinessError(
                "tk", return_code=8005, return_msg="exp", api_id="ka10075",
            )
        )
        with pytest.raises(KiwoomAuthError):
            await get_order_status(context, "ORD1")


# ---------------------------------------------------------------------------
# Group I: KiwoomAPIError v71_mapped attribute (4 cases)
# ---------------------------------------------------------------------------


class TestKiwoomAPIErrorV71Mapped:
    def test_default_v71_mapped_is_none(self):
        err = KiwoomAPIError("plain message")
        assert err.v71_mapped is None
        assert str(err) == "plain message"

    def test_keyword_only_v71_mapped_preserved(self):
        v71 = V71KiwoomRateLimitError(
            "rl", return_code=1700, return_msg="rate",
            api_id="kt10000", severity="HIGH",
        )
        err = KiwoomAPIError("wrapped", v71_mapped=v71)
        assert err.v71_mapped is v71

    def test_subclass_inherits_v71_mapped(self):
        v71 = V71KiwoomTokenInvalidError(
            "tk", return_code=8005, return_msg="exp",
            api_id="kt10000", severity="MEDIUM",
        )
        err = KiwoomAuthError("auth fail", v71_mapped=v71)
        assert err.v71_mapped is v71

    def test_v71_mapped_must_be_keyword_only(self):
        v71 = V71KiwoomRateLimitError(
            "rl", return_code=1700, return_msg="rate",
            api_id="kt10000", severity="HIGH",
        )
        with pytest.raises(TypeError):
            # positional — must fail
            KiwoomAPIError("msg", v71)


# ---------------------------------------------------------------------------
# Group J: _filter_position_by_stock helper (4 cases)
# ---------------------------------------------------------------------------


class TestFilterPositionByStock:
    def test_returns_matching_holding(self):
        data = {"acnt_evlt_remn_indv_tot": [
            {"stk_cd": "005930", "rmnd_qty": "10"},
            {"stk_cd": "000660", "rmnd_qty": "5"},
        ]}
        assert _filter_position_by_stock(data, "005930") == {
            "stk_cd": "005930", "rmnd_qty": "10",
        }

    def test_returns_none_when_not_found(self):
        data = {"acnt_evlt_remn_indv_tot": [
            {"stk_cd": "000660", "rmnd_qty": "5"},
        ]}
        assert _filter_position_by_stock(data, "005930") is None

    def test_returns_none_for_empty_holdings(self):
        assert _filter_position_by_stock({"acnt_evlt_remn_indv_tot": []}, "005930") is None

    def test_returns_none_for_missing_holdings_key(self):
        assert _filter_position_by_stock({}, "005930") is None


# ---------------------------------------------------------------------------
# Group K: security regression (2 cases)
# ---------------------------------------------------------------------------


class TestSecurityRegression:
    async def test_skill_layer_does_not_log_during_business_error(
        self, context, kiwoom_client_mock, caplog,
    ):
        # Skill layer must not introduce a NEW logger call that could
        # leak return_msg; that responsibility lives with the
        # notification path (P5-Kiwoom-Notify).
        kiwoom_client_mock.request.side_effect = V71KiwoomBusinessError(
            "biz", return_code=1700,
            return_msg="Bearer SECRET_TOKEN_XYZ",
            api_id="kt10000",
        )
        request = KiwoomAPIRequest(
            endpoint="/api/dostk/ordr", method="POST",
            api_id="kt10000", payload={},
        )

        with caplog.at_level(logging.DEBUG), pytest.raises(KiwoomRateLimitError):
            await call_kiwoom_api(context, request)

        skill_logs = [
            r for r in caplog.records
            if r.name.startswith("src.core.v71.skills.kiwoom_api_skill")
        ]
        assert skill_logs == []  # no new log surface in this layer

    async def test_v71_mapped_attached_for_notify_routing(
        self, context, kiwoom_client_mock,
    ):
        # Caller can route the wrapped error through notify_kiwoom_error
        # by reading exc.v71_mapped.
        kiwoom_client_mock.request.side_effect = V71KiwoomBusinessError(
            "ip", return_code=8010, return_msg="ip mismatch",
            api_id="kt10000",
        )
        request = KiwoomAPIRequest(
            endpoint="/api/dostk/ordr", method="POST",
            api_id="kt10000", payload={},
        )

        with pytest.raises(KiwoomAPIError) as excinfo:
            await call_kiwoom_api(context, request)

        assert excinfo.value.v71_mapped is not None
        assert excinfo.value.v71_mapped.return_code == 8010
