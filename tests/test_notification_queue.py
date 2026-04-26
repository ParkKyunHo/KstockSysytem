"""
Phase 5: notification_queue.py 단위 테스트 (V7.0)

알림 큐의 재시도, 쿨다운, 큐 관리 기능을 검증합니다.
"""

import pytest
import asyncio
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.notification.notification_queue import (
    NotificationQueue,
    NotificationItem,
    MAX_RETRIES,
)


class TestNotificationItem:
    """NotificationItem 테스트"""

    def test_item_creation(self):
        """아이템 생성 테스트"""
        item = NotificationItem(
            message="테스트 메시지",
            stock_code="005930",
            stock_name="삼성전자",
        )

        assert item.message == "테스트 메시지"
        assert item.stock_code == "005930"
        assert item.stock_name == "삼성전자"
        assert item.retry_count == 0
        assert item.priority == 1

    def test_item_age(self):
        """아이템 경과 시간 테스트"""
        item = NotificationItem(message="테스트")

        # 즉시 확인하면 거의 0초
        assert item.age_seconds < 1

    def test_item_with_metadata(self):
        """메타데이터 포함 테스트"""
        item = NotificationItem(
            message="테스트",
            metadata={"price": 50000, "change": 5.2}
        )

        assert item.metadata["price"] == 50000
        assert item.metadata["change"] == 5.2


class TestNotificationQueue:
    """NotificationQueue 테스트"""

    def test_enqueue(self):
        """큐 추가 테스트"""
        queue = NotificationQueue()

        result = queue.enqueue("테스트 메시지")
        assert result is True
        assert queue.pending_count() == 1

    def test_enqueue_with_stock_code(self):
        """종목 코드 포함 추가 테스트"""
        queue = NotificationQueue()

        queue.enqueue("신호 발생", stock_code="005930", stock_name="삼성전자")
        assert queue.pending_count() == 1

    def test_enqueue_cooldown(self):
        """쿨다운 테스트"""
        queue = NotificationQueue(cooldown_seconds=300)

        # 첫 번째 알림
        result1 = queue.enqueue("알림1", stock_code="005930")
        assert result1 is True

        # 같은 종목 두 번째 알림 -> 쿨다운 중
        result2 = queue.enqueue("알림2", stock_code="005930")
        assert result2 is False

        # force=True로 강제 추가
        result3 = queue.enqueue("알림3", stock_code="005930", force=True)
        assert result3 is True

    def test_enqueue_different_stocks(self):
        """다른 종목 알림 테스트"""
        queue = NotificationQueue(cooldown_seconds=300)

        queue.enqueue("알림1", stock_code="005930")
        result = queue.enqueue("알림2", stock_code="000660")  # 다른 종목

        assert result is True
        assert queue.pending_count() == 2

    def test_enqueue_priority(self):
        """우선순위 테스트"""
        queue = NotificationQueue()

        queue.enqueue("일반 메시지", priority=1)
        queue.enqueue("긴급 메시지", priority=0)  # 앞에 삽입

        # 긴급 메시지가 먼저 처리됨
        assert queue.pending_count() == 2

    def test_pending_count(self):
        """대기 개수 테스트"""
        queue = NotificationQueue()

        assert queue.pending_count() == 0
        queue.enqueue("메시지1")
        queue.enqueue("메시지2")
        assert queue.pending_count() == 2

    def test_is_empty(self):
        """빈 큐 테스트"""
        queue = NotificationQueue()

        assert queue.is_empty() is True
        queue.enqueue("메시지")
        assert queue.is_empty() is False

    def test_clear(self):
        """큐 비우기 테스트"""
        queue = NotificationQueue()

        queue.enqueue("메시지1")
        queue.enqueue("메시지2")

        count = queue.clear()
        assert count == 2
        assert queue.is_empty() is True

    def test_clear_cooldowns(self):
        """쿨다운 초기화 테스트"""
        queue = NotificationQueue(cooldown_seconds=300)

        queue.enqueue("알림", stock_code="005930")
        assert queue.enqueue("알림2", stock_code="005930") is False

        queue.clear_cooldowns()
        assert queue.enqueue("알림3", stock_code="005930") is True

    def test_get_cooldown_remaining(self):
        """쿨다운 남은 시간 테스트"""
        queue = NotificationQueue(cooldown_seconds=300)

        # 쿨다운 없음
        assert queue.get_cooldown_remaining("005930") == 0

        # 알림 후 쿨다운
        queue.enqueue("알림", stock_code="005930")
        remaining = queue.get_cooldown_remaining("005930")
        assert remaining > 0
        assert remaining <= 300

    def test_get_stats(self):
        """통계 테스트"""
        queue = NotificationQueue()

        queue.enqueue("메시지1")
        queue.enqueue("메시지2", stock_code="005930")

        stats = queue.get_stats()
        assert stats["pending"] == 2
        assert stats["success_count"] == 0
        assert stats["failed_count"] == 0


