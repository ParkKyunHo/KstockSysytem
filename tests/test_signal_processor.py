"""
Phase 3 리팩토링: SignalProcessor 단위 테스트

신호 처리기의 큐 관리, 알림 전송, 신호 유효성 검증을 검증합니다.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.signal_processor import (
    SignalProcessor,
    SignalProcessResult,
    SignalProcessCallbacks,
    QueuedSignal,
)
from src.core.signal_detector import Signal, SignalType, StrategyType
from src.core.candle_builder import Timeframe


def create_mock_signal(
    stock_code: str = "005930",
    stock_name: str = "삼성전자",
    price: int = 50000,
    strategy: StrategyType = StrategyType.SNIPER_TRAP,
) -> Signal:
    """테스트용 Signal 객체 생성"""
    return Signal(
        stock_code=stock_code,
        stock_name=stock_name,
        signal_type=SignalType.BUY,
        strategy=strategy,
        price=price,
        reason="테스트 신호",
        timestamp=datetime.now(),
        timeframe=Timeframe.M3,
    )


class TestSignalProcessor:
    """SignalProcessor 테스트"""

    def test_initialization(self):
        """초기화 테스트"""
        processor = SignalProcessor()

        assert processor.get_queue_size() == 0
        assert processor._signal_alert_cooldown_seconds == 300
        assert processor._signal_queue_max_age_seconds == 15

    def test_initialization_with_params(self):
        """커스텀 파라미터 초기화 테스트"""
        processor = SignalProcessor(
            signal_queue_max_age_seconds=30,
            signal_alert_cooldown_seconds=600,
        )

        assert processor._signal_queue_max_age_seconds == 30
        assert processor._signal_alert_cooldown_seconds == 600


class TestSignalProcessCallbacks:
    """SignalProcessCallbacks 테스트"""

    def test_callbacks_default_none(self):
        """콜백 기본값 None 테스트"""
        callbacks = SignalProcessCallbacks()

        assert callbacks.can_execute_trade is None
        assert callbacks.has_position is None
        assert callbacks.is_in_cooldown is None
        assert callbacks.execute_buy is None

    def test_callbacks_with_functions(self):
        """콜백 함수 설정 테스트"""
        callbacks = SignalProcessCallbacks(
            can_execute_trade=lambda x: True,
            has_position=lambda x: False,
        )

        assert callbacks.can_execute_trade("005930") is True
        assert callbacks.has_position("005930") is False


class TestQueuedSignal:
    """QueuedSignal 테스트"""

    def test_queued_signal_creation(self):
        """QueuedSignal 생성 테스트"""
        signal = create_mock_signal()
        queued = QueuedSignal(
            stock_code="005930",
            stock_name="삼성전자",
            signal=signal,
            price=50000,
        )

        assert queued.stock_code == "005930"
        assert queued.stock_name == "삼성전자"
        assert queued.price == 50000
        assert queued.timestamp is not None

    def test_queued_signal_age(self):
        """QueuedSignal 대기 시간 테스트"""
        signal = create_mock_signal()
        queued = QueuedSignal(
            stock_code="005930",
            stock_name="삼성전자",
            signal=signal,
            price=50000,
            timestamp=datetime.now() - timedelta(seconds=5),
        )

        age = queued.age_seconds()
        assert 4.9 <= age <= 5.5  # 약간의 오차 허용


class TestProcessSignal:
    """process_signal 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_process_signal_blocked_when_cannot_execute(self):
        """매매 불가 시 차단 테스트"""
        processor = SignalProcessor()
        signal = create_mock_signal()

        callbacks = SignalProcessCallbacks(
            can_execute_trade=AsyncMock(return_value=False),
        )

        result = await processor.process_signal(signal, callbacks)

        assert result == SignalProcessResult.BLOCKED
        assert processor._stats["signals_blocked"] == 1

    @pytest.mark.asyncio
    async def test_process_signal_alert_mode_skips_existing_position(self):
        """SIGNAL_ALERT 모드 - 이미 보유 중이면 스킵"""
        processor = SignalProcessor()
        signal = create_mock_signal()

        callbacks = SignalProcessCallbacks(
            can_execute_trade=AsyncMock(return_value=True),
            has_position=lambda x: True,  # 이미 보유 중
        )

        result = await processor.process_signal(
            signal, callbacks, trading_mode="SIGNAL_ALERT"
        )

        assert result == SignalProcessResult.SKIPPED

    @pytest.mark.asyncio
    async def test_process_signal_alert_mode_sends_alert(self):
        """SIGNAL_ALERT 모드 - 알림 전송 테스트"""
        mock_telegram = AsyncMock()
        processor = SignalProcessor(telegram=mock_telegram)
        signal = create_mock_signal()

        callbacks = SignalProcessCallbacks(
            can_execute_trade=AsyncMock(return_value=True),
            has_position=lambda x: False,
        )

        result = await processor.process_signal(
            signal, callbacks, trading_mode="SIGNAL_ALERT"
        )

        assert result == SignalProcessResult.ALERT_SENT
        assert processor._stats["signal_alerts_sent"] == 1
        mock_telegram.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_process_signal_queued_during_cooldown(self):
        """쿨다운 중 신호 큐잉 테스트"""
        processor = SignalProcessor()
        signal = create_mock_signal()

        callbacks = SignalProcessCallbacks(
            can_execute_trade=AsyncMock(return_value=True),
            has_position=lambda x: False,
            is_in_cooldown=lambda: True,
            get_cooldown_remaining=lambda: 10.0,
        )

        result = await processor.process_signal(
            signal, callbacks, trading_mode="AUTO_TRADE"
        )

        assert result == SignalProcessResult.QUEUED
        assert processor.get_queue_size() == 1
        assert processor._stats["signals_queued"] == 1

    @pytest.mark.asyncio
    async def test_process_signal_executed(self):
        """정상 매수 실행 테스트"""
        processor = SignalProcessor()
        signal = create_mock_signal()
        execute_buy_called = False

        async def mock_execute_buy(s):
            nonlocal execute_buy_called
            execute_buy_called = True

        callbacks = SignalProcessCallbacks(
            can_execute_trade=AsyncMock(return_value=True),
            has_position=lambda x: False,
            is_in_cooldown=lambda: False,
            can_enter_risk=lambda x: (True, None, "OK"),
            execute_buy=mock_execute_buy,
        )

        result = await processor.process_signal(
            signal, callbacks, trading_mode="AUTO_TRADE"
        )

        assert result == SignalProcessResult.EXECUTED
        assert execute_buy_called is True


