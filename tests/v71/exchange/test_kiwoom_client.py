"""Unit tests for ``src/core/v71/exchange/kiwoom_client.py``.

Spec sources:
  - docs/v71/06_AGENTS_SPEC.md §5 Test Strategy verification (38 cases)
  - docs/v71/12_SECURITY.md §6 (token plaintext must never appear)
  - docs/v71/KIWOOM_API_ANALYSIS.md (5 core APIs)
"""

from __future__ import annotations

import json

import httpx
import pytest

from src.core.v71.exchange.kiwoom_client import (
    ACCOUNT_PATH,
    API_ID_ACCOUNT_BALANCE,
    API_ID_BUY,
    API_ID_CANCEL,
    API_ID_DAILY_CHART,
    API_ID_MINUTE_CHART,
    API_ID_MODIFY,
    API_ID_PENDING_ORDERS,
    API_ID_SELL,
    CHART_PATH,
    LIVE_BASE_URL,
    ORDER_PATH,
    PAPER_BASE_URL,
    V71KiwoomBusinessError,
    V71KiwoomClient,
    V71KiwoomResponse,
    V71KiwoomTradeType,
    V71KiwoomTransportError,
)

# ---------------------------------------------------------------------------
# Group A -- happy path
# ---------------------------------------------------------------------------


async def test_request_sends_bearer_and_returns_response(
    make_kiwoom_client, make_kiwoom_response,
):
    client, transport, _, _ = make_kiwoom_client(
        [make_kiwoom_response(data={"hello": "world"})],
    )
    async with client:
        resp = await client.request(
            api_id="ka10080", endpoint=CHART_PATH, payload={"stk_cd": "005930"},
        )
    assert isinstance(resp, V71KiwoomResponse)
    assert resp.success is True
    assert resp.api_id == "ka10080"
    assert resp.data == {"hello": "world"}
    assert resp.return_code == 0
    assert transport.calls == 1
    req = transport.requests[0]
    assert req.method == "POST"
    assert req.headers["api-id"] == "ka10080"
    assert req.headers["authorization"] == "Bearer TKN_FIXTURE_TOKEN_1234ABCD"
    assert json.loads(req.content) == {"stk_cd": "005930"}


async def test_get_minute_chart_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.get_minute_chart(stock_code="005930", tic_scope="3")
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_MINUTE_CHART
    assert req.url.path == CHART_PATH
    assert json.loads(req.content) == {
        "stk_cd": "005930", "tic_scope": "3", "upd_stkpc_tp": "1",
    }


async def test_get_daily_chart_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.get_daily_chart(stock_code="005930", base_date="20260427")
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_DAILY_CHART
    assert json.loads(req.content) == {
        "stk_cd": "005930", "base_dt": "20260427", "upd_stkpc_tp": "1",
    }


async def test_place_buy_order_limit_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, rate_limiter = make_kiwoom_client(
        [make_kiwoom_response(data={"ord_no": "0000139"})],
    )
    async with client:
        resp = await client.place_buy_order(
            stock_code="005930", quantity=10, price=70000,
            trade_type=V71KiwoomTradeType.LIMIT,
        )
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_BUY
    assert req.url.path == ORDER_PATH
    assert json.loads(req.content) == {
        "dmst_stex_tp": "KRX", "stk_cd": "005930",
        "ord_qty": "10", "ord_uv": "70000", "trde_tp": "0",
    }
    assert resp.data == {"ord_no": "0000139"}
    rate_limiter.acquire.assert_awaited_once()


async def test_place_sell_order_market_payload(
    make_kiwoom_client, make_kiwoom_response,
):
    client, transport, _, _ = make_kiwoom_client(
        [make_kiwoom_response(data={"ord_no": "0000200"})],
    )
    async with client:
        await client.place_sell_order(
            stock_code="005930", quantity=10, price=None,
            trade_type=V71KiwoomTradeType.MARKET,
        )
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_SELL
    body = json.loads(req.content)
    assert body == {
        "dmst_stex_tp": "KRX", "stk_cd": "005930",
        "ord_qty": "10", "trde_tp": "3",
    }
    assert "ord_uv" not in body


async def test_modify_order_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.modify_order(
            orig_order_no="0000139", stock_code="005930",
            modify_qty=5, modify_price=72000,
        )
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_MODIFY
    assert json.loads(req.content) == {
        "dmst_stex_tp": "KRX", "orig_ord_no": "0000139",
        "stk_cd": "005930", "mdfy_qty": "5", "mdfy_uv": "72000",
    }


