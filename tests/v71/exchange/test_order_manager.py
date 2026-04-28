"""Unit tests for ``src/core/v71/exchange/order_manager.py``.

Spec sources:
  - 06_AGENTS_SPEC.md §5 Test Strategy verification (78-case plan)
  - 12_SECURITY.md §6 (token plaintext / PII never logged)
  - 02_TRADING_RULES.md §4.3 (partial-fill weighted average) + §6 (avg price
    delegation) + §7 (manual order delegation) + §12 (cancel / modify)
  - KIWOOM_API_ANALYSIS.md §5 (kt10000~10003) + §9 (WebSocket 00 fields)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.core.v71.exchange.kiwoom_client import (
    V71KiwoomBusinessError,
    V71KiwoomResponse,
    V71KiwoomTransportError,
)
from src.core.v71.exchange.kiwoom_websocket import (
    V71KiwoomChannelType,
    V71WebSocketMessage,
)
from src.core.v71.exchange.order_manager import (
    KIWOOM_STATE_ACCEPTED,
    KIWOOM_STATE_CANCELLED,
    KIWOOM_STATE_CONFIRMED,
    KIWOOM_STATE_FILLED,
    KIWOOM_STATE_REJECTED,
    VALID_EXCHANGES,
    WS_FIELD,
    V71OrderFillEvent,
    V71OrderManager,
    V71OrderNotFoundError,
    V71OrderRequest,
    V71OrderSubmissionFailed,
    V71OrderUnsupportedError,
)
from src.database.models import Base
from src.database.models_v71 import (
    OrderDirection,
    OrderState,
    OrderTradeType,
    V71Order,
)

# ---------------------------------------------------------------------------
# Fixtures: in-memory DB
# ---------------------------------------------------------------------------


@pytest.fixture
async def sqlite_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        yield engine
    finally:
        await engine.dispose()


@pytest.fixture
async def session_factory(sqlite_engine):
    maker = async_sessionmaker(
        sqlite_engine, class_=AsyncSession, expire_on_commit=False,
    )

    @asynccontextmanager
    async def _factory() -> AsyncIterator[AsyncSession]:
        session = maker()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    return _factory


@pytest.fixture
def fixed_clock():
    state = {"now": datetime(2026, 4, 28, 9, 30, 0, tzinfo=timezone.utc)}

    def _clock() -> datetime:
        return state["now"]

    def _advance(seconds: float) -> None:
        from datetime import timedelta
        state["now"] += timedelta(seconds=seconds)

    _clock.advance = _advance  # type: ignore[attr-defined]
    return _clock


# ---------------------------------------------------------------------------
# Fixtures: kiwoom client mock
# ---------------------------------------------------------------------------


def _make_response(
    *,
    api_id: str = "kt10000",
    return_code: int = 0,
    return_msg: str = "OK",
    ord_no: str | None = "ORDER12345",
    cont_yn: str = "N",
    next_key: str = "",
    duration_ms: int = 12,
    extra_data: dict[str, Any] | None = None,
) -> V71KiwoomResponse:
    data: dict[str, Any] = {}
    if ord_no is not None:
        data["ord_no"] = ord_no
    if extra_data:
        data.update(extra_data)
    return V71KiwoomResponse(
        success=True,
        api_id=api_id,
        data=data,
        return_code=return_code,
        return_msg=return_msg,
        cont_yn=cont_yn,
        next_key=next_key,
        duration_ms=duration_ms,
    )


@pytest.fixture
def kiwoom_client_mock():
    """AsyncMock-backed V71KiwoomClient stand-in."""
    client = AsyncMock()
    client.place_buy_order = AsyncMock(return_value=_make_response())
    client.place_sell_order = AsyncMock(
        return_value=_make_response(api_id="kt10001")
    )
    client.cancel_order = AsyncMock(
        return_value=_make_response(api_id="kt10003", ord_no="CXL99999")
    )
    client.modify_order = AsyncMock(
        return_value=_make_response(api_id="kt10002", ord_no="MOD88888")
    )
    return client


@pytest.fixture
def order_manager(kiwoom_client_mock, session_factory, fixed_clock):
    return V71OrderManager(
        kiwoom_client=kiwoom_client_mock,
        db_session_factory=session_factory,
        clock=fixed_clock,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ws_msg(
    *,
    channel: V71KiwoomChannelType = V71KiwoomChannelType.ORDER_EXECUTION,
    ord_no: str = "ORDER12345",
    state_kr: str = KIWOOM_STATE_ACCEPTED,
    fill_qty: str | None = None,
    fill_price: str | None = None,
    remaining: str | None = None,
    reject_reason: str | None = None,
    received_at: datetime | None = None,
) -> V71WebSocketMessage:
    values: dict[str, str] = {}
    if ord_no is not None:
        values[WS_FIELD["ORDER_NO"]] = ord_no
    if state_kr is not None:
        values[WS_FIELD["ORDER_STATE"]] = state_kr
    if fill_qty is not None:
        values[WS_FIELD["FILL_QUANTITY"]] = fill_qty
    if fill_price is not None:
        values[WS_FIELD["FILL_PRICE"]] = fill_price
    if remaining is not None:
        values[WS_FIELD["REMAINING_QUANTITY"]] = remaining
    if reject_reason is not None:
        values[WS_FIELD["REJECT_REASON"]] = reject_reason
    received_at = received_at or datetime(
        2026, 4, 28, 9, 30, 1, tzinfo=timezone.utc
    )
    return V71WebSocketMessage(
        channel=channel,
        item="005930",
        name="주문체결",
        values=values,
        received_at=received_at,
        raw={"trnm": "REAL", "data": [{"type": channel.value, "values": values}]},
    )


async def _read_orders(session_factory) -> list[V71Order]:
    async with session_factory() as session:
        result = await session.execute(select(V71Order))
        return list(result.scalars().all())


async def _read_order(session_factory, kiwoom_order_no: str) -> V71Order | None:
    async with session_factory() as session:
        result = await session.execute(
            select(V71Order).where(V71Order.kiwoom_order_no == kiwoom_order_no)
        )
        return result.scalar_one_or_none()


async def _seed_order(
    session_factory,
    *,
    kiwoom_order_no: str = "ORDER12345",
    direction: OrderDirection = OrderDirection.BUY,
    trade_type: OrderTradeType = OrderTradeType.LIMIT,
    quantity: int = 10,
    price: int | None = 73500,
    state: OrderState = OrderState.SUBMITTED,
    filled_quantity: int = 0,
    filled_avg_price: Decimal | None = None,
    position_id: UUID | None = None,
) -> V71Order:
    async with session_factory() as session:
        row = V71Order(
            id=uuid4(),
            kiwoom_order_no=kiwoom_order_no,
            stock_code="005930",
            direction=direction,
            trade_type=trade_type,
            quantity=quantity,
            price=(Decimal(price) if price is not None else None),
            state=state,
            filled_quantity=filled_quantity,
            filled_avg_price=filled_avg_price,
            position_id=position_id,
        )
        session.add(row)
        await session.commit()
        return row


# ---------------------------------------------------------------------------
# Group A: submit_order normal paths (4 cases)
# ---------------------------------------------------------------------------


class TestSubmitOrderNormal:
    async def test_buy_limit_inserts_v71_orders_row(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        # Given: a normal LIMIT buy request
        req = V71OrderRequest(
            stock_code="005930",
            quantity=10,
            price=73500,
            direction=OrderDirection.BUY,
            trade_type=OrderTradeType.LIMIT,
        )

        # When: submit_order is called
        result = await order_manager.submit_order(req)

        # Then: result + DB row both reflect the kiwoom ord_no
        assert result.kiwoom_order_no == "ORDER12345"
        assert result.state == OrderState.SUBMITTED
        assert result.direction == OrderDirection.BUY
        assert result.quantity == 10
        kiwoom_client_mock.place_buy_order.assert_awaited_once()
        kiwoom_client_mock.place_sell_order.assert_not_awaited()
        rows = await _read_orders(session_factory)
        assert len(rows) == 1
        assert rows[0].state == OrderState.SUBMITTED
        assert rows[0].direction == OrderDirection.BUY
        assert rows[0].trade_type == OrderTradeType.LIMIT
        assert rows[0].quantity == 10
        assert rows[0].price == Decimal(73500)
        assert rows[0].kiwoom_order_no == "ORDER12345"

    async def test_buy_market_persists_price_null(
        self, order_manager, session_factory
    ):
        req = V71OrderRequest(
            stock_code="005930",
            quantity=5,
            price=None,
            direction=OrderDirection.BUY,
            trade_type=OrderTradeType.MARKET,
        )

        await order_manager.submit_order(req)

        rows = await _read_orders(session_factory)
        assert len(rows) == 1
        assert rows[0].price is None
        assert rows[0].trade_type == OrderTradeType.MARKET

    async def test_sell_limit_calls_place_sell(
        self, order_manager, kiwoom_client_mock
    ):
        req = V71OrderRequest(
            stock_code="005930",
            quantity=3,
            price=80000,
            direction=OrderDirection.SELL,
            trade_type=OrderTradeType.LIMIT,
        )

        result = await order_manager.submit_order(req)

        assert result.direction == OrderDirection.SELL
        kiwoom_client_mock.place_sell_order.assert_awaited_once()
        kiwoom_client_mock.place_buy_order.assert_not_awaited()

    async def test_sell_market_persists_price_null(
        self, order_manager, session_factory
    ):
        req = V71OrderRequest(
            stock_code="005930",
            quantity=10,
            price=None,
            direction=OrderDirection.SELL,
            trade_type=OrderTradeType.MARKET,
        )

        await order_manager.submit_order(req)

        rows = await _read_orders(session_factory)
        assert rows[0].price is None
        assert rows[0].direction == OrderDirection.SELL


# ---------------------------------------------------------------------------
# Group B: submit_order fail-fast validation (10 cases)
# ---------------------------------------------------------------------------


class TestSubmitOrderValidation:
    @pytest.mark.parametrize("qty", [0, -1, -100])
    def test_quantity_non_positive_raises_value_error(self, qty):
        with pytest.raises(ValueError, match="quantity must be > 0"):
            V71OrderRequest(
                stock_code="005930",
                quantity=qty,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            )

    def test_limit_with_none_price_raises(self):
        with pytest.raises(ValueError, match="LIMIT order requires price"):
            V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=None,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            )

    @pytest.mark.parametrize("price", [0, -1])
    def test_limit_with_zero_or_negative_price_raises(self, price):
        with pytest.raises(ValueError, match="LIMIT order requires price"):
            V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=price,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            )

    def test_market_with_price_raises(self):
        with pytest.raises(ValueError, match="MARKET order must have price=None"):
            V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.MARKET,
            )

    @pytest.mark.parametrize(
        "trade_type",
        [
            OrderTradeType.CONDITIONAL,
            OrderTradeType.AFTER_HOURS,
            OrderTradeType.BEST_LIMIT,
            OrderTradeType.PRIORITY_LIMIT,
        ],
    )
    def test_unsupported_trade_type_raises_unsupported_error(self, trade_type):
        with pytest.raises(V71OrderUnsupportedError):
            V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=trade_type,
            )

    def test_empty_stock_code_raises(self):
        with pytest.raises(ValueError, match="stock_code is required"):
            V71OrderRequest(
                stock_code="",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            )

    def test_invalid_exchange_raises(self):
        with pytest.raises(ValueError, match="exchange must be one of"):
            V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
                exchange="krx",  # lowercase rejected
            )

    @pytest.mark.parametrize("exchange", sorted(VALID_EXCHANGES))
    def test_valid_exchanges_accepted(self, exchange):
        req = V71OrderRequest(
            stock_code="005930",
            quantity=10,
            price=73500,
            direction=OrderDirection.BUY,
            trade_type=OrderTradeType.LIMIT,
            exchange=exchange,
        )
        assert req.exchange == exchange


# ---------------------------------------------------------------------------
# Group C: submit_order kiwoom errors (4 cases)
# ---------------------------------------------------------------------------


class TestSubmitOrderKiwoomErrors:
    async def test_transport_error_wraps_to_submission_failed_no_db_row(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.place_buy_order.side_effect = V71KiwoomTransportError(
            "network timeout"
        )

        with pytest.raises(V71OrderSubmissionFailed) as excinfo:
            await order_manager.submit_order(V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            ))

        assert isinstance(excinfo.value.__cause__, V71KiwoomTransportError)
        rows = await _read_orders(session_factory)
        assert rows == []

    async def test_business_error_propagates_return_code_no_db_row(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.place_buy_order.side_effect = V71KiwoomBusinessError(
            "rate limit",
            return_code=1700,
            return_msg="허용된 요청 개수를 초과하였습니다",
            api_id="kt10000",
        )

        with pytest.raises(V71OrderSubmissionFailed) as excinfo:
            await order_manager.submit_order(V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            ))

        assert excinfo.value.return_code == 1700
        assert excinfo.value.api_id == "kt10000"
        rows = await _read_orders(session_factory)
        assert rows == []

    async def test_response_missing_ord_no_raises(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        kiwoom_client_mock.place_buy_order.return_value = _make_response(
            ord_no=None
        )

        with pytest.raises(V71OrderSubmissionFailed, match="missing ord_no"):
            await order_manager.submit_order(V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            ))

        rows = await _read_orders(session_factory)
        assert rows == []

    async def test_duplicate_kiwoom_order_no_raises_submission_failed(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="DUP123")
        kiwoom_client_mock.place_buy_order.return_value = _make_response(
            ord_no="DUP123"  # already exists
        )

        with pytest.raises(V71OrderSubmissionFailed, match="duplicate"):
            await order_manager.submit_order(V71OrderRequest(
                stock_code="005930",
                quantity=10,
                price=73500,
                direction=OrderDirection.BUY,
                trade_type=OrderTradeType.LIMIT,
            ))


# ---------------------------------------------------------------------------
# Group D: cancel_order (6 cases)
# ---------------------------------------------------------------------------


class TestCancelOrder:
    async def test_inserts_cancel_row_with_orig_link(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG001")

        result = await order_manager.cancel_order(
            kiwoom_order_no="ORG001",
            stock_code="005930",
            cancel_qty=5,
        )

        assert result.state == OrderState.CANCELLED
        assert result.direction == OrderDirection.BUY  # inherited
        rows = await _read_orders(session_factory)
        assert len(rows) == 2
        cancel_row = next(r for r in rows if r.kiwoom_order_no == "CXL99999")
        assert cancel_row.kiwoom_orig_order_no == "ORG001"
        assert cancel_row.state == OrderState.CANCELLED

    async def test_unknown_kiwoom_order_no_raises_not_found(self, order_manager):
        with pytest.raises(V71OrderNotFoundError):
            await order_manager.cancel_order(
                kiwoom_order_no="UNKNOWN",
                stock_code="005930",
            )

    async def test_default_cancel_qty_is_zero(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG002")

        await order_manager.cancel_order(
            kiwoom_order_no="ORG002",
            stock_code="005930",
        )

        kiwoom_client_mock.cancel_order.assert_awaited_once()
        call = kiwoom_client_mock.cancel_order.call_args
        assert call.kwargs["cancel_qty"] == 0

    async def test_negative_cancel_qty_raises_value_error(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG003")
        with pytest.raises(ValueError, match="cancel_qty must be >= 0"):
            await order_manager.cancel_order(
                kiwoom_order_no="ORG003",
                stock_code="005930",
                cancel_qty=-1,
            )

    async def test_invalid_exchange_raises(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG004")
        with pytest.raises(ValueError, match="exchange must be one of"):
            await order_manager.cancel_order(
                kiwoom_order_no="ORG004",
                stock_code="005930",
                exchange="badx",
            )

    async def test_kiwoom_business_error_propagates(
        self, order_manager, kiwoom_client_mock, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG005")
        kiwoom_client_mock.cancel_order.side_effect = V71KiwoomBusinessError(
            "code 9999",
            return_code=9999,
            return_msg="something",
            api_id="kt10003",
        )

        with pytest.raises(V71OrderSubmissionFailed) as excinfo:
            await order_manager.cancel_order(
                kiwoom_order_no="ORG005",
                stock_code="005930",
            )
        assert excinfo.value.return_code == 9999
        assert excinfo.value.api_id == "kt10003"


# ---------------------------------------------------------------------------
# Group E: modify_order (5 cases)
# ---------------------------------------------------------------------------


class TestModifyOrder:
    async def test_replicates_buy_direction_from_origin(
        self, order_manager, session_factory
    ):
        await _seed_order(
            session_factory,
            kiwoom_order_no="ORG010",
            direction=OrderDirection.BUY,
        )

        result = await order_manager.modify_order(
            kiwoom_order_no="ORG010",
            stock_code="005930",
            new_quantity=15,
            new_price=72000,
        )

        assert result.direction == OrderDirection.BUY
        assert result.state == OrderState.SUBMITTED
        rows = await _read_orders(session_factory)
        modify_row = next(r for r in rows if r.kiwoom_order_no == "MOD88888")
        assert modify_row.direction == OrderDirection.BUY
        assert modify_row.kiwoom_orig_order_no == "ORG010"
        assert modify_row.quantity == 15
        assert modify_row.price == Decimal(72000)
        assert modify_row.trade_type == OrderTradeType.LIMIT

    async def test_replicates_sell_direction_from_origin(
        self, order_manager, session_factory
    ):
        await _seed_order(
            session_factory,
            kiwoom_order_no="ORG011",
            direction=OrderDirection.SELL,
        )

        result = await order_manager.modify_order(
            kiwoom_order_no="ORG011",
            stock_code="005930",
            new_quantity=20,
            new_price=80000,
        )
        assert result.direction == OrderDirection.SELL

    async def test_negative_quantity_raises(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG012")
        with pytest.raises(ValueError, match="new_quantity must be > 0"):
            await order_manager.modify_order(
                kiwoom_order_no="ORG012",
                stock_code="005930",
                new_quantity=0,
                new_price=72000,
            )

    async def test_negative_price_raises(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="ORG013")
        with pytest.raises(ValueError, match="new_price must be > 0"):
            await order_manager.modify_order(
                kiwoom_order_no="ORG013",
                stock_code="005930",
                new_quantity=10,
                new_price=0,
            )

    async def test_unknown_kiwoom_order_no_raises_not_found(self, order_manager):
        with pytest.raises(V71OrderNotFoundError):
            await order_manager.modify_order(
                kiwoom_order_no="UNKNOWN",
                stock_code="005930",
                new_quantity=10,
                new_price=72000,
            )


# ---------------------------------------------------------------------------
# Group F: WebSocket Korean state matching (12 cases)
# ---------------------------------------------------------------------------


class TestWebSocketStateMatching:
    async def test_accepted_state_is_noop(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS001")
        msg = _make_ws_msg(ord_no="WS001", state_kr=KIWOOM_STATE_ACCEPTED)

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS001")
        assert row.state == OrderState.SUBMITTED  # unchanged
        assert row.filled_quantity == 0

    async def test_full_fill_marks_filled(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS002", quantity=10)
        msg = _make_ws_msg(
            ord_no="WS002",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="10",
            fill_price="73500",
            remaining="0",
        )

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS002")
        assert row.state == OrderState.FILLED
        assert row.filled_quantity == 10
        assert row.filled_avg_price == Decimal(73500)
        assert row.filled_at is not None

    async def test_partial_fill_first_event(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS003", quantity=100)
        msg = _make_ws_msg(
            ord_no="WS003",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="50",
            fill_price="73500",
            remaining="50",
        )

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS003")
        assert row.state == OrderState.PARTIAL
        assert row.filled_quantity == 50
        assert row.filled_avg_price == Decimal(73500)

    async def test_partial_fill_accumulates_with_weighted_avg(
        self, order_manager, session_factory
    ):
        # PRD 02 §4.3 example: 50@18000 + 50@18050 => avg 18025.
        await _seed_order(session_factory, kiwoom_order_no="WS004", quantity=100)
        await order_manager.on_websocket_order_event(_make_ws_msg(
            ord_no="WS004",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="50",
            fill_price="18000",
            remaining="50",
        ))
        await order_manager.on_websocket_order_event(_make_ws_msg(
            ord_no="WS004",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="50",
            fill_price="18050",
            remaining="0",
        ))

        row = await _read_order(session_factory, "WS004")
        assert row.state == OrderState.FILLED
        assert row.filled_quantity == 100
        assert row.filled_avg_price == Decimal(18025)

    async def test_confirmed_marks_submitted_as_cancelled(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS005")
        msg = _make_ws_msg(ord_no="WS005", state_kr=KIWOOM_STATE_CONFIRMED)

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS005")
        assert row.state == OrderState.CANCELLED
        assert row.cancelled_at is not None

    async def test_confirmed_keeps_partial_state(
        self, order_manager, session_factory
    ):
        await _seed_order(
            session_factory,
            kiwoom_order_no="WS005b",
            state=OrderState.PARTIAL,
            filled_quantity=30,
            filled_avg_price=Decimal(73500),
        )
        msg = _make_ws_msg(ord_no="WS005b", state_kr=KIWOOM_STATE_CONFIRMED)

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS005b")
        assert row.state == OrderState.PARTIAL  # not flipped
        assert row.cancelled_at is not None  # but stamped

    async def test_cancelled_state_with_reason(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS006")
        msg = _make_ws_msg(
            ord_no="WS006",
            state_kr=KIWOOM_STATE_CANCELLED,
            reject_reason="user requested",
        )

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS006")
        assert row.state == OrderState.CANCELLED
        assert row.cancelled_at is not None
        assert row.cancel_reason == "user requested"

    async def test_cancel_reason_truncates_at_100(
        self, order_manager, session_factory, caplog
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS006b")
        long_reason = "x" * 250
        msg = _make_ws_msg(
            ord_no="WS006b",
            state_kr=KIWOOM_STATE_CANCELLED,
            reject_reason=long_reason,
        )

        with caplog.at_level(logging.INFO):
            await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS006b")
        assert row.cancel_reason is not None
        assert len(row.cancel_reason) == 100

    async def test_rejected_state_records_reject_reason(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS007")
        msg = _make_ws_msg(
            ord_no="WS007",
            state_kr=KIWOOM_STATE_REJECTED,
            reject_reason="잔고 부족",
        )

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS007")
        assert row.state == OrderState.REJECTED
        assert row.rejected_at is not None
        assert row.reject_reason == "잔고 부족"

    async def test_unknown_state_logs_warning(
        self, order_manager, session_factory, caplog
    ):
        await _seed_order(session_factory, kiwoom_order_no="WS008")
        msg = _make_ws_msg(ord_no="WS008", state_kr="??")

        with caplog.at_level(logging.WARNING):
            await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS008")
        assert row.state == OrderState.SUBMITTED  # unchanged

    async def test_fill_qty_zero_with_filled_state_is_noop(
        self, order_manager, session_factory
    ):
        # If Kiwoom sends "체결" but fill_qty=0 (corrupt), guard activates.
        await _seed_order(session_factory, kiwoom_order_no="WS009")
        msg = _make_ws_msg(
            ord_no="WS009",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="0",
            fill_price="73500",
            remaining="10",
        )

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS009")
        assert row.state == OrderState.SUBMITTED
        assert row.filled_quantity == 0

    async def test_non_order_channel_is_ignored(
        self, order_manager, session_factory
    ):
        # PRICE_TICK should not trigger any DB read or write.
        await _seed_order(session_factory, kiwoom_order_no="WS010")
        msg = _make_ws_msg(
            channel=V71KiwoomChannelType.PRICE_TICK,
            ord_no="WS010",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="10",
            fill_price="73500",
            remaining="0",
        )

        await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "WS010")
        assert row.state == OrderState.SUBMITTED  # untouched


# ---------------------------------------------------------------------------
# Group G: manual-order callback fallback (3 cases)
# ---------------------------------------------------------------------------


class TestManualOrderCallback:
    async def test_unknown_ord_no_invokes_manual_callback(
        self, kiwoom_client_mock, session_factory, fixed_clock
    ):
        manual_cb = AsyncMock()
        manager = V71OrderManager(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_manual_order=manual_cb,
        )
        msg = _make_ws_msg(ord_no="UNKNOWN_NO", state_kr=KIWOOM_STATE_FILLED)

        await manager.on_websocket_order_event(msg)

        manual_cb.assert_awaited_once_with(msg)

    async def test_unknown_ord_no_without_callback_no_error(
        self, order_manager, caplog
    ):
        msg = _make_ws_msg(ord_no="UNKNOWN_NO", state_kr=KIWOOM_STATE_FILLED)

        with caplog.at_level(logging.INFO):
            await order_manager.on_websocket_order_event(msg)
        # No exception means the test passes.

    async def test_manual_callback_exception_is_isolated_and_type_only(
        self, kiwoom_client_mock, session_factory, fixed_clock, caplog
    ):
        secret_marker = "DO-NOT-LOG-THIS-1234"

        async def _raising(_msg):
            raise RuntimeError(secret_marker)

        manager = V71OrderManager(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_manual_order=_raising,
        )
        msg = _make_ws_msg(ord_no="UNKNOWN_NO", state_kr=KIWOOM_STATE_FILLED)

        with caplog.at_level(logging.ERROR):
            # Must not raise.
            await manager.on_websocket_order_event(msg)

        for record in caplog.records:
            assert secret_marker not in record.getMessage()


# ---------------------------------------------------------------------------
# Group H: concurrency / per-order lock (2 cases)
# ---------------------------------------------------------------------------


class TestConcurrentFills:
    async def test_concurrent_partial_fills_serialise(
        self, order_manager, session_factory
    ):
        # 100주 주문에 25주씩 4번 동시 체결. 가중평균/누적이 정확해야 한다.
        await _seed_order(session_factory, kiwoom_order_no="WSC001", quantity=100)
        msgs = [
            _make_ws_msg(
                ord_no="WSC001",
                state_kr=KIWOOM_STATE_FILLED,
                fill_qty="25",
                fill_price="100",
                remaining=str(75 - i * 25),
            )
            for i in range(4)
        ]

        await asyncio.gather(*[
            order_manager.on_websocket_order_event(m) for m in msgs
        ])

        row = await _read_order(session_factory, "WSC001")
        assert row.filled_quantity == 100
        assert row.filled_avg_price == Decimal(100)
        assert row.state == OrderState.FILLED

    async def test_lock_cleanup_after_terminal_state(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="WSC002")
        msg = _make_ws_msg(
            ord_no="WSC002",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="10",
            fill_price="73500",
            remaining="0",
        )

        await order_manager.on_websocket_order_event(msg)
        # Security H1: terminal state -> lock removed.
        assert order_manager._fill_locks == {}


# ---------------------------------------------------------------------------
# Group I: position_fill callback (3 cases)
# ---------------------------------------------------------------------------


class TestPositionFillCallback:
    async def test_fill_with_position_id_invokes_callback(
        self, kiwoom_client_mock, session_factory, fixed_clock
    ):
        fill_cb = AsyncMock()
        position_id = uuid4()
        await _seed_order(
            session_factory,
            kiwoom_order_no="POS001",
            position_id=position_id,
            quantity=10,
        )
        manager = V71OrderManager(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_position_fill=fill_cb,
        )
        msg = _make_ws_msg(
            ord_no="POS001",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="10",
            fill_price="73500",
            remaining="0",
        )

        await manager.on_websocket_order_event(msg)

        fill_cb.assert_awaited_once()
        event = fill_cb.await_args.args[0]
        assert isinstance(event, V71OrderFillEvent)
        assert event.position_id == position_id
        assert event.fill_quantity == 10
        assert event.fill_price == 73500
        assert event.cumulative_filled_quantity == 10
        assert event.state == OrderState.FILLED

    async def test_fill_without_position_id_skips_callback(
        self, kiwoom_client_mock, session_factory, fixed_clock
    ):
        fill_cb = AsyncMock()
        await _seed_order(session_factory, kiwoom_order_no="POS002")
        manager = V71OrderManager(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_position_fill=fill_cb,
        )
        msg = _make_ws_msg(
            ord_no="POS002",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="10",
            fill_price="73500",
            remaining="0",
        )

        await manager.on_websocket_order_event(msg)

        fill_cb.assert_not_awaited()

    async def test_position_fill_callback_exception_isolated(
        self, kiwoom_client_mock, session_factory, fixed_clock, caplog
    ):
        secret = "POS-CALLBACK-SECRET-9999"

        async def _raising(_event):
            raise RuntimeError(secret)

        position_id = uuid4()
        await _seed_order(
            session_factory,
            kiwoom_order_no="POS003",
            position_id=position_id,
        )
        manager = V71OrderManager(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_position_fill=_raising,
        )
        msg = _make_ws_msg(
            ord_no="POS003",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="10",
            fill_price="73500",
            remaining="0",
        )

        with caplog.at_level(logging.ERROR):
            await manager.on_websocket_order_event(msg)  # must not raise

        for record in caplog.records:
            assert secret not in record.getMessage()


# ---------------------------------------------------------------------------
# Group L: malformed messages (4 cases)
# ---------------------------------------------------------------------------


class TestMalformedMessages:
    async def test_missing_ord_no_logs_warning(
        self, order_manager, caplog
    ):
        msg = _make_ws_msg(ord_no="", state_kr=KIWOOM_STATE_FILLED)

        with caplog.at_level(logging.WARNING):
            await order_manager.on_websocket_order_event(msg)
        # No exception, no DB row created.

    async def test_invalid_fill_qty_logs_warning(
        self, order_manager, session_factory, caplog
    ):
        await _seed_order(session_factory, kiwoom_order_no="MAL002")
        msg = _make_ws_msg(
            ord_no="MAL002",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="abc",   # non-numeric
            fill_price="73500",
            remaining="0",
        )

        with caplog.at_level(logging.WARNING):
            await order_manager.on_websocket_order_event(msg)

        row = await _read_order(session_factory, "MAL002")
        assert row.filled_quantity == 0  # default
        assert row.state == OrderState.SUBMITTED

    async def test_empty_state_logs_warning(
        self, order_manager, session_factory, caplog
    ):
        await _seed_order(session_factory, kiwoom_order_no="MAL003")
        msg = _make_ws_msg(ord_no="MAL003", state_kr="")

        with caplog.at_level(logging.WARNING):
            await order_manager.on_websocket_order_event(msg)
        row = await _read_order(session_factory, "MAL003")
        assert row.state == OrderState.SUBMITTED

    async def test_signed_int_parses(
        self, order_manager, session_factory
    ):
        await _seed_order(session_factory, kiwoom_order_no="MAL004", quantity=10)
        msg = _make_ws_msg(
            ord_no="MAL004",
            state_kr=KIWOOM_STATE_FILLED,
            fill_qty="+10",
            fill_price="+73500",
            remaining="0",
        )
        await order_manager.on_websocket_order_event(msg)
        row = await _read_order(session_factory, "MAL004")
        assert row.filled_quantity == 10


# ---------------------------------------------------------------------------
# Group M: _weighted_average pure helper (5 cases)
# ---------------------------------------------------------------------------


class TestWeightedAverage:
    def test_first_fill_returns_new_price(self):
        result = V71OrderManager._weighted_average(
            prior_filled=0, prior_avg=None, new_qty=10, new_price=100,
        )
        assert result == Decimal(100)

    def test_subsequent_fill_weighted(self):
        result = V71OrderManager._weighted_average(
            prior_filled=10,
            prior_avg=Decimal(100),
            new_qty=10,
            new_price=200,
        )
        assert result == Decimal(150)

    def test_total_qty_zero_falls_back_to_new_price(self):
        # Defensive: should not divide by zero.
        result = V71OrderManager._weighted_average(
            prior_filled=0, prior_avg=Decimal(100), new_qty=0, new_price=200,
        )
        assert result == Decimal(200)

    def test_three_partial_fills_commutative(self):
        # 02 §4.3 example: 50@18000 + 50@18050 = 100@18025.
        avg1 = V71OrderManager._weighted_average(
            prior_filled=0, prior_avg=None, new_qty=50, new_price=18000,
        )
        avg2 = V71OrderManager._weighted_average(
            prior_filled=50, prior_avg=avg1, new_qty=50, new_price=18050,
        )
        assert avg2 == Decimal(18025)

    def test_decimal_precision_preserved(self):
        result = V71OrderManager._weighted_average(
            prior_filled=3,
            prior_avg=Decimal("33.33"),
            new_qty=2,
            new_price=66,
        )
        assert isinstance(result, Decimal)


# ---------------------------------------------------------------------------
# Group N: _coerce_int helper (5 cases via parametrize)
# ---------------------------------------------------------------------------


class TestCoerceInt:
    @pytest.mark.parametrize(
        "raw,default,expected",
        [
            ("+200", 0, 200),
            ("-100", 0, -100),
            ("", 0, 0),
            ("abc", 99, 99),
            (None, 5, 5),
            ("0", 0, 0),
            ("  42  ", 0, 42),
            (123, 0, 123),  # already int
        ],
    )
    def test_coerce_int(self, raw, default, expected):
        from src.core.v71.exchange.order_manager import _coerce_int
        assert _coerce_int(raw, default=default) == expected


# ---------------------------------------------------------------------------
# Group O: _extract_ord_no helper (3 cases)
# ---------------------------------------------------------------------------


class TestExtractOrdNo:
    def test_primary_field(self):
        resp = _make_response(ord_no="12345")
        assert V71OrderManager._extract_ord_no(resp) == "12345"

    def test_missing_raises(self):
        resp = _make_response(ord_no=None)
        with pytest.raises(V71OrderSubmissionFailed, match="missing ord_no"):
            V71OrderManager._extract_ord_no(resp)

    def test_alternate_field_b(self):
        # Some Kiwoom modify/cancel responses use ``base_orig_ord_no``.
        resp = V71KiwoomResponse(
            success=True,
            api_id="kt10003",
            data={"base_orig_ord_no": "9999"},
            return_code=0,
            return_msg="OK",
            cont_yn="N",
            next_key="",
            duration_ms=10,
        )
        assert V71OrderManager._extract_ord_no(resp) == "9999"


# ---------------------------------------------------------------------------
# Group P: security regression (3 cases)
# ---------------------------------------------------------------------------


class TestSecurityRegression:
    async def test_repr_does_not_leak_callbacks_or_session(
        self, kiwoom_client_mock, session_factory, fixed_clock
    ):
        secret = "CALLBACK-SECRET-XYZ"

        async def _cb(_msg):
            return secret  # closed-over

        manager = V71OrderManager(
            kiwoom_client=kiwoom_client_mock,
            db_session_factory=session_factory,
            clock=fixed_clock,
            on_manual_order=_cb,
            on_position_fill=_cb,
        )
        text = repr(manager)
        assert "kiwoom_client" in text
        assert secret not in text
        assert "session_factory" not in text
        assert "on_manual_order" not in text

    async def test_audit_request_contains_no_token(
        self, order_manager, session_factory
    ):
        req = V71OrderRequest(
            stock_code="005930",
            quantity=10,
            price=73500,
            direction=OrderDirection.BUY,
            trade_type=OrderTradeType.LIMIT,
        )
        await order_manager.submit_order(req)

        rows = await _read_orders(session_factory)
        audit = rows[0].kiwoom_raw_request
        assert audit is not None
        for forbidden in (
            "token",
            "Authorization",
            "authorization",
            "app_secret",
            "appkey",
            "secret",
            "Bearer",
        ):
            for value in audit.values():
                assert forbidden not in str(value)

    async def test_sanitize_response_redacts_forbidden_keys(
        self, order_manager, session_factory, kiwoom_client_mock
    ):
        kiwoom_client_mock.place_buy_order.return_value = _make_response(
            ord_no="REDACT001",
            extra_data={"token": "secret-bearer-xxx", "ord_no": "REDACT001"},
        )

        await order_manager.submit_order(V71OrderRequest(
            stock_code="005930",
            quantity=10,
            price=73500,
            direction=OrderDirection.BUY,
            trade_type=OrderTradeType.LIMIT,
        ))

        row = await _read_order(session_factory, "REDACT001")
        audit_data = row.kiwoom_raw_response["data"]
        assert audit_data["token"] == "***REDACTED***"

    async def test_sanitize_response_deep_copies_data(
        self, order_manager, session_factory, kiwoom_client_mock
    ):
        # Caller-mutating original payload after submit MUST NOT change the
        # persisted audit row (Security M1.1).
        original_data = {"ord_no": "DEEP001", "nested": {"key": "v1"}}
        response = V71KiwoomResponse(
            success=True,
            api_id="kt10000",
            data=original_data,
            return_code=0,
            return_msg="OK",
            cont_yn="N",
            next_key="",
            duration_ms=11,
        )
        kiwoom_client_mock.place_buy_order.return_value = response

        await order_manager.submit_order(V71OrderRequest(
            stock_code="005930",
            quantity=10,
            price=73500,
            direction=OrderDirection.BUY,
            trade_type=OrderTradeType.LIMIT,
        ))
        # Mutate original after persistence.
        original_data["nested"]["key"] = "v2"

        row = await _read_order(session_factory, "DEEP001")
        assert row.kiwoom_raw_response["data"]["nested"]["key"] == "v1"
