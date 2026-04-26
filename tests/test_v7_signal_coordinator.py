"""
Phase 3 리팩토링: V7SignalCoordinator 단위 테스트

V7 Dual-Pass 신호 탐지, 알림 전송을 테스트합니다.
"""

import pytest
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.v7_signal_coordinator import (
    V7SignalCoordinator,
    V7Callbacks,
)


def create_mock_stock_info(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
) -> MagicMock:
    """테스트용 StockInfo 객체 생성"""
    info = MagicMock()
    info.stock_code = stock_code
    info.stock_name = stock_name
    info.last_signal_bar = None
    info.can_signal_new_bar = MagicMock(return_value=True)
    info.update_signal_bar = MagicMock()
    return info


def create_mock_pre_check_result(is_candidate: bool = True, conditions_met: int = 4):
    """테스트용 PreCheckResult 생성"""
    result = MagicMock()
    result.is_candidate = is_candidate
    result.conditions_met = conditions_met
    result.conditions = {
        "purple_ok": True,
        "trend": True,
        "zone": True,
        "reabs_start": is_candidate,
        "trigger": False,
    }
    return result


def create_mock_purple_signal(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: int = 72000,
) -> MagicMock:
    """테스트용 PurpleSignal 생성"""
    signal = MagicMock()
    signal.stock_code = stock_code
    signal.stock_name = stock_name
    signal.price = price
    return signal


class TestV7SignalCoordinator:
    """V7SignalCoordinator 기본 테스트"""

    def test_initialization(self):
        """초기화 테스트"""
        coordinator = V7SignalCoordinator()

        assert coordinator._running is False
        assert coordinator._stats["pre_checks"] == 0
        assert coordinator._stats["signals_sent"] == 0

    def test_get_stats(self):
        """통계 조회 테스트"""
        coordinator = V7SignalCoordinator()

        stats = coordinator.get_stats()

        assert "pre_checks" in stats
        assert "confirm_checks" in stats
        assert "signals_sent" in stats
        assert "errors" in stats

    def test_get_status(self):
        """상태 조회 테스트"""
        coordinator = V7SignalCoordinator()

        status = coordinator.get_status()

        assert status["running"] is False
        assert "stats" in status

    def test_str_representation(self):
        """문자열 표현 테스트"""
        coordinator = V7SignalCoordinator()

        s = str(coordinator)

        assert "V7SignalCoordinator" in s
        assert "running=" in s


class TestV7Callbacks:
    """V7Callbacks 테스트"""

    def test_callbacks_default_none(self):
        """콜백 기본값 None 테스트"""
        callbacks = V7Callbacks()

        assert callbacks.get_candles is None
        assert callbacks.send_telegram is None

    def test_callbacks_with_functions(self):
        """콜백 함수 설정 테스트"""
        callbacks = V7Callbacks(
            is_market_open=lambda x: True,
            is_signal_time=lambda x: True,
        )

        assert callbacks.is_market_open(datetime.now()) is True
        assert callbacks.is_signal_time(datetime.now()) is True


class TestEnsureCandleLoaded:
    """ensure_candle_loaded 테스트"""

    @pytest.mark.asyncio
    async def test_already_loaded(self):
        """이미 로딩된 경우 테스트"""
        coordinator = V7SignalCoordinator()

        callbacks = V7Callbacks(
            is_candle_loaded=lambda x: True,
        )

        result = await coordinator.ensure_candle_loaded("005930", callbacks)

        assert result is True

    @pytest.mark.asyncio
    async def test_not_loaded_promote_success(self):
        """로딩 안 된 경우 promote 성공 테스트"""
        coordinator = V7SignalCoordinator()

        async def mock_promote(code):
            return True

        callbacks = V7Callbacks(
            is_candle_loaded=lambda x: False,
            promote_to_tier1=mock_promote,
        )

        result = await coordinator.ensure_candle_loaded("005930", callbacks)

        assert result is True

    @pytest.mark.asyncio
    async def test_timeout(self):
        """타임아웃 테스트"""
        coordinator = V7SignalCoordinator()

        async def slow_promote(code):
            await asyncio.sleep(10)
            return True

        callbacks = V7Callbacks(
            is_candle_loaded=lambda x: False,
            promote_to_tier1=slow_promote,
        )

        result = await coordinator.ensure_candle_loaded(
            "005930", callbacks, timeout=0.1
        )

        assert result is False


