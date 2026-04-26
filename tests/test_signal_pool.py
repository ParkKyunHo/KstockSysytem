"""
Phase 2: signal_pool.py 단위 테스트 (V7.0)

통합 신호 Pool의 Thread-safe 동작과 기능을 검증합니다.
"""

import pytest
import threading
import time
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.signal_pool import SignalPool, StockInfo


class TestStockInfo:
    """StockInfo 데이터클래스 테스트"""

    def test_stock_info_creation(self):
        """기본 생성 테스트"""
        info = StockInfo(
            stock_code="005930",
            stock_name="삼성전자",
        )

        assert info.stock_code == "005930"
        assert info.stock_name == "삼성전자"
        assert info.last_signal_at is None
        assert info.signal_count == 0
        assert isinstance(info.metadata, dict)

    def test_stock_info_with_metadata(self):
        """메타데이터 포함 생성 테스트"""
        info = StockInfo(
            stock_code="005930",
            stock_name="삼성전자",
            metadata={"change_rate": 5.2, "volume": 1000000}
        )

        assert info.metadata["change_rate"] == 5.2
        assert info.metadata["volume"] == 1000000

    def test_update_signal(self):
        """신호 업데이트 테스트"""
        info = StockInfo(stock_code="005930", stock_name="삼성전자")

        assert info.signal_count == 0
        assert info.last_signal_at is None

        info.update_signal()

        assert info.signal_count == 1
        assert info.last_signal_at is not None

        info.update_signal()
        assert info.signal_count == 2

    def test_signal_cooldown_elapsed(self):
        """쿨다운 경과 테스트"""
        info = StockInfo(stock_code="005930", stock_name="삼성전자")

        # 신호 없으면 쿨다운 경과로 판단
        assert info.get_signal_cooldown_elapsed(300) is True

        # 신호 발생 후 즉시 체크 -> 쿨다운 중
        info.update_signal()
        assert info.get_signal_cooldown_elapsed(300) is False

        # 짧은 쿨다운 (1초)으로 테스트
        time.sleep(0.1)
        assert info.get_signal_cooldown_elapsed(0) is True  # 0초 쿨다운이면 즉시 통과


