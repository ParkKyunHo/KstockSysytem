"""
Phase 4: watermark_manager.py 단위 테스트 (V7.0)

봉 완성 시점 계산 및 Dual-Pass 타이밍 관리를 검증합니다.
"""

import pytest
from datetime import datetime, time, timedelta
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.core.watermark_manager import (
    WatermarkManager,
    MARKET_OPEN,
    MARKET_CLOSE,
    MARKET_END,
    BAR_INTERVAL_MINUTES,
)


class TestBarTimeCalculation:
    """봉 시간 계산 테스트"""

    def test_current_bar_start_at_open(self):
        """장 시작 시점 테스트"""
        wm = WatermarkManager()

        # 09:00:00
        now = datetime(2026, 1, 21, 9, 0, 0)
        bar_start = wm.get_current_bar_start(now)

        assert bar_start.hour == 9
        assert bar_start.minute == 0
        assert bar_start.second == 0

    def test_current_bar_start_during_session(self):
        """장중 봉 시작 시간 테스트"""
        wm = WatermarkManager()

        # 09:05:30 -> 현재 봉 시작 = 09:03
        now = datetime(2026, 1, 21, 9, 5, 30)
        bar_start = wm.get_current_bar_start(now)

        assert bar_start.hour == 9
        assert bar_start.minute == 3

        # 09:08:59 -> 현재 봉 시작 = 09:06
        now = datetime(2026, 1, 21, 9, 8, 59)
        bar_start = wm.get_current_bar_start(now)

        assert bar_start.hour == 9
        assert bar_start.minute == 6

    def test_current_bar_close(self):
        """봉 완성 시간 테스트"""
        wm = WatermarkManager()

        # 09:05:30 -> 현재 봉 완성 = 09:06
        now = datetime(2026, 1, 21, 9, 5, 30)
        bar_close = wm.get_current_bar_close(now)

        assert bar_close.hour == 9
        assert bar_close.minute == 6
        assert bar_close.second == 0

    def test_next_bar_close_before_completion(self):
        """봉 완성 전 다음 봉 시간 테스트"""
        wm = WatermarkManager()

        # 09:04:00 -> 다음 봉 완성 = 09:06 (현재 봉)
        now = datetime(2026, 1, 21, 9, 4, 0)
        next_bar = wm.get_next_bar_close(now)

        assert next_bar.hour == 9
        assert next_bar.minute == 6

    def test_next_bar_close_after_completion(self):
        """봉 완성 후 다음 봉 시간 테스트"""
        wm = WatermarkManager()

        # 09:06:01 -> 다음 봉 완성 = 09:09
        now = datetime(2026, 1, 21, 9, 6, 1)
        next_bar = wm.get_next_bar_close(now)

        assert next_bar.hour == 9
        assert next_bar.minute == 9


class TestTimeCalculation:
    """시간 계산 테스트"""

    def test_seconds_until_next_bar(self):
        """다음 봉까지 남은 시간 테스트"""
        wm = WatermarkManager()

        # 09:05:00 -> 09:06까지 60초
        now = datetime(2026, 1, 21, 9, 5, 0)
        seconds = wm.get_seconds_until_next_bar(now)

        assert seconds == 60.0

        # 09:05:30 -> 09:06까지 30초
        now = datetime(2026, 1, 21, 9, 5, 30)
        seconds = wm.get_seconds_until_next_bar(now)

        assert seconds == 30.0

    def test_is_bar_complete(self):
        """봉 완성 여부 테스트"""
        wm = WatermarkManager()

        bar_time = datetime(2026, 1, 21, 9, 3, 0)  # 09:03 봉 시작

        # 09:05:59 -> 아직 미완성
        now = datetime(2026, 1, 21, 9, 5, 59)
        assert wm.is_bar_complete(bar_time, now) is False

        # 09:06:00 -> 완성
        now = datetime(2026, 1, 21, 9, 6, 0)
        assert wm.is_bar_complete(bar_time, now) is True