class TestSignalAlertCooldown:
    """SIGNAL_ALERT 쿨다운 테스트"""

    @pytest.mark.asyncio
    async def test_duplicate_alert_blocked_by_cooldown(self):
        """중복 알림 쿨다운 테스트"""
        mock_telegram = AsyncMock()
        processor = SignalProcessor(
            telegram=mock_telegram,
            signal_alert_cooldown_seconds=300,
        )
        signal = create_mock_signal()

        callbacks = SignalProcessCallbacks(
            can_execute_trade=AsyncMock(return_value=True),
            has_position=lambda x: False,
        )

        # 첫 번째 알림
        result1 = await processor.process_signal(
            signal, callbacks, trading_mode="SIGNAL_ALERT"
        )
        assert result1 == SignalProcessResult.ALERT_SENT
        assert mock_telegram.send_message.call_count == 1

        # 두 번째 알림 (쿨다운 중)
        result2 = await processor.process_signal(
            signal, callbacks, trading_mode="SIGNAL_ALERT"
        )
        # 쿨다운 중에도 ALERT_SENT 반환 (실제 전송은 스킵됨)
        assert mock_telegram.send_message.call_count == 1  # 호출 횟수 증가 안 함

    def test_clear_alert_cooldown_single(self):
        """단일 종목 쿨다운 초기화 테스트"""
        processor = SignalProcessor()
        processor._signal_alert_cooldown["005930"] = datetime.now()
        processor._signal_alert_cooldown["000660"] = datetime.now()

        processor.clear_alert_cooldown("005930")

        assert "005930" not in processor._signal_alert_cooldown
        assert "000660" in processor._signal_alert_cooldown

    def test_clear_alert_cooldown_all(self):
        """전체 쿨다운 초기화 테스트"""
        processor = SignalProcessor()
        processor._signal_alert_cooldown["005930"] = datetime.now()
        processor._signal_alert_cooldown["000660"] = datetime.now()

        processor.clear_alert_cooldown()

        assert len(processor._signal_alert_cooldown) == 0


