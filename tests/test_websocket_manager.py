"""
WebSocketManager 단위 테스트 (Phase 4-A)

WebSocket 연결/구독/이벤트 핸들링을 검증합니다.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from src.core.websocket_manager import WebSocketManager, WebSocketCallbacks


def _make_callbacks(**overrides) -> WebSocketCallbacks:
    """테스트용 WebSocketCallbacks 생성"""
    defaults = dict(
        on_tick=AsyncMock(),
        sync_positions=AsyncMock(),
        initialize_trailing_stops=AsyncMock(),
        get_universe_codes=MagicMock(return_value={"005930", "000660"}),
        get_all_position_codes=MagicMock(return_value={"035720"}),
        get_position_count=MagicMock(return_value=1),
        get_engine_state=MagicMock(return_value="RUNNING"),
        set_engine_paused=MagicMock(),
    )
    defaults.update(overrides)
    return WebSocketCallbacks(**defaults)


def _make_manager(websocket=None, **kwargs) -> WebSocketManager:
    """테스트용 WebSocketManager 생성"""
    ws = websocket or MagicMock()
    callbacks = kwargs.pop("callbacks", _make_callbacks())
    return WebSocketManager(
        websocket=ws,
        logger=MagicMock(),
        telegram=AsyncMock(),
        risk_settings=MagicMock(),
        subscription_manager=MagicMock(),
        callbacks=callbacks,
    )


class TestWebSocketManagerConnect:
    """연결 및 조건검색 구독 테스트"""

    @pytest.mark.asyncio
    async def test_connect_skips_without_websocket(self):
        mgr = _make_manager(websocket=None)
        mgr._websocket = None
        await mgr.connect()
        # No error - just logs and returns

    @pytest.mark.asyncio
    async def test_connect_logs_failure(self):
        ws = AsyncMock()
        ws.connect = AsyncMock(return_value=False)
        ws.is_connected = False
        mgr = _make_manager(websocket=ws)
        await mgr.connect()
        mgr._logger.error.assert_called()

    @pytest.mark.asyncio
    async def test_connect_success_auto_universe(self):
        from src.utils.config import TradingMode

        ws = AsyncMock()
        ws.connect = AsyncMock(return_value=True)
        ws.is_connected = True
        ws.get_condition_list = AsyncMock(return_value=[
            MagicMock(seq="1", name="Test Condition"),
        ])
        ws.start_condition_search = AsyncMock(return_value=True)

        mgr = _make_manager(websocket=ws)
        mgr._risk_settings.auto_universe_enabled = True
        mgr._risk_settings.auto_universe_condition_seq = "1"
        mgr._risk_settings.atr_alert_condition_seq = "2"
        mgr._risk_settings.trading_mode = TradingMode.SIGNAL_ALERT

        await mgr.connect()

        # Verify condition search was attempted
        assert ws.get_condition_list.called


class TestWebSocketManagerConditionSearch:
    """조건검색 유효성 검증 테스트"""

    @pytest.mark.asyncio
    async def test_condition_search_success(self):
        ws = AsyncMock()
        ws.get_condition_list = AsyncMock(return_value=[
            MagicMock(seq="1", name="V7 Purple"),
        ])
        ws.start_condition_search = AsyncMock(return_value=True)

        mgr = _make_manager(websocket=ws)
        result = await mgr._start_condition_search_with_validation("1")
        assert result is True

    @pytest.mark.asyncio
    async def test_condition_search_not_found(self):
        ws = AsyncMock()
        ws.get_condition_list = AsyncMock(return_value=[
            MagicMock(seq="2", name="Other"),
        ])

        mgr = _make_manager(websocket=ws)
        result = await mgr._start_condition_search_with_validation("1")
        assert result is False

    @pytest.mark.asyncio
    async def test_condition_search_server_reject(self):
        ws = AsyncMock()
        ws.get_condition_list = AsyncMock(return_value=[
            MagicMock(seq="1", name="V7 Purple"),
        ])
        ws.start_condition_search = AsyncMock(return_value=False)

        mgr = _make_manager(websocket=ws)
        result = await mgr._start_condition_search_with_validation("1")
        assert result is False

    @pytest.mark.asyncio
    async def test_condition_search_exception(self):
        ws = AsyncMock()
        ws.get_condition_list = AsyncMock(side_effect=Exception("Network error"))

        mgr = _make_manager(websocket=ws)
        result = await mgr._start_condition_search_with_validation("1")
        assert result is False


class TestWebSocketEventHandlers:
    """WebSocket 이벤트 핸들러 테스트"""

    @pytest.mark.asyncio
    async def test_on_tick_converts_and_dispatches(self):
        callbacks = _make_callbacks()
        mgr = _make_manager(callbacks=callbacks)

        tick_data = MagicMock()
        tick_data.stock_code = "005930"
        tick_data.price = 70000
        tick_data.volume = 100
        tick_data.time = "093000"

        await mgr.on_tick(tick_data)

        assert mgr._ticks_received == 1
        callbacks.on_tick.assert_called_once()
        tick = callbacks.on_tick.call_args[0][0]
        assert tick.stock_code == "005930"
        assert tick.price == 70000

    @pytest.mark.asyncio
    async def test_on_tick_handles_invalid_time(self):
        callbacks = _make_callbacks()
        mgr = _make_manager(callbacks=callbacks)

        tick_data = MagicMock()
        tick_data.stock_code = "005930"
        tick_data.price = 70000
        tick_data.volume = 100
        tick_data.time = "INVALID"

        await mgr.on_tick(tick_data)
        callbacks.on_tick.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_connected_logs(self):
        mgr = _make_manager()
        await mgr.on_connected()
        mgr._logger.info.assert_called()

    @pytest.mark.asyncio
    async def test_on_disconnected_skips_during_reconnect(self):
        ws = MagicMock()
        ws._is_reconnecting = True
        mgr = _make_manager(websocket=ws)

        await mgr.on_disconnected()
        mgr._telegram.send_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_on_disconnected_sends_alert(self):
        ws = MagicMock(spec=[])  # No _is_reconnecting attribute
        mgr = _make_manager(websocket=ws)

        await mgr.on_disconnected()
        mgr._telegram.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_reconnected_full_recovery(self):
        callbacks = _make_callbacks()
        mgr = _make_manager(callbacks=callbacks)

        await mgr.on_reconnected()

        # subscription manager re-subscribe
        mgr._subscription_manager.on_websocket_reconnected.assert_called_once()
        # position sync
        callbacks.sync_positions.assert_called_once()
        # trailing stops
        callbacks.initialize_trailing_stops.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_reconnect_failed_pauses_engine(self):
        callbacks = _make_callbacks(get_engine_state=MagicMock(return_value="RUNNING"))
        mgr = _make_manager(callbacks=callbacks)

        await mgr.on_reconnect_failed(attempts=5)

        callbacks.set_engine_paused.assert_called_once()
        mgr._telegram.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_reconnect_failed_no_pause_if_not_running(self):
        callbacks = _make_callbacks(get_engine_state=MagicMock(return_value="PAUSED"))
        mgr = _make_manager(callbacks=callbacks)

        await mgr.on_reconnect_failed(attempts=5)

        callbacks.set_engine_paused.assert_not_called()