class TestSignalPool:
    """SignalPool 클래스 테스트"""

    def test_add_and_get(self):
        """종목 추가 및 조회 테스트"""
        pool = SignalPool()

        info = pool.add("005930", "삼성전자")
        assert info.stock_code == "005930"
        assert info.stock_name == "삼성전자"

        retrieved = pool.get("005930")
        assert retrieved is not None
        assert retrieved.stock_code == "005930"

    def test_add_with_metadata(self):
        """메타데이터 포함 추가 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자", {"change_rate": 5.2})
        info = pool.get("005930")

        assert info.metadata["change_rate"] == 5.2

    def test_add_existing_updates_metadata(self):
        """기존 종목 재추가 시 메타데이터만 업데이트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자", {"rate": 1.0})
        original_added_at = pool.get("005930").added_at

        # 동일 종목 재추가
        pool.add("005930", "삼성전자", {"rate": 2.0, "new_key": "value"})

        info = pool.get("005930")
        assert info.metadata["rate"] == 2.0
        assert info.metadata["new_key"] == "value"
        assert info.added_at == original_added_at  # added_at 유지

    def test_remove(self):
        """종목 제거 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        assert pool.contains("005930") is True

        result = pool.remove("005930")
        assert result is True
        assert pool.contains("005930") is False

        # 없는 종목 제거
        result = pool.remove("000000")
        assert result is False

    def test_contains(self):
        """존재 여부 확인 테스트"""
        pool = SignalPool()

        assert pool.contains("005930") is False
        pool.add("005930", "삼성전자")
        assert pool.contains("005930") is True

    def test_size(self):
        """크기 테스트"""
        pool = SignalPool()

        assert pool.size() == 0
        pool.add("005930", "삼성전자")
        assert pool.size() == 1
        pool.add("000660", "SK하이닉스")
        assert pool.size() == 2

    def test_get_all(self):
        """전체 조회 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        pool.add("000660", "SK하이닉스")

        all_stocks = pool.get_all()
        assert len(all_stocks) == 2

        codes = [info.stock_code for info in all_stocks]
        assert "005930" in codes
        assert "000660" in codes

    def test_get_all_codes(self):
        """전체 종목코드 조회 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        pool.add("000660", "SK하이닉스")

        codes = pool.get_all_codes()
        assert len(codes) == 2
        assert "005930" in codes
        assert "000660" in codes

    def test_clear(self):
        """전체 삭제 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        pool.add("000660", "SK하이닉스")

        count = pool.clear()
        assert count == 2
        assert pool.size() == 0

    def test_update_signal(self):
        """신호 갱신 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")

        assert pool.update_signal("005930") is True
        info = pool.get("005930")
        assert info.signal_count == 1

        # 없는 종목
        assert pool.update_signal("000000") is False

    def test_can_signal(self):
        """신호 가능 여부 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")

        # 처음은 가능
        assert pool.can_signal("005930", cooldown_seconds=300) is True

        # 신호 후 쿨다운
        pool.update_signal("005930")
        assert pool.can_signal("005930", cooldown_seconds=300) is False

        # 짧은 쿨다운으로 테스트
        time.sleep(0.1)
        assert pool.can_signal("005930", cooldown_seconds=0) is True

    def test_get_signal_ready_stocks(self):
        """신호 가능 종목 조회 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        pool.add("000660", "SK하이닉스")

        # 초기에는 모두 신호 가능
        ready = pool.get_signal_ready_stocks(cooldown_seconds=300)
        assert len(ready) == 2

        # 삼성전자 신호 발생 -> 쿨다운
        pool.update_signal("005930")
        ready = pool.get_signal_ready_stocks(cooldown_seconds=300)
        assert len(ready) == 1
        assert ready[0].stock_code == "000660"

    def test_get_stats(self):
        """통계 조회 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        pool.add("000660", "SK하이닉스")
        pool.update_signal("005930")

        stats = pool.get_stats()
        assert stats["total"] == 2
        assert stats["signaled"] == 1
        assert stats["never_signaled"] == 1
        assert stats["total_signals"] == 1

    def test_to_dict(self):
        """딕셔너리 변환 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자", {"rate": 5.0})

        d = pool.to_dict()
        assert "005930" in d
        assert d["005930"]["stock_name"] == "삼성전자"
        assert d["005930"]["metadata"]["rate"] == 5.0

    def test_len_operator(self):
        """len() 연산자 테스트"""
        pool = SignalPool()

        assert len(pool) == 0
        pool.add("005930", "삼성전자")
        assert len(pool) == 1

    def test_in_operator(self):
        """in 연산자 테스트"""
        pool = SignalPool()

        assert "005930" not in pool
        pool.add("005930", "삼성전자")
        assert "005930" in pool

    def test_iter(self):
        """for 루프 테스트"""
        pool = SignalPool()

        pool.add("005930", "삼성전자")
        pool.add("000660", "SK하이닉스")

        codes = list(pool)
        assert len(codes) == 2
        assert "005930" in codes


class TestSignalPoolThreadSafety:
    """SignalPool Thread-safety 테스트"""

    def test_concurrent_add(self):
        """동시 추가 테스트"""
        pool = SignalPool()
        n_threads = 10
        n_items_per_thread = 100

        def add_items(thread_id):
            for i in range(n_items_per_thread):
                pool.add(f"{thread_id:02d}{i:04d}", f"Stock_{thread_id}_{i}")

        threads = [
            threading.Thread(target=add_items, args=(t,))
            for t in range(n_threads)
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert pool.size() == n_threads * n_items_per_thread

    def test_concurrent_read_write(self):
        """동시 읽기/쓰기 테스트"""
        pool = SignalPool()
        pool.add("005930", "삼성전자")

        errors = []

        def writer():
            for i in range(100):
                pool.add(f"00000{i}", f"Stock_{i}")
                time.sleep(0.001)

        def reader():
            for _ in range(100):
                try:
                    _ = pool.get_all()
                    _ = pool.size()
                    _ = pool.contains("005930")
                except Exception as e:
                    errors.append(e)
                time.sleep(0.001)

        threads = [
            threading.Thread(target=writer),
            threading.Thread(target=reader),
            threading.Thread(target=reader),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0, f"Thread-safety errors: {errors}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