class TestMarketTimeCheck:
    """장 시간 체크 테스트"""

    def test_is_market_open(self):
        """정규장 시간 테스트"""
        wm = WatermarkManager()

        # 장 시작 전
        assert wm.is_market_open(datetime(2026, 1, 21, 8, 59, 0)) is False

        # 장중
        assert wm.is_market_open(datetime(2026, 1, 21, 9, 0, 0)) is True
        assert wm.is_market_open(datetime(2026, 1, 21, 12, 0, 0)) is True
        assert wm.is_market_open(datetime(2026, 1, 21, 15, 20, 0)) is True

        # 장 마감 후
        assert wm.is_market_open(datetime(2026, 1, 21, 15, 21, 0)) is False

    def test_is_signal_time(self):
        """신호 탐지 시간 테스트"""
        wm = WatermarkManager()

        # 신호 시작 전 (09:05 기준)
        assert wm.is_signal_time(datetime(2026, 1, 21, 9, 4, 0)) is False

        # 신호 허용 구간
        assert wm.is_signal_time(datetime(2026, 1, 21, 9, 5, 0)) is True
        assert wm.is_signal_time(datetime(2026, 1, 21, 15, 20, 0)) is True

        # 신호 종료 후
        assert wm.is_signal_time(datetime(2026, 1, 21, 15, 21, 0)) is False

    def test_is_nxt_time(self):
        """NXT 시간 테스트"""
        wm = WatermarkManager()

        # 프리마켓 (08:00~09:00)
        assert wm.is_nxt_time(datetime(2026, 1, 21, 7, 59, 0)) is False
        assert wm.is_nxt_time(datetime(2026, 1, 21, 8, 0, 0)) is True
        assert wm.is_nxt_time(datetime(2026, 1, 21, 8, 30, 0)) is True
        assert wm.is_nxt_time(datetime(2026, 1, 21, 9, 0, 0)) is False

        # 정규장 중 NXT 아님
        assert wm.is_nxt_time(datetime(2026, 1, 21, 12, 0, 0)) is False

        # 애프터마켓 (15:30~20:00)
        assert wm.is_nxt_time(datetime(2026, 1, 21, 15, 30, 0)) is False  # 정확히 15:30은 아님
        assert wm.is_nxt_time(datetime(2026, 1, 21, 15, 31, 0)) is True
        assert wm.is_nxt_time(datetime(2026, 1, 21, 19, 0, 0)) is True
        assert wm.is_nxt_time(datetime(2026, 1, 21, 20, 0, 0)) is True
        assert wm.is_nxt_time(datetime(2026, 1, 21, 20, 1, 0)) is False


class TestBarProcessing:
    """봉 처리 테스트"""

    def test_should_process_bar(self):
        """봉 처리 필요 여부 테스트"""
        wm = WatermarkManager()

        # 09:02:30 -> 첫 봉(09:00-09:03) 미완성, 처리 불필요
        now = datetime(2026, 1, 21, 9, 2, 30)
        assert wm.should_process_bar(now) is False

        # 09:03:01 -> 첫 봉 완성, 처리 필요
        now = datetime(2026, 1, 21, 9, 3, 1)
        assert wm.should_process_bar(now) is True

        # 처리 완료 표시 (09:00 봉 처리됨)
        wm.mark_bar_processed(now)

        # 09:05:30 -> 09:00 봉은 처리 완료, 09:03 봉은 아직 미완성
        now = datetime(2026, 1, 21, 9, 5, 30)
        assert wm.should_process_bar(now) is False

        # 09:06:01 -> 09:03 봉 완성, 처리 필요
        now = datetime(2026, 1, 21, 9, 6, 1)
        assert wm.should_process_bar(now) is True

        # 처리 완료 표시
        wm.mark_bar_processed(now)

        # 같은 시간대 다시 체크 -> 처리 불필요
        now = datetime(2026, 1, 21, 9, 6, 30)
        assert wm.should_process_bar(now) is False

        # 다음 봉 완성 시점 -> 처리 필요
        now = datetime(2026, 1, 21, 9, 9, 1)
        assert wm.should_process_bar(now) is True

    def test_mark_bar_processed(self):
        """봉 처리 완료 표시 테스트"""
        wm = WatermarkManager()

        now = datetime(2026, 1, 21, 9, 6, 1)
        bar_start = wm.mark_bar_processed(now)

        # 09:06:01 시점의 현재 봉 시작 = 09:03
        assert bar_start.hour == 9
        assert bar_start.minute == 3

    def test_get_all_bar_times(self):
        """모든 봉 완성 시점 테스트"""
        wm = WatermarkManager()

        bar_times = wm.get_all_bar_times(datetime(2026, 1, 21, 12, 0, 0))

        # 첫 봉 완성: 09:03
        assert bar_times[0].hour == 9
        assert bar_times[0].minute == 3

        # 3분 간격 확인
        for i in range(1, len(bar_times)):
            diff = (bar_times[i] - bar_times[i-1]).total_seconds() / 60
            assert diff == 3


