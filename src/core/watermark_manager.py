"""
봉 완성 시점 관리 모듈 (V7.0)

3분봉 캔들의 완성 시점을 계산하고 관리합니다.
Dual-Pass 신호 탐지 (Pre-Check → Confirm-Check)를 위한 타이밍 관리.

주요 기능:
- 봉 완성 시점 계산 (09:03, 09:06, 09:09, ...)
- 다음 봉 완성까지 대기 시간 계산
- 장중/장외 시간 판단
"""

from datetime import datetime, timedelta, time
from typing import Optional, Tuple
import asyncio


# 장 시간 설정 (KST)
MARKET_OPEN = time(9, 0)      # 장 시작
MARKET_CLOSE = time(15, 20)   # 신호 종료 (종가 단일가 전)
MARKET_END = time(15, 30)     # 장 마감

# NXT 시간대 (V6.2-L)
NXT_PRE_OPEN = time(8, 0)     # NXT 프리마켓 시작
NXT_AFTER_CLOSE = time(20, 0) # NXT 애프터마켓 종료

# 봉 간격 (분)
BAR_INTERVAL_MINUTES = 3


class WatermarkManager:
    """
    봉 완성 시점 관리자

    3분봉 기준으로 봉 완성 시점을 계산하고 관리합니다.
    신호 탐지의 Dual-Pass (Pre-Check → Confirm-Check)를 위한
    정확한 타이밍 관리를 제공합니다.

    Features:
    - 봉 완성 시점 계산 (09:03, 09:06, ...)
    - 다음 봉 완성까지 남은 시간 계산
    - 장중/장외 시간 판단
    - 비동기 대기 지원

    Usage:
        wm = WatermarkManager()
        next_bar = wm.get_next_bar_close()
        is_complete = wm.is_bar_complete(some_time)
        await wm.wait_for_next_bar()
    """

    def __init__(self, bar_interval: int = BAR_INTERVAL_MINUTES):
        """
        WatermarkManager 초기화

        Args:
            bar_interval: 봉 간격 (분, 기본 3분)
        """
        self.bar_interval = bar_interval
        self._last_processed_bar: Optional[datetime] = None

    def get_current_bar_start(self, now: Optional[datetime] = None) -> datetime:
        """
        현재 봉의 시작 시간 계산

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            현재 봉의 시작 시간 (예: 09:03 → 09:03:00)
        """
        if now is None:
            now = datetime.now()

        # 장 시작(09:00) 이후 경과 분
        market_open_dt = datetime.combine(now.date(), MARKET_OPEN)
        if now < market_open_dt:
            # 장 시작 전: 첫 봉은 09:00
            return market_open_dt

        elapsed_minutes = (now - market_open_dt).total_seconds() / 60

        # 현재 봉 시작 시간 계산
        bar_index = int(elapsed_minutes) // self.bar_interval
        bar_start_minutes = bar_index * self.bar_interval

        return market_open_dt + timedelta(minutes=bar_start_minutes)

    def get_current_bar_close(self, now: Optional[datetime] = None) -> datetime:
        """
        현재 봉의 완성 시간 계산

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            현재 봉의 완성 시간 (예: 09:03봉 → 09:06:00)
        """
        bar_start = self.get_current_bar_start(now)
        return bar_start + timedelta(minutes=self.bar_interval)

    def get_next_bar_close(self, now: Optional[datetime] = None) -> datetime:
        """
        다음 봉 완성 시간 계산

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            다음 봉 완성 시간
        """
        if now is None:
            now = datetime.now()

        current_bar_close = self.get_current_bar_close(now)

        # 현재 시간이 봉 완성 시점 이전이면 현재 봉 완성 시간 반환
        if now < current_bar_close:
            return current_bar_close

        # 이미 봉이 완성되었으면 다음 봉 완성 시간 반환
        return current_bar_close + timedelta(minutes=self.bar_interval)

    def get_seconds_until_next_bar(self, now: Optional[datetime] = None) -> float:
        """
        다음 봉 완성까지 남은 시간 (초)

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            남은 시간 (초), 0 이상
        """
        if now is None:
            now = datetime.now()

        next_bar = self.get_next_bar_close(now)
        remaining = (next_bar - now).total_seconds()
        return max(0, remaining)

    def is_bar_complete(self, bar_time: datetime, now: Optional[datetime] = None) -> bool:
        """
        특정 봉이 완성되었는지 확인

        Args:
            bar_time: 봉 시작 시간 (예: 09:03:00)
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            True: 봉 완성됨, False: 미완성
        """
        if now is None:
            now = datetime.now()

        bar_close = bar_time + timedelta(minutes=self.bar_interval)
        return now >= bar_close

    def is_market_open(self, now: Optional[datetime] = None) -> bool:
        """
        정규 장 시간인지 확인

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            True: 장중, False: 장외
        """
        if now is None:
            now = datetime.now()

        current_time = now.time()
        return MARKET_OPEN <= current_time <= MARKET_CLOSE

    def is_signal_time(self, now: Optional[datetime] = None, signal_start: time = time(9, 5)) -> bool:
        """
        신호 탐지 허용 시간인지 확인

        Args:
            now: 기준 시간 (기본: 현재 시간)
            signal_start: 신호 시작 시간 (기본: 09:00)

        Returns:
            True: 신호 탐지 가능, False: 불가
        """
        if now is None:
            now = datetime.now()

        current_time = now.time()
        return signal_start <= current_time <= MARKET_CLOSE

    def is_nxt_time(self, now: Optional[datetime] = None) -> bool:
        """
        NXT 거래 시간인지 확인 (프리마켓/애프터마켓)

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            True: NXT 시간, False: 아님
        """
        if now is None:
            now = datetime.now()

        current_time = now.time()

        # 프리마켓: 08:00 ~ 09:00
        is_pre = NXT_PRE_OPEN <= current_time < MARKET_OPEN

        # 애프터마켓: 15:30 ~ 20:00
        is_after = MARKET_END < current_time <= NXT_AFTER_CLOSE

        return is_pre or is_after

    def get_bar_time_range(self, bar_start: datetime) -> Tuple[datetime, datetime]:
        """
        봉의 시작/종료 시간 범위 반환

        Args:
            bar_start: 봉 시작 시간

        Returns:
            (시작 시간, 종료 시간) 튜플
        """
        bar_end = bar_start + timedelta(minutes=self.bar_interval)
        return bar_start, bar_end

    def get_all_bar_times(self, now: Optional[datetime] = None) -> list:
        """
        장중 모든 봉 완성 시점 리스트 반환

        Args:
            now: 기준 날짜 (기본: 오늘)

        Returns:
            봉 완성 시점 리스트 [09:03, 09:06, ..., 15:21]
        """
        if now is None:
            now = datetime.now()

        market_open_dt = datetime.combine(now.date(), MARKET_OPEN)
        market_close_dt = datetime.combine(now.date(), MARKET_CLOSE)

        bar_times = []
        current = market_open_dt + timedelta(minutes=self.bar_interval)

        while current <= market_close_dt + timedelta(minutes=self.bar_interval):
            bar_times.append(current)
            current += timedelta(minutes=self.bar_interval)

        return bar_times

    def get_last_completed_bar_start(self, now: Optional[datetime] = None) -> datetime:
        """
        가장 최근 완성된 봉의 시작 시간

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            마지막 완성 봉의 시작 시간
        """
        if now is None:
            now = datetime.now()

        # 현재 진행 중인 봉의 시작 시간
        current_bar_start = self.get_current_bar_start(now)

        # 직전 봉 시작 시간 (현재 봉 - interval)
        last_completed_bar_start = current_bar_start - timedelta(minutes=self.bar_interval)

        # 장 시작 전이면 전날 마지막 봉 대신 장 시작 봉 반환
        market_open_dt = datetime.combine(now.date(), MARKET_OPEN)
        if last_completed_bar_start < market_open_dt:
            return market_open_dt

        return last_completed_bar_start

    def should_process_bar(self, now: Optional[datetime] = None) -> bool:
        """
        방금 완성된 봉을 처리해야 하는지 확인 (중복 처리 방지)

        봉 완성 시점에 한 번만 처리하고, 이미 처리한 봉은 건너뜁니다.

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            True: 처리 필요, False: 이미 처리됨 또는 장 시작 전
        """
        if now is None:
            now = datetime.now()

        market_open_dt = datetime.combine(now.date(), MARKET_OPEN)

        # 장 시작 전이면 처리 불필요
        if now < market_open_dt:
            return False

        # 마지막 완성 봉의 시작 시간
        last_completed = self.get_last_completed_bar_start(now)

        # 이미 처리한 봉이면 건너뜀
        if self._last_processed_bar == last_completed:
            return False

        # 첫 봉(09:00)이 완성되지 않았으면 처리 불필요 (09:03 전)
        first_bar_close = market_open_dt + timedelta(minutes=self.bar_interval)
        if now < first_bar_close:
            return False

        return True

    def mark_bar_processed(self, now: Optional[datetime] = None) -> datetime:
        """
        방금 완성된 봉을 처리 완료로 표시

        Args:
            now: 기준 시간 (기본: 현재 시간)

        Returns:
            처리된 봉 시작 시간
        """
        if now is None:
            now = datetime.now()

        bar_start = self.get_last_completed_bar_start(now)
        self._last_processed_bar = bar_start
        return bar_start

    async def wait_for_next_bar(self, buffer_seconds: float = 0.5) -> datetime:
        """
        다음 봉 완성까지 비동기 대기

        Args:
            buffer_seconds: 봉 완성 후 추가 대기 시간 (데이터 안정화용)

        Returns:
            완성된 봉의 완성 시간
        """
        wait_seconds = self.get_seconds_until_next_bar() + buffer_seconds

        if wait_seconds > 0:
            await asyncio.sleep(wait_seconds)

        return self.get_current_bar_close()

    def get_pre_check_time(self, bar_close: datetime, pre_check_seconds: int = 30) -> datetime:
        """
        Pre-Check 실행 시점 계산

        봉 완성 전 Pre-Check를 실행할 시점을 반환합니다.

        Args:
            bar_close: 봉 완성 시간
            pre_check_seconds: 봉 완성 전 실행 시점 (초, 기본 30초)

        Returns:
            Pre-Check 실행 시점
        """
        return bar_close - timedelta(seconds=pre_check_seconds)

    def is_pre_check_time(
        self,
        now: Optional[datetime] = None,
        pre_check_seconds: int = 30
    ) -> bool:
        """
        Pre-Check 실행 시점인지 확인

        Args:
            now: 기준 시간 (기본: 현재 시간)
            pre_check_seconds: 봉 완성 전 실행 구간 (초)

        Returns:
            True: Pre-Check 구간, False: 아님
        """
        if now is None:
            now = datetime.now()

        seconds_until = self.get_seconds_until_next_bar(now)
        return 0 < seconds_until <= pre_check_seconds

    def is_confirm_check_time(self, now: Optional[datetime] = None, tolerance_seconds: int = 5) -> bool:
        """
        Confirm-Check 실행 시점인지 확인 (봉 완성 직후)

        Args:
            now: 기준 시간 (기본: 현재 시간)
            tolerance_seconds: 봉 완성 후 허용 구간 (초)

        Returns:
            True: Confirm-Check 구간, False: 아님
        """
        if now is None:
            now = datetime.now()

        # 마지막 완성 봉의 완료 시간 (= 현재 봉 시작 시간)
        last_bar_close = self.get_current_bar_start(now)

        # 봉이 방금 완성된 시점인지 확인
        elapsed_since_close = (now - last_bar_close).total_seconds()
        return 0 <= elapsed_since_close <= tolerance_seconds
