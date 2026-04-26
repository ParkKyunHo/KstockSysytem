"""
장 스케줄 관리 모듈

장 시작/종료 감지, 휴장일 관리, 자동 대기 기능을 제공합니다.

PRD REQ-001, REQ-002 구현:
- 장 시간 자동 감지 및 대기
- 휴장일 처리 (주말/공휴일)
"""

from datetime import datetime, time, date, timedelta
from enum import Enum
from pathlib import Path
from typing import Callable, Optional, Awaitable, Set
import asyncio
import json

from src.utils.logger import get_logger
from src.utils.config import get_risk_settings


class MarketState(Enum):
    """장 상태 (V6.2-L NXT 확장)"""
    CLOSED = "closed"               # 폐장 (~08:00, 20:00~)
    NXT_PRE_MARKET = "nxt_pre_market"   # NXT 프리마켓 (08:00~08:50)
    PRE_MARKET = "pre_market"       # 동시호가 (08:50~09:00)
    OPEN = "open"                   # 정규장 (09:00~15:20)
    KRX_CLOSING = "krx_closing"     # KRX 단일가 (15:20~15:30) - NXT 중단!
    NXT_AFTER = "nxt_after"         # NXT 애프터마켓 (15:30~20:00)
    AFTER_HOURS = "after_hours"     # 장 종료 (20:00~)
    HOLIDAY = "holiday"             # 휴장일 (주말/공휴일)