class TestDualPassTiming:
    """Dual-Pass 타이밍 테스트"""

    def test_get_pre_check_time(self):
        """Pre-Check 시점 테스트"""
        wm = WatermarkManager()

        bar_close = datetime(2026, 1, 21, 9, 6, 0)
        pre_check = wm.get_pre_check_time(bar_close, pre_check_seconds=30)

        # 봉 완성 30초 전 = 09:05:30
        assert pre_check.hour == 9
        assert pre_check.minute == 5
        assert pre_check.second == 30

    def test_is_pre_check_time(self):
        """Pre-Check 구간 테스트"""
        wm = WatermarkManager()

        # 봉 완성 30초 전 구간
        # 09:05:31 -> 봉 완성(09:06)까지 29초 -> Pre-Check 구간
        now = datetime(2026, 1, 21, 9, 5, 31)
        assert wm.is_pre_check_time(now, pre_check_seconds=30) is True

        # 09:05:00 -> 60초 남음 -> Pre-Check 아님
        now = datetime(2026, 1, 21, 9, 5, 0)
        assert wm.is_pre_check_time(now, pre_check_seconds=30) is False

        # 09:06:01 -> 이미 완성됨 -> Pre-Check 아님
        now = datetime(2026, 1, 21, 9, 6, 1)
        assert wm.is_pre_check_time(now, pre_check_seconds=30) is False

    def test_is_confirm_check_time(self):
        """Confirm-Check 구간 테스트"""
        wm = WatermarkManager()

        # 봉 완성 직후 (5초 이내)
        now = datetime(2026, 1, 21, 9, 6, 3)
        assert wm.is_confirm_check_time(now, tolerance_seconds=5) is True

        # 봉 완성 5초 초과
        now = datetime(2026, 1, 21, 9, 6, 10)
        assert wm.is_confirm_check_time(now, tolerance_seconds=5) is False


class TestEdgeCases:
    """엣지 케이스 테스트"""

    def test_before_market_open(self):
        """장 시작 전 테스트"""
        wm = WatermarkManager()

        # 08:30 -> 첫 봉 시작은 09:00
        now = datetime(2026, 1, 21, 8, 30, 0)
        bar_start = wm.get_current_bar_start(now)

        assert bar_start.hour == 9
        assert bar_start.minute == 0

    def test_bar_time_range(self):
        """봉 시작/종료 범위 테스트"""
        wm = WatermarkManager()

        bar_start = datetime(2026, 1, 21, 9, 3, 0)
        start, end = wm.get_bar_time_range(bar_start)

        assert start == bar_start
        assert end.hour == 9
        assert end.minute == 6

    def test_custom_bar_interval(self):
        """커스텀 봉 간격 테스트"""
        wm = WatermarkManager(bar_interval=5)  # 5분봉

        now = datetime(2026, 1, 21, 9, 7, 0)
        bar_start = wm.get_current_bar_start(now)

        # 5분봉: 09:07 -> 현재 봉 시작 = 09:05
        assert bar_start.minute == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