class TestSignalQueue:
    """신호 큐 관리 테스트"""

    @pytest.mark.asyncio
    async def test_enqueue_replaces_existing(self):
        """같은 종목 신호 교체 테스트"""
        processor = SignalProcessor()
        signal1 = create_mock_signal(price=50000)
        signal2 = create_mock_signal(price=51000)

        await processor._enqueue_signal("005930", "삼성전자", signal1, 50000)
        await processor._enqueue_signal("005930", "삼성전자", signal2, 51000)

        assert processor.get_queue_size() == 1
        assert processor._signal_queue["005930"].price == 51000

    @pytest.mark.asyncio
    async def test_process_queue_expires_old_signals(self):
        """만료된 신호 폐기 테스트"""
        processor = SignalProcessor(signal_queue_max_age_seconds=5)
        signal = create_mock_signal()

        # 오래된 신호 직접 추가
        processor._signal_queue["005930"] = QueuedSignal(
            stock_code="005930",
            stock_name="삼성전자",
            signal=signal,
            price=50000,
            timestamp=datetime.now() - timedelta(seconds=10),  # 10초 전
        )

        callbacks = SignalProcessCallbacks(
            has_position=lambda x: False,
            is_in_cooldown=lambda: False,
        )

        await processor.process_queue(callbacks)

        assert processor.get_queue_size() == 0
        assert processor._stats["signals_expired"] == 1

    @pytest.mark.asyncio
    async def test_process_queue_skips_existing_position(self):
        """보유 중인 종목 신호 스킵 테스트"""
        processor = SignalProcessor()
        signal = create_mock_signal()

        await processor._enqueue_signal("005930", "삼성전자", signal, 50000)

        callbacks = SignalProcessCallbacks(
            has_position=lambda x: True,  # 이미 보유 중
            is_in_cooldown=lambda: False,
        )

        await processor.process_queue(callbacks)

        assert processor.get_queue_size() == 0  # 큐에서 제거됨

    @pytest.mark.asyncio
    async def test_process_queue_executes_valid_signal(self):
        """유효한 신호 실행 테스트"""
        processor = SignalProcessor()
        signal = create_mock_signal()
        executed_codes = []

        async def mock_execute_buy(s):
            executed_codes.append(s.stock_code)

        await processor._enqueue_signal("005930", "삼성전자", signal, 50000)

        callbacks = SignalProcessCallbacks(
            has_position=lambda x: False,
            is_in_cooldown=lambda: False,
            can_enter_risk=lambda x: (True, None, "OK"),
            execute_buy=mock_execute_buy,
        )

        result = await processor.process_queue(callbacks)

        assert result == "005930"
        assert "005930" in executed_codes
        assert processor._stats["signals_from_queue"] == 1


class TestStatus:
    """상태 조회 테스트"""

    def test_get_status(self):
        """상태 조회 테스트"""
        processor = SignalProcessor(
            signal_queue_max_age_seconds=20,
            signal_alert_cooldown_seconds=400,
        )

        status = processor.get_status()

        assert status["queue_size"] == 0
        assert status["alert_cooldown_count"] == 0
        assert status["max_queue_age_seconds"] == 20
        assert status["alert_cooldown_seconds"] == 400
        assert "stats" in status

    def test_get_stats(self):
        """통계 조회 테스트"""
        processor = SignalProcessor()

        stats = processor.get_stats()

        assert "signals_processed" in stats
        assert "signals_queued" in stats
        assert "signal_alerts_sent" in stats

    def test_str_representation(self):
        """문자열 표현 테스트"""
        processor = SignalProcessor()

        s = str(processor)

        assert "SignalProcessor" in s
        assert "queue=" in s
        assert "alerts=" in s


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