class TestNotificationQueueAsync:
    """NotificationQueue 비동기 테스트"""

    @pytest.mark.asyncio
    async def test_process_next_empty_queue(self):
        """빈 큐 처리 테스트"""
        queue = NotificationQueue()

        result = await queue.process_next()
        assert result is None

    @pytest.mark.asyncio
    async def test_process_next_no_send_func(self):
        """전송 함수 없이 처리 테스트"""
        queue = NotificationQueue()
        queue.enqueue("메시지")

        result = await queue.process_next()
        assert result is None  # send_func 없으면 None

    @pytest.mark.asyncio
    async def test_process_next_success(self):
        """성공적인 처리 테스트"""
        async def mock_send(msg):
            return True

        queue = NotificationQueue(send_func=mock_send)
        queue.enqueue("메시지")

        result = await queue.process_next()
        assert result is True
        assert queue.is_empty() is True

    @pytest.mark.asyncio
    async def test_process_next_failure(self):
        """실패 처리 테스트"""
        async def mock_send(msg):
            return False

        queue = NotificationQueue(send_func=mock_send, max_retries=0)
        queue.enqueue("메시지")

        result = await queue.process_next()
        assert result is False

    @pytest.mark.asyncio
    async def test_retry_on_failure(self):
        """재시도 테스트"""
        call_count = 0

        async def mock_send(msg):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return False
            return True  # 3번째 시도에 성공

        queue = NotificationQueue(send_func=mock_send, max_retries=3)
        queue.enqueue("메시지")

        result = await queue.process_next()
        assert result is True
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self):
        """최대 재시도 초과 테스트"""
        call_count = 0

        async def mock_send(msg):
            nonlocal call_count
            call_count += 1
            return False

        queue = NotificationQueue(send_func=mock_send, max_retries=2)
        queue.enqueue("메시지")

        result = await queue.process_next()
        assert result is False
        assert call_count == 3  # 초기 1회 + 재시도 2회

    @pytest.mark.asyncio
    async def test_flush(self):
        """전체 처리 테스트"""
        async def mock_send(msg):
            return True

        queue = NotificationQueue(send_func=mock_send)
        queue.enqueue("메시지1")
        queue.enqueue("메시지2")
        queue.enqueue("메시지3")

        processed = await queue.flush()
        assert processed == 3
        assert queue.is_empty() is True

    @pytest.mark.asyncio
    async def test_set_send_func(self):
        """전송 함수 설정 테스트"""
        queue = NotificationQueue()

        async def mock_send(msg):
            return True

        queue.set_send_func(mock_send)
        queue.enqueue("메시지")

        result = await queue.process_next()
        assert result is True


class TestNotificationQueueMaxSize:
    """큐 최대 크기 테스트"""

    def test_queue_max_size(self):
        """큐 최대 크기 초과 테스트"""
        queue = NotificationQueue()

        # 최대 크기(100)보다 많이 추가
        for i in range(110):
            queue.enqueue(f"메시지{i}")

        # 최대 크기만큼만 유지
        assert queue.pending_count() == 100


class TestNotificationQueueStats:
    """통계 추적 테스트"""

    @pytest.mark.asyncio
    async def test_stats_after_processing(self):
        """처리 후 통계 테스트"""
        success_count = 0

        async def mock_send(msg):
            nonlocal success_count
            success_count += 1
            return True

        queue = NotificationQueue(send_func=mock_send)
        queue.enqueue("메시지1")
        queue.enqueue("메시지2")

        await queue.flush()

        stats = queue.get_stats()
        assert stats["success_count"] == 2
        assert stats["failed_count"] == 0

    @pytest.mark.asyncio
    async def test_stats_with_failures(self):
        """실패 포함 통계 테스트"""
        async def mock_send(msg):
            return False

        queue = NotificationQueue(send_func=mock_send, max_retries=0)
        queue.enqueue("메시지1")
        queue.enqueue("메시지2")

        await queue.flush()

        stats = queue.get_stats()
        assert stats["success_count"] == 0
        assert stats["failed_count"] == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