async def test_cancel_order_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.cancel_order(orig_order_no="0000139", stock_code="005930")
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_CANCEL
    assert json.loads(req.content)["cncl_qty"] == "0"  # 0 = remainder


async def test_get_pending_orders_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.get_pending_orders(all_stk_tp="1", stock_code="005930")
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_PENDING_ORDERS
    assert req.url.path == ACCOUNT_PATH
    body = json.loads(req.content)
    assert body == {
        "all_stk_tp": "1", "trde_tp": "0", "stex_tp": "0", "stk_cd": "005930",
    }


async def test_get_account_balance_payload(make_kiwoom_client, make_kiwoom_response):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.get_account_balance()
    req = transport.requests[0]
    assert req.headers["api-id"] == API_ID_ACCOUNT_BALANCE
    assert json.loads(req.content) == {"qry_tp": "1", "dmst_stex_tp": "KRX"}


async def test_pagination_headers_propagate(make_kiwoom_client, make_kiwoom_response):
    client, _, _, _ = make_kiwoom_client(
        [make_kiwoom_response(cont_yn="Y", next_key="ABC123")],
    )
    async with client:
        resp = await client.get_pending_orders()
    assert resp.cont_yn == "Y"
    assert resp.next_key == "ABC123"


async def test_rate_limiter_and_token_called_each_request(
    make_kiwoom_client, make_kiwoom_response,
):
    client, transport, token_mgr, rate_limiter = make_kiwoom_client(
        [make_kiwoom_response()] * 3,
    )
    async with client:
        await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})
        await client.request(api_id="ka10081", endpoint=CHART_PATH, payload={})
        await client.request(api_id="kt00018", endpoint=ACCOUNT_PATH, payload={})
    assert rate_limiter.acquire.await_count == 3
    assert token_mgr.get_token.await_count == 3
    assert transport.calls == 3


# ---------------------------------------------------------------------------
# Group B -- error paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_code", [400, 401, 429, 500, 503])
async def test_http_error_raises_transport_error(
    make_kiwoom_client, make_kiwoom_response, status_code,
):
    client, _, _, _ = make_kiwoom_client(
        [make_kiwoom_response(status=status_code)],
    )
    async with client:
        with pytest.raises(V71KiwoomTransportError) as excinfo:
            await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})
    assert str(status_code) in str(excinfo.value)


async def test_invalid_json_response_raises_transport_error():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(200, content=b"not json"),
    )
    http = httpx.AsyncClient(transport=transport, base_url=LIVE_BASE_URL)
    from unittest.mock import AsyncMock

    from src.core.v71.exchange.kiwoom_client import V71KiwoomClient
    tm = AsyncMock()

    tm.get_token = AsyncMock(return_value="TKN")
    rl = AsyncMock()

    rl.acquire = AsyncMock(return_value=0.0)
    client = V71KiwoomClient(
        token_manager=tm, rate_limiter=rl, http_client=http,
        base_url=LIVE_BASE_URL,
    )
    async with client:
        with pytest.raises(V71KiwoomTransportError):
            await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})


async def test_non_dict_response_raises_transport_error():
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(200, json=["not", "a", "dict"]),
    )
    http = httpx.AsyncClient(transport=transport, base_url=LIVE_BASE_URL)
    from unittest.mock import AsyncMock
    tm = AsyncMock()

    tm.get_token = AsyncMock(return_value="TKN")
    rl = AsyncMock()

    rl.acquire = AsyncMock(return_value=0.0)
    client = V71KiwoomClient(
        token_manager=tm, rate_limiter=rl, http_client=http,
        base_url=LIVE_BASE_URL,
    )
    async with client:
        with pytest.raises(V71KiwoomTransportError, match="not an object"):
            await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})


async def test_transport_exception_propagates_as_transport_error():
    def _raise(_request):
        raise httpx.ConnectError("boom")

    transport = httpx.MockTransport(_raise)
    http = httpx.AsyncClient(transport=transport, base_url=LIVE_BASE_URL)
    from unittest.mock import AsyncMock
    tm = AsyncMock()

    tm.get_token = AsyncMock(return_value="TKN")
    rl = AsyncMock()

    rl.acquire = AsyncMock(return_value=0.0)
    client = V71KiwoomClient(
        token_manager=tm, rate_limiter=rl, http_client=http,
        base_url=LIVE_BASE_URL,
    )
    async with client:
        with pytest.raises(V71KiwoomTransportError):
            await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})