class TestSendPurpleSignal:
    """_send_purple_signal 테스트"""

    @pytest.mark.asyncio
    async def test_send_with_queue(self):
        """알림 큐 사용 테스트"""
        coordinator = V7SignalCoordinator()
        enqueued = []

        def mock_enqueue(**kwargs):
            enqueued.append(kwargs)
            return True

        callbacks = V7Callbacks(
            enqueue_notification=mock_enqueue,
        )

        signal = create_mock_purple_signal()

        with patch(
            "src.core.v7_signal_coordinator.generate_signal_summary",
            return_value="테스트 요약"
        ):
            await coordinator._send_purple_signal(signal, callbacks)

        assert len(enqueued) == 1
        assert "005930" in enqueued[0]["message"]

    @pytest.mark.asyncio
    async def test_send_direct_telegram(self):
        """직접 텔레그램 전송 테스트"""
        coordinator = V7SignalCoordinator()
        messages = []

        async def mock_send(msg):
            messages.append(msg)

        callbacks = V7Callbacks(
            enqueue_notification=None,
            send_telegram=mock_send,
        )

        signal = create_mock_purple_signal()

        with patch(
            "src.core.v7_signal_coordinator.generate_signal_summary",
            return_value="테스트 요약"
        ):
            await coordinator._send_purple_signal(signal, callbacks)

        assert len(messages) == 1
        assert "V7 PURPLE" in messages[0]


class TestStartStop:
    """start/stop 테스트"""

    @pytest.mark.asyncio
    async def test_start_creates_tasks(self):
        """start가 태스크를 생성하는지 테스트"""
        coordinator = V7SignalCoordinator()

        # 즉시 종료하도록 콜백 설정
        callbacks = V7Callbacks(
            is_engine_running=lambda: False,
        )

        await coordinator.start(callbacks)

        assert coordinator._running is True
        assert coordinator._dual_pass_task is not None
        assert coordinator._notification_task is not None

        # 정리
        await coordinator.stop()

        assert coordinator._running is False

    @pytest.mark.asyncio
    async def test_stop_cancels_tasks(self):
        """stop이 태스크를 취소하는지 테스트"""
        coordinator = V7SignalCoordinator()

        callbacks = V7Callbacks(
            is_engine_running=lambda: False,
        )

        await coordinator.start(callbacks)
        await asyncio.sleep(0.1)
        await coordinator.stop()

        assert coordinator._running is False


class TestPreCheck:
    """_run_pre_check 테스트"""

    @pytest.mark.asyncio
    async def test_pre_check_empty_pool(self):
        """빈 SignalPool 테스트"""
        coordinator = V7SignalCoordinator()

        callbacks = V7Callbacks(
            get_all_pool_stocks=lambda: [],
        )

        # 오류 없이 완료되어야 함
        await coordinator._run_pre_check(callbacks)

        assert coordinator._stats["pre_checks"] == 0

    @pytest.mark.asyncio
    async def test_pre_check_with_stocks(self):
        """종목이 있는 경우 테스트"""
        coordinator = V7SignalCoordinator()

        stock_info = create_mock_stock_info()
        mock_dual_pass = MagicMock()
        mock_dual_pass.run_pre_check_single.return_value = create_mock_pre_check_result()

        import pandas as pd
        mock_df = pd.DataFrame({"close": [1000] * 100})

        callbacks = V7Callbacks(
            get_all_pool_stocks=lambda: [stock_info],
            get_candles=lambda code, tf: mock_df,
            get_dual_pass=lambda: mock_dual_pass,
        )

        await coordinator._run_pre_check(callbacks)

        assert coordinator._stats["pre_checks"] == 1


class TestStats:
    """통계 테스트"""

    def test_stats_update_on_signal(self):
        """신호 발생 시 통계 업데이트 테스트"""
        coordinator = V7SignalCoordinator()

        # 수동으로 통계 업데이트
        coordinator._stats["signals_sent"] += 1

        stats = coordinator.get_stats()
        assert stats["signals_sent"] == 1

    def test_stats_copy_returned(self):
        """통계가 복사본으로 반환되는지 테스트"""
        coordinator = V7SignalCoordinator()

        stats = coordinator.get_stats()
        stats["signals_sent"] = 999

        # 원본은 변경되지 않아야 함
        assert coordinator._stats["signals_sent"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
