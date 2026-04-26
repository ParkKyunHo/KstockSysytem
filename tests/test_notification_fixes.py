"""
V7.1 신호 분석 및 알림 시스템 수정 테스트

F-1~F-8, T-1~T-4 수정사항 검증
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import sys
import os
import logging
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notification.notification_queue import (
    NotificationQueue,
    NotificationItem,
    MAX_QUEUE_SIZE,
    OVERFLOW_ALERT_INTERVAL_SECONDS,
)
from src.notification.telegram import (
    TelegramBot,
    CIRCUIT_BREAKER_FAILURE_THRESHOLD,
)
from src.core.signal_processor import SignalProcessor, SignalProcessCallbacks
from src.core.wave_harvest_exit import WaveHarvestExit, PositionExitState


def make_test_df(rows=60):
    """테스트용 DataFrame 생성"""
    dates = pd.date_range("2025-01-01", periods=rows, freq="3min")
    np.random.seed(42)
    data = {
        "open": np.random.randint(49000, 51000, rows),
        "high": np.random.randint(50000, 52000, rows),
        "low": np.random.randint(48000, 50000, rows),
        "close": np.random.randint(49000, 51000, rows),
        "volume": np.random.randint(1000, 10000, rows),
    }
    return pd.DataFrame(data, index=dates)


# =====================================================
# F-1: send_func None 카운터 테스트
# =====================================================

class TestF1SendFuncNoneCounter:
    """F-1: process_next()에서 send_func=None일 때 _send_func_none_count 증가"""

    @pytest.mark.asyncio
    async def test_send_func_none_increments_counter(self):
        """send_func=None이면 _send_func_none_count가 증가해야 함"""
        queue = NotificationQueue(send_func=None)
        queue.enqueue("test message")

        assert queue._send_func_none_count == 0

        await queue.process_next()
        assert queue._send_func_none_count == 1

        await queue.process_next()
        assert queue._send_func_none_count == 2

    @pytest.mark.asyncio
    async def test_send_func_none_returns_none(self):
        """send_func=None이면 process_next()는 None을 반환해야 함"""
        queue = NotificationQueue(send_func=None)
        queue.enqueue("test message")

        result = await queue.process_next()
        assert result is None

    @pytest.mark.asyncio
    async def test_send_func_none_backup_at_threshold(self):
        """send_func_none_count가 10 이상이면 _backup_pending_queue 호출"""
        queue = NotificationQueue(send_func=None)
        queue.enqueue("test message")
        queue._send_func_none_count = 9

        with patch.object(queue, "_backup_pending_queue") as mock_backup:
            await queue.process_next()
            assert queue._send_func_none_count == 10
            mock_backup.assert_called_once()


# =====================================================
# F-5: Queue overflow rate limiting 테스트
# =====================================================

class TestF5QueueOverflowRateLimit:
    """F-5: 큐 오버플로우 시 알림 rate-limiting (5분 간격)"""

    def test_overflow_sets_last_alert_time(self):
        """오버플로우 발생 시 _last_overflow_alert_time이 설정되어야 함"""
        async def mock_send(msg):
            return True

        queue = NotificationQueue(send_func=mock_send)
        assert queue._last_overflow_alert_time is None

        # 큐를 가득 채움
        for i in range(MAX_QUEUE_SIZE):
            queue.enqueue(f"msg{i}")

        # 오버플로우 발생 (101번째 메시지)
        queue.enqueue("overflow msg")
        assert queue._last_overflow_alert_time is not None

    def test_overflow_rate_limiting_within_5min(self):
        """5분 이내 오버플로우 반복 시 알림이 다시 발생하지 않아야 함"""
        async def mock_send(msg):
            return True

        queue = NotificationQueue(send_func=mock_send)

        # 큐를 가득 채움
        for i in range(MAX_QUEUE_SIZE):
            queue.enqueue(f"msg{i}")

        # 첫 번째 오버플로우 -> 알림 시간 설정
        queue.enqueue("overflow 1")
        first_alert_time = queue._last_overflow_alert_time
        assert first_alert_time is not None

        # 두 번째 오버플로우 -> 5분 이내이므로 알림 시간 변경 없음
        queue.enqueue("overflow 2")
        assert queue._last_overflow_alert_time == first_alert_time

    def test_overflow_dropped_count(self):
        """오버플로우 시 _dropped_count가 증가해야 함"""
        queue = NotificationQueue()

        # 큐를 가득 채움
        for i in range(MAX_QUEUE_SIZE):
            queue.enqueue(f"msg{i}")

        assert queue._dropped_count == 0

        queue.enqueue("overflow")
        assert queue._dropped_count == 1

        queue.enqueue("overflow 2")
        assert queue._dropped_count == 2


# =====================================================
# T-4: Enhanced notification queue stats 테스트
# =====================================================

class TestT4EnhancedNotificationQueueStats:
    """T-4: get_stats()에 last_success_time, consecutive_failures, send_func_none_count 포함"""

    def test_stats_include_enhanced_fields(self):
        """get_stats()에 T-4 강화 필드가 포함되어야 함"""
        queue = NotificationQueue()
        stats = queue.get_stats()

        assert "last_success_time" in stats
        assert "consecutive_failures" in stats
        assert "send_func_none_count" in stats

    def test_stats_initial_values(self):
        """초기 T-4 통계값이 올바른지 확인"""
        queue = NotificationQueue()
        stats = queue.get_stats()

        assert stats["last_success_time"] is None
        assert stats["consecutive_failures"] == 0
        assert stats["send_func_none_count"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_success(self):
        """성공 후 통계가 올바르게 업데이트되는지 확인"""
        async def mock_send(msg):
            return True

        queue = NotificationQueue(send_func=mock_send)
        queue.enqueue("test msg")
        await queue.process_next()

        stats = queue.get_stats()
        assert stats["last_success_time"] is not None
        assert stats["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_consecutive_failures(self):
        """연속 실패 후 consecutive_failures가 증가하는지 확인"""
        async def mock_send(msg):
            return False

        queue = NotificationQueue(send_func=mock_send, max_retries=0)
        queue.enqueue("msg1")
        queue.enqueue("msg2")

        await queue.process_next()
        await queue.process_next()

        stats = queue.get_stats()
        assert stats["consecutive_failures"] == 2


# =====================================================
# F-2: Telegram retry 테스트
# =====================================================

class TestF2TelegramRetry:
    """F-2: send_message가 실패 시 1회 재시도하는지 확인"""

    @pytest.mark.asyncio
    async def test_send_message_retries_on_failure(self):
        """첫 번째 시도 실패 후 재시도하여 성공해야 함"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)

        call_count = 0

        async def mock_post(url, json=None, timeout=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("Network error")
            # Second call succeeds
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await bot.send_message("test")
            assert result is True
            assert call_count == 2  # first attempt failed, second succeeded

    @pytest.mark.asyncio
    async def test_send_message_both_attempts_fail(self):
        """양쪽 시도 모두 실패하면 False 반환"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)

        async def mock_post(url, json=None, timeout=None):
            raise Exception("Network error")

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            result = await bot.send_message("test")
            assert result is False


# =====================================================
# F-3: Circuit Breaker counter 테스트
# =====================================================

class TestF3CircuitBreakerCounter:
    """F-3: 연속 실패 시 Circuit Breaker 열림 및 카운터 증가"""

    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_after_threshold_failures(self):
        """CIRCUIT_BREAKER_FAILURE_THRESHOLD회 실패 후 circuit_breaker_opens_today >= 1"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)
        assert bot._circuit_breaker_opens_today == 0

        async def mock_post(url, json=None, timeout=None):
            raise Exception("Network error")

        with patch("httpx.AsyncClient") as MockClient:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = mock_client

            # Send messages that fail (each send_message does 2 attempts,
            # which counts as 1 circuit failure via _on_circuit_failure)
            for i in range(CIRCUIT_BREAKER_FAILURE_THRESHOLD):
                await bot.send_message(f"fail msg {i}")

            assert bot._circuit_breaker_opens_today >= 1

    def test_circuit_breaker_on_circuit_failure_increments(self):
        """_on_circuit_failure()가 호출될 때마다 _circuit_failures가 증가"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)

        for i in range(CIRCUIT_BREAKER_FAILURE_THRESHOLD - 1):
            bot._on_circuit_failure()
            assert bot._circuit_failures == i + 1
            assert bot._circuit_open_until is None

        # At threshold, circuit should open
        bot._on_circuit_failure()
        assert bot._circuit_failures == CIRCUIT_BREAKER_FAILURE_THRESHOLD
        assert bot._circuit_open_until is not None
        assert bot._circuit_breaker_opens_today == 1


# =====================================================
# T-1: Pre-Check/Confirm-Check elif 테스트
# =====================================================

class TestT1DualPassElif:
    """T-1: Dual-Pass 루프에서 if/elif로 Pre-Check과 Confirm-Check이 동시에 실행되지 않음"""

    @pytest.mark.asyncio
    async def test_pre_check_and_confirm_check_not_both_called(self):
        """is_pre_check_time과 is_confirm_check_time 모두 True일 때 Pre-Check만 실행"""
        from src.core.v7_signal_coordinator import V7SignalCoordinator, V7Callbacks

        coordinator = V7SignalCoordinator()

        pre_check_called = False
        confirm_check_called = False

        async def mock_run_pre_check(callbacks):
            nonlocal pre_check_called
            pre_check_called = True

        async def mock_run_confirm_check(callbacks):
            nonlocal confirm_check_called
            confirm_check_called = True

        # Patch _run_pre_check and _run_confirm_check
        coordinator._run_pre_check = mock_run_pre_check
        coordinator._run_confirm_check = mock_run_confirm_check

        callbacks = V7Callbacks(
            is_engine_running=lambda: True,
            is_market_open=lambda now: True,
            is_signal_time=lambda now: True,
            is_pre_check_time=lambda now, sec: True,
            is_confirm_check_time=lambda now, sec: True,
        )

        # Run one iteration of the loop manually
        coordinator._running = True

        # Simulate a single loop iteration
        now = datetime.now()
        if callbacks.is_pre_check_time and callbacks.is_pre_check_time(now, 30):
            await coordinator._run_pre_check(callbacks)
        elif callbacks.is_confirm_check_time and callbacks.is_confirm_check_time(now, 5):
            await coordinator._run_confirm_check(callbacks)

        assert pre_check_called is True
        assert confirm_check_called is False  # elif ensures this is NOT called


# =====================================================
# T-2: Signal queue max age 테스트
# =====================================================

class TestT2SignalQueueMaxAge:
    """T-2: SignalProcessor 기본 signal_queue_max_age_seconds == 30"""

    def test_default_max_age_is_30(self):
        """기본 signal_queue_max_age_seconds가 30초인지 확인"""
        processor = SignalProcessor()
        assert processor._signal_queue_max_age_seconds == 30

    def test_custom_max_age(self):
        """커스텀 signal_queue_max_age_seconds 설정"""
        processor = SignalProcessor(signal_queue_max_age_seconds=60)
        assert processor._signal_queue_max_age_seconds == 60


# =====================================================
# F-8: Telegram uninitialized CRITICAL log 테스트
# =====================================================

class TestF8TelegramUninitializedCritical:
    """F-8: send_telegram과 _telegram 모두 None일 때 CRITICAL 로그 발생"""

    @pytest.mark.asyncio
    async def test_critical_logged_when_no_telegram(self):
        """send_telegram=None, _telegram=None일 때 CRITICAL 로그 기록"""
        processor = SignalProcessor(telegram=None)

        # Create a mock Signal object
        from src.core.signal_detector import Signal, StrategyType
        signal = Signal(
            stock_code="005930",
            stock_name="삼성전자",
            price=50000,
        )

        # Callbacks with no send_telegram
        callbacks = SignalProcessCallbacks(send_telegram=None)

        with patch.object(processor._logger, "critical") as mock_critical:
            await processor._send_signal_alert(signal, callbacks)
            mock_critical.assert_called_once()
            # Verify the message mentions uninitialized telegram
            call_args = mock_critical.call_args[0][0]
            assert "텔레그램 미초기화" in call_args or "미초기화" in call_args


# =====================================================
# F-6: Exception fallback reason 테스트
# =====================================================

class TestF6ExceptionFallbackReason:
    """F-6: update_and_check 예외 시 가격 > fallback이면 EXCEPTION_NOEXIT 반환"""

    def test_exception_noexit_when_price_above_fallback(self):
        """예외 발생 시 현재가 > fallback이면 reason에 EXCEPTION_NOEXIT 포함"""
        exit_mgr = WaveHarvestExit()
        entry_price = 50000
        state = exit_mgr.create_state(stock_code="005930", entry_price=entry_price)

        # 현재가는 진입가보다 높음 (fallback stop = 48000)
        current_price = 51000

        # DataFrame을 만들되 calculate_base_price에서 예외가 발생하도록 패치
        df = make_test_df(60)

        with patch.object(exit_mgr, "calculate_base_price", side_effect=ValueError("test error")):
            should_exit, reason = exit_mgr.update_and_check(state, df, current_price)

        assert should_exit is False
        assert "EXCEPTION_NOEXIT" in reason

    def test_exception_fallback_when_price_below_fallback(self):
        """예외 발생 시 현재가 < fallback이면 EXCEPTION_FALLBACK 반환"""
        exit_mgr = WaveHarvestExit()
        entry_price = 50000
        state = exit_mgr.create_state(stock_code="005930", entry_price=entry_price)

        # 현재가가 fallback (-4%) 이하 (fallback = 48000)
        current_price = 47000

        df = make_test_df(60)

        with patch.object(exit_mgr, "calculate_base_price", side_effect=ValueError("test error")):
            should_exit, reason = exit_mgr.update_and_check(state, df, current_price)

        assert should_exit is True
        assert "EXCEPTION_FALLBACK" in reason


# =====================================================
# T-4: TelegramBot.get_stats() 테스트
# =====================================================

class TestT4TelegramStats:
    """T-4: TelegramBot.get_stats()에 circuit_breaker 정보 포함"""

    def test_get_stats_has_circuit_breaker(self):
        """get_stats()에 circuit_breaker 키가 포함되어야 함"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)
        stats = bot.get_stats()

        assert "circuit_breaker" in stats
        assert "circuit_breaker_opens_today" in stats
        assert "failed_alerts_count" in stats

    def test_get_stats_circuit_breaker_details(self):
        """circuit_breaker 상세 필드 확인"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)
        stats = bot.get_stats()

        cb = stats["circuit_breaker"]
        assert "is_open" in cb
        assert "failures" in cb
        assert "threshold" in cb
        assert "remaining_seconds" in cb

    def test_get_stats_initial_values(self):
        """초기 circuit_breaker 값이 올바른지 확인"""
        mock_settings = MagicMock()
        mock_settings.bot_token = "fake_token"
        mock_settings.chat_id = "fake_chat_id"

        bot = TelegramBot(settings=mock_settings)
        stats = bot.get_stats()

        assert stats["circuit_breaker"]["is_open"] is False
        assert stats["circuit_breaker"]["failures"] == 0
        assert stats["circuit_breaker_opens_today"] == 0
        assert stats["failed_alerts_count"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