async def test_business_error_carries_attributes(
    make_kiwoom_client, make_kiwoom_response,
):
    client, _, _, _ = make_kiwoom_client(
        [make_kiwoom_response(return_code=900100, return_msg="잔고 부족")],
    )
    async with client:
        with pytest.raises(V71KiwoomBusinessError) as excinfo:
            await client.place_buy_order(
                stock_code="005930", quantity=1, price=1000,
                trade_type=V71KiwoomTradeType.LIMIT,
            )
    assert excinfo.value.return_code == 900100
    assert excinfo.value.return_msg == "잔고 부족"
    assert excinfo.value.api_id == API_ID_BUY


# ---------------------------------------------------------------------------
# Group C -- input validation
# ---------------------------------------------------------------------------


def test_request_timeout_must_be_positive(fake_token_manager, fake_rate_limiter):
    with pytest.raises(ValueError):
        V71KiwoomClient(
            token_manager=fake_token_manager,
            rate_limiter=fake_rate_limiter,
            request_timeout=0,
        )


def test_base_url_must_be_https(fake_token_manager, fake_rate_limiter):
    with pytest.raises(ValueError, match="https://"):
        V71KiwoomClient(
            token_manager=fake_token_manager,
            rate_limiter=fake_rate_limiter,
            base_url="http://api.kiwoom.com",
        )


def test_base_url_paper_default(fake_token_manager, fake_rate_limiter):
    client = V71KiwoomClient(
        token_manager=fake_token_manager,
        rate_limiter=fake_rate_limiter,
        is_paper=True,
    )
    assert client.base_url == PAPER_BASE_URL
    assert client.is_paper is True


def test_base_url_live_default(fake_token_manager, fake_rate_limiter):
    client = V71KiwoomClient(
        token_manager=fake_token_manager,
        rate_limiter=fake_rate_limiter,
    )
    assert client.base_url == LIVE_BASE_URL


@pytest.mark.parametrize("qty", [0, -1, -100])
async def test_place_order_rejects_non_positive_quantity(
    make_kiwoom_client, qty,
):
    client, _, _, _ = make_kiwoom_client()
    async with client:
        with pytest.raises(ValueError, match="quantity"):
            await client.place_buy_order(
                stock_code="005930", quantity=qty, price=1000,
                trade_type=V71KiwoomTradeType.LIMIT,
            )


@pytest.mark.parametrize("price", [None, 0, -1])
async def test_place_limit_order_rejects_invalid_price(make_kiwoom_client, price):
    client, _, _, _ = make_kiwoom_client()
    async with client:
        with pytest.raises(ValueError, match="price"):
            await client.place_buy_order(
                stock_code="005930", quantity=1, price=price,
                trade_type=V71KiwoomTradeType.LIMIT,
            )


async def test_modify_order_validates_inputs(make_kiwoom_client):
    client, _, _, _ = make_kiwoom_client()
    async with client:
        with pytest.raises(ValueError, match="orig_order_no"):
            await client.modify_order(
                orig_order_no="", stock_code="005930",
                modify_qty=1, modify_price=1000,
            )
        with pytest.raises(ValueError, match="modify_qty"):
            await client.modify_order(
                orig_order_no="X", stock_code="005930",
                modify_qty=0, modify_price=1000,
            )
        with pytest.raises(ValueError, match="modify_price"):
            await client.modify_order(
                orig_order_no="X", stock_code="005930",
                modify_qty=1, modify_price=0,
            )


async def test_cancel_order_validates_inputs(make_kiwoom_client):
    client, _, _, _ = make_kiwoom_client()
    async with client:
        with pytest.raises(ValueError, match="orig_order_no"):
            await client.cancel_order(orig_order_no="", stock_code="005930")
        with pytest.raises(ValueError, match="cancel_qty"):
            await client.cancel_order(
                orig_order_no="X", stock_code="005930", cancel_qty=-1,
            )


# ---------------------------------------------------------------------------
# Group D -- security regression (★)
# ---------------------------------------------------------------------------