class MarketScheduleManager:
    """
    장 스케줄 관리자

    장 시간 감지, 휴장일 관리, 대기 기능을 제공합니다.

    Usage:
        schedule = MarketScheduleManager()
        await schedule.initialize()

        if not schedule.is_market_open():
            await schedule.wait_for_market_open()
    """

    # 장 시간 (KST) - V6.2-L NXT 확장
    NXT_PRE_START = time(8, 0)         # NXT 프리마켓 시작
    PRE_MARKET_START = time(8, 50)     # 동시호가 시작 (V6.2-L: 08:30→08:50)
    CLOSING_START = time(15, 20)       # KRX 단일가 시작 (NXT 중단)
    MARKET_CLOSE_WARNING = time(15, 15)  # 종료 알림 시간
    KRX_CLOSE = time(15, 30)           # KRX 정규장 종료
    NXT_AFTER_END = time(20, 0)        # NXT 애프터마켓 종료

    def __init__(self):
        self._logger = get_logger(__name__)
        self._state = MarketState.CLOSED
        self._holidays: Set[date] = set()
        self._initialized = False

        # 환경변수에서 장 시작 시간 로드
        try:
            settings = get_risk_settings()
            time_str = settings.market_open_time
            parts = time_str.split(":")
            self.MARKET_OPEN = time(int(parts[0]), int(parts[1]))
            # 동시호가 시작은 장 시작 10분 전 (V6.2-L: 08:30→08:50)
            pre_minutes = self.MARKET_OPEN.hour * 60 + self.MARKET_OPEN.minute - 10
            self.PRE_MARKET_START = time(pre_minutes // 60, pre_minutes % 60)
            self._logger.info(f"장 시작 시간: {self.MARKET_OPEN.strftime('%H:%M')}")
        except Exception as e:
            self.MARKET_OPEN = time(9, 0)  # 기본값
            self._logger.warning(f"장 시작 시간 파싱 실패, 기본값 09:00 사용: {e}")

        # 콜백 (async 함수)
        self.on_market_open: Optional[Callable[[], Awaitable[None]]] = None
        self.on_market_close: Optional[Callable[[], Awaitable[None]]] = None
        self.on_pre_market: Optional[Callable[[], Awaitable[None]]] = None
        self.on_close_warning: Optional[Callable[[], Awaitable[None]]] = None

    async def initialize(self) -> None:
        """휴장일 데이터 로드"""
        await self._load_holidays()
        self._initialized = True
        self._logger.info(
            f"MarketScheduleManager 초기화 완료: {len(self._holidays)}개 휴장일 로드"
        )

    def get_state(self) -> MarketState:
        """
        현재 장 상태 반환 (V6.2-L NXT 확장)

        시간대 구분:
        - ~08:00: CLOSED
        - 08:00~08:50: NXT_PRE_MARKET (NXT 프리마켓)
        - 08:50~09:00: PRE_MARKET (동시호가)
        - 09:00~15:20: OPEN (정규장)
        - 15:20~15:30: KRX_CLOSING (KRX 단일가, NXT 중단!)
        - 15:30~20:00: NXT_AFTER (NXT 애프터마켓)
        - 20:00~: AFTER_HOURS

        Returns:
            MarketState: 현재 장 상태
        """
        now = datetime.now()
        today = now.date()
        current_time = now.time()

        # 휴장일 체크 (공휴일)
        if self.is_holiday(today):
            return MarketState.HOLIDAY

        # 주말 체크
        if today.weekday() >= 5:  # 토요일(5), 일요일(6)
            return MarketState.HOLIDAY

        # V6.2-L NXT 시간대별 상태
        if current_time < self.NXT_PRE_START:
            return MarketState.CLOSED
        elif current_time < self.PRE_MARKET_START:
            return MarketState.NXT_PRE_MARKET
        elif current_time < self.MARKET_OPEN:
            return MarketState.PRE_MARKET
        elif current_time < self.CLOSING_START:
            return MarketState.OPEN
        elif current_time < self.KRX_CLOSE:
            return MarketState.KRX_CLOSING  # NXT 중단!
        elif current_time < self.NXT_AFTER_END:
            return MarketState.NXT_AFTER
        else:
            return MarketState.AFTER_HOURS

    def is_market_open(self) -> bool:
        """
        거래 가능 시간인지 확인 (V6.2-L NXT 확장)

        거래 가능:
        - OPEN (09:00~15:20): 정규장
        - NXT_AFTER (15:30~20:00): NXT 애프터마켓

        거래 불가:
        - KRX_CLOSING (15:20~15:30): NXT 중단

        Returns:
            bool: 거래 가능 여부
        """
        state = self.get_state()
        return state in (MarketState.OPEN, MarketState.NXT_AFTER)

    def is_nxt_exit_possible(self) -> bool:
        """
        V6.2-L: NXT 청산/손절 가능 시간인지 확인

        청산 가능:
        - NXT_PRE_MARKET (08:00~08:50): 프리마켓 청산
        - OPEN (09:00~15:20): 정규장
        - NXT_AFTER (15:30~20:00): 애프터마켓 청산

        Returns:
            bool: 청산 가능 여부
        """
        state = self.get_state()
        return state in (MarketState.NXT_PRE_MARKET, MarketState.OPEN, MarketState.NXT_AFTER)

    def is_trading_possible(self) -> bool:
        """
        매매 실행 가능 시간인지 확인 (정규장만)

        Returns:
            bool: 매매 가능 여부
        """
        return self.get_state() == MarketState.OPEN

    def is_holiday(self, check_date: date) -> bool:
        """
        휴장일인지 확인

        Args:
            check_date: 확인할 날짜

        Returns:
            bool: 휴장일 여부
        """
        return check_date in self._holidays

    def get_next_market_open(self) -> datetime:
        """
        다음 장 시작 시간 반환

        Returns:
            datetime: 다음 장 시작 시간
        """
        now = datetime.now()
        today = now.date()

        # 오늘 장이 아직 안 열렸고, 휴장일이 아니면 오늘 09:00
        if (
            now.time() < self.MARKET_OPEN
            and not self.is_holiday(today)
            and today.weekday() < 5
        ):
            return datetime.combine(today, self.MARKET_OPEN)

        # 다음 거래일 찾기
        next_day = today + timedelta(days=1)
        while self.is_holiday(next_day) or next_day.weekday() >= 5:
            next_day += timedelta(days=1)
            # 안전장치: 최대 30일 검색
            if (next_day - today).days > 30:
                break

        return datetime.combine(next_day, self.MARKET_OPEN)

    def get_time_until_market_open(self) -> timedelta:
        """
        장 시작까지 남은 시간

        Returns:
            timedelta: 남은 시간
        """
        next_open = self.get_next_market_open()
        now = datetime.now()

        if next_open > now:
            return next_open - now
        return timedelta(0)

    async def wait_for_market_open(self) -> None:
        """
        장 시작까지 대기 (비동기)

        장이 열릴 때까지 대기하고, 관련 콜백을 실행합니다.
        """
        self._logger.info("장 시작 대기 시작...")

        pre_market_notified = False

        while not self.is_market_open():
            state = self.get_state()

            if state == MarketState.HOLIDAY:
                # 다음 거래일까지 대기 (최대 1시간씩)
                next_open = self.get_next_market_open()
                wait_seconds = min(
                    (next_open - datetime.now()).total_seconds(),
                    3600  # 최대 1시간
                )
                self._logger.info(
                    f"휴장일 - 다음 장 시작: {next_open.strftime('%Y-%m-%d %H:%M')}, "
                    f"대기: {int(wait_seconds)}초"
                )
                await asyncio.sleep(max(wait_seconds, 1))

            elif state == MarketState.PRE_MARKET:
                # 동시호가 콜백 (한 번만)
                if not pre_market_notified:
                    pre_market_notified = True
                    if self.on_pre_market:
                        try:
                            await self.on_pre_market()
                        except Exception as e:
                            self._logger.error(f"on_pre_market 콜백 에러: {e}")

                # 정규장까지 대기
                wait_seconds = await self._wait_until(self.MARKET_OPEN)
                self._logger.info(f"동시호가 중 - 정규장 시작까지 {int(wait_seconds)}초 대기")

            elif state == MarketState.CLOSED:
                # 다음 동시호가 또는 정규장까지 대기
                now = datetime.now()

                if now.time() < self.PRE_MARKET_START:
                    # 오늘 동시호가까지 대기
                    wait_seconds = await self._wait_until(self.PRE_MARKET_START)
                    self._logger.info(f"장 시작 전 - 동시호가까지 {int(wait_seconds)}초 대기")
                else:
                    # 다음 날 장 시작까지 대기 (최대 1시간씩)
                    next_open = self.get_next_market_open()
                    wait_seconds = min(
                        (next_open - now).total_seconds(),
                        3600
                    )
                    self._logger.info(
                        f"장 종료 후 - 다음 장 시작: {next_open.strftime('%Y-%m-%d %H:%M')}"
                    )
                    await asyncio.sleep(max(wait_seconds, 1))

            else:
                # 예상치 못한 상태
                await asyncio.sleep(10)

        # 장 시작 콜백
        self._logger.info("장 시작됨!")
        if self.on_market_open:
            try:
                await self.on_market_open()
            except Exception as e:
                self._logger.error(f"on_market_open 콜백 에러: {e}")

    async def _wait_until(self, target_time: time) -> float:
        """
        특정 시간까지 대기

        Args:
            target_time: 대기할 시간

        Returns:
            float: 대기한 시간 (초)
        """
        now = datetime.now()
        target = datetime.combine(now.date(), target_time)

        if target <= now:
            return 0

        wait_seconds = (target - now).total_seconds()
        await asyncio.sleep(wait_seconds)
        return wait_seconds

    def get_status_text(self) -> str:
        """
        현재 장 상태 텍스트

        Returns:
            str: 상태 텍스트
        """
        state = self.get_state()
        now = datetime.now()

        state_names = {
            MarketState.CLOSED: "폐장",
            MarketState.NXT_PRE_MARKET: "NXT 프리마켓",
            MarketState.PRE_MARKET: "동시호가",
            MarketState.OPEN: "정규장",
            MarketState.KRX_CLOSING: "KRX 단일가",
            MarketState.NXT_AFTER: "NXT 애프터마켓",
            MarketState.AFTER_HOURS: "장외",
            MarketState.HOLIDAY: "휴장",
        }

        status = f"[장 상태: {state_names.get(state, '알 수 없음')}]\n"
        status += f"현재 시간: {now.strftime('%H:%M:%S')}\n"

        if state in (MarketState.CLOSED, MarketState.HOLIDAY):
            next_open = self.get_next_market_open()
            remaining = self.get_time_until_market_open()
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            status += f"다음 장 시작: {next_open.strftime('%Y-%m-%d %H:%M')}\n"
            status += f"남은 시간: {hours}시간 {minutes}분"

        elif state == MarketState.OPEN:
            close_time = datetime.combine(now.date(), self.NXT_AFTER_END)  # V6.2-L: 20:00 기준
            remaining = close_time - now
            hours, remainder = divmod(int(remaining.total_seconds()), 3600)
            minutes, _ = divmod(remainder, 60)
            status += f"전체 장 마감까지: {hours}시간 {minutes}분"

        return status

    async def _load_holidays(self) -> None:
        """
        휴장일 데이터 로드 (config/holidays.json)

        한국거래소 공휴일 캘린더 기준.
        JSON 파일 로드 실패 시 하드코딩 폴백 사용.
        """
        self._holidays = set()

        # config/holidays.json 경로 탐색
        holidays_path = Path(__file__).resolve().parent.parent.parent / "config" / "holidays.json"

        if holidays_path.exists():
            try:
                with open(holidays_path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                for year_str, entries in data.get("holidays", {}).items():
                    for entry in entries:
                        self._holidays.add(date.fromisoformat(entry["date"]))

                self._logger.debug(
                    f"휴장일 로드 완료: {len(self._holidays)}개 (config/holidays.json)"
                )

                # 현재 연도 데이터 유무 확인
                current_year = str(datetime.now().year)
                if current_year not in data.get("holidays", {}):
                    self._logger.warning(
                        f"config/holidays.json에 {current_year}년 공휴일 데이터가 없습니다. "
                        f"휴장일 감지가 불완전할 수 있습니다."
                    )
                return

            except Exception as e:
                self._logger.warning(f"holidays.json 로드 실패, 폴백 사용: {e}")

        else:
            self._logger.warning(
                f"config/holidays.json 파일 없음 ({holidays_path}), 폴백 사용"
            )

        # 폴백: 하드코딩 (JSON 로드 실패 시)
        self._holidays = {
            date(2025, 1, 1), date(2025, 1, 28), date(2025, 1, 29),
            date(2025, 1, 30), date(2025, 3, 1), date(2025, 3, 3),
            date(2025, 5, 5), date(2025, 5, 6), date(2025, 6, 6),
            date(2025, 8, 15), date(2025, 10, 3), date(2025, 10, 6),
            date(2025, 10, 7), date(2025, 10, 8), date(2025, 10, 9),
            date(2025, 12, 25),
            date(2026, 1, 1), date(2026, 2, 16), date(2026, 2, 17),
            date(2026, 2, 18), date(2026, 3, 2), date(2026, 5, 5),
            date(2026, 5, 25), date(2026, 6, 8), date(2026, 8, 17),
            date(2026, 9, 24), date(2026, 9, 25), date(2026, 9, 26),
            date(2026, 10, 3), date(2026, 10, 9), date(2026, 12, 25),
        }
        self._logger.debug(f"휴장일 폴백 로드 완료: {len(self._holidays)}개")

    def add_holiday(self, holiday_date: date) -> None:
        """
        휴장일 추가

        Args:
            holiday_date: 추가할 휴장일
        """
        self._holidays.add(holiday_date)
        self._logger.info(f"휴장일 추가: {holiday_date}")

    def remove_holiday(self, holiday_date: date) -> None:
        """
        휴장일 제거

        Args:
            holiday_date: 제거할 휴장일
        """
        self._holidays.discard(holiday_date)
        self._logger.info(f"휴장일 제거: {holiday_date}")


# 싱글톤 인스턴스
_market_schedule: Optional[MarketScheduleManager] = None


def get_market_schedule() -> MarketScheduleManager:
    """싱글톤 MarketScheduleManager 인스턴스 반환"""
    global _market_schedule
    if _market_schedule is None:
        _market_schedule = MarketScheduleManager()
    return _market_schedule