async def test_token_plaintext_never_appears_in_transport_error():
    """4xx 응답 본문이 토큰을 echo back해도 raise 메시지에서 마스킹되어야 한다."""
    secret = "TKN_FIXTURE_TOKEN_1234ABCD"
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(
            500,
            text=f"server echoed: Authorization Bearer {secret} reflected",
        ),
    )
    http = httpx.AsyncClient(transport=transport, base_url=LIVE_BASE_URL)
    from unittest.mock import AsyncMock
    tm = AsyncMock()

    tm.get_token = AsyncMock(return_value=secret)
    rl = AsyncMock()

    rl.acquire = AsyncMock(return_value=0.0)
    client = V71KiwoomClient(
        token_manager=tm, rate_limiter=rl, http_client=http,
        base_url=LIVE_BASE_URL,
    )
    async with client:
        with pytest.raises(V71KiwoomTransportError) as excinfo:
            await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})
    assert secret not in str(excinfo.value)


async def test_logs_never_contain_plaintext_token(
    make_kiwoom_client, make_kiwoom_response, caplog,
):
    secret = "TKN_FIXTURE_TOKEN_1234ABCD"
    client, _, _, _ = make_kiwoom_client(
        [
            make_kiwoom_response(),  # success
            make_kiwoom_response(status=500),  # transport error
            make_kiwoom_response(return_code=999, return_msg="biz fail"),  # business
        ],
    )
    async with client:
        await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})
        with pytest.raises(V71KiwoomTransportError):
            await client.request(api_id="ka10080", endpoint=CHART_PATH, payload={})
        with pytest.raises(V71KiwoomBusinessError):
            await client.request(api_id="ka10081", endpoint=CHART_PATH, payload={})
    for record in caplog.records:
        assert secret not in record.getMessage()


def test_repr_does_not_leak_secrets(fake_token_manager, fake_rate_limiter):
    client = V71KiwoomClient(
        token_manager=fake_token_manager,
        rate_limiter=fake_rate_limiter,
        is_paper=True,
    )
    text = repr(client)
    assert "TKN_FIXTURE" not in text
    assert client.base_url in text   # only safe data


# ---------------------------------------------------------------------------
# Group E -- lifecycle
# ---------------------------------------------------------------------------


async def test_external_client_not_closed_on_aclose(fake_token_manager, fake_rate_limiter):
    transport = httpx.MockTransport(
        lambda _req: httpx.Response(200, json={"return_code": 0, "return_msg": "OK"}),
    )
    http = httpx.AsyncClient(transport=transport, base_url=LIVE_BASE_URL)
    client = V71KiwoomClient(
        token_manager=fake_token_manager, rate_limiter=fake_rate_limiter,
        http_client=http, base_url=LIVE_BASE_URL,
    )
    await client.aclose()
    assert not http.is_closed
    await http.aclose()


async def test_owned_client_closed_on_aclose(fake_token_manager, fake_rate_limiter):
    client = V71KiwoomClient(
        token_manager=fake_token_manager, rate_limiter=fake_rate_limiter,
        is_paper=True,
    )
    inner = await client._ensure_client()
    assert not inner.is_closed
    await client.aclose()
    assert inner.is_closed


async def test_async_context_manager_closes(fake_token_manager, fake_rate_limiter):
    client = V71KiwoomClient(
        token_manager=fake_token_manager, rate_limiter=fake_rate_limiter,
        is_paper=True,
    )
    async with client as ctx:
        inner = await ctx._ensure_client()
        assert not inner.is_closed
    assert inner.is_closed


# ---------------------------------------------------------------------------
# Group F -- additional
# ---------------------------------------------------------------------------


async def test_pagination_headers_passed_in_request(
    make_kiwoom_client, make_kiwoom_response,
):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.get_pending_orders(cont_yn="Y", next_key="abc")
    req = transport.requests[0]
    assert req.headers["cont-yn"] == "Y"
    assert req.headers["next-key"] == "abc"


@pytest.mark.parametrize("dmst", ["KRX", "NXT"])
async def test_dmst_stex_tp_propagates(
    make_kiwoom_client, make_kiwoom_response, dmst,
):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.place_buy_order(
            stock_code="005930", quantity=1, price=1000,
            trade_type=V71KiwoomTradeType.LIMIT, dmst_stex_tp=dmst,
        )
    body = json.loads(transport.requests[0].content)
    assert body["dmst_stex_tp"] == dmst


async def test_pending_orders_omits_stk_cd_when_none(
    make_kiwoom_client, make_kiwoom_response,
):
    client, transport, _, _ = make_kiwoom_client([make_kiwoom_response()])
    async with client:
        await client.get_pending_orders()
    body = json.loads(transport.requests[0].content)
    assert "stk_cd" not in body
