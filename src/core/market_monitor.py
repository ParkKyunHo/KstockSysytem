"""
시장 모니터링 모듈

TradingEngine에서 추출된 KOSDAQ 지수 감시 및 Global_Lock 관리.
Phase 4-D: ~85줄 절감.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Callable, Awaitable, List, Tuple
import asyncio
import logging


@dataclass
class MarketMonitorCallbacks:
    """MarketMonitor → TradingEngine 콜백"""

    get_engine_state: Callable[[], str]
    is_regular_trading_hours: Callable[[], bool]
    send_telegram: Callable[[str], Awaitable[None]]
    get_kosdaq_index: Callable[[], Awaitable[float]]


class MarketMonitor:
    """
    KOSDAQ 지수 감시 및 Global_Lock 관리.

    10초마다 KOSDAQ 지수를 조회하여 시장 급락을 감지하고,
    Global_Lock을 발동/해제합니다.
    """

    def __init__(
        self,
        risk_settings,
        logger: logging.Logger,
        callbacks: MarketMonitorCallbacks,
        watcher_interval: float = 10.0,
    ):
        self._risk_settings = risk_settings
        self._logger = logger
        self._callbacks = callbacks
        self._watcher_interval = watcher_interval

        # KOSDAQ 모니터링 상태
        self._kosdaq_prices: List[Tuple[datetime, float]] = []
        self._kosdaq_crash_threshold: float = -0.8
        self._global_lock: bool = False
        self._global_lock_until: Optional[datetime] = None

    @property
    def global_lock(self) -> bool:
        return self._global_lock

    @global_lock.setter
    def global_lock(self, value: bool) -> None:
        self._global_lock = value

    @property
    def global_lock_until(self) -> Optional[datetime]:
        return self._global_lock_until

    @global_lock_until.setter
    def global_lock_until(self, value: Optional[datetime]) -> None:
        self._global_lock_until = value

    def reset_daily(self) -> None:
        """일일 리셋"""
        self._kosdaq_prices.clear()
        self._global_lock = False
        self._global_lock_until = None

    async def market_watcher_loop(self) -> None:
        """
        시장 감시 루프 (PRD v3.0 6-4)

        10초마다 KOSDAQ 지수를 조회하여 시장 급락을 감지합니다.
        3분 내 -0.8% 하락 시 Global_Lock 발동 → 5분간 신규 매수 중단
        """
        self._logger.info("[MarketWatcher] 시장 감시 루프 시작 (10초 간격)")

        while self._callbacks.get_engine_state() in ("RUNNING", "PAUSED"):
            await asyncio.sleep(self._watcher_interval)

            if self._callbacks.get_engine_state() != "RUNNING":
                continue

            if not self._callbacks.is_regular_trading_hours():
                continue

            try:
                # Global_Lock 해제 시간 체크
                if self._global_lock and self._global_lock_until:
                    if datetime.now() >= self._global_lock_until:
                        self._global_lock = False
                        self._global_lock_until = None
                        self._logger.info("[MarketWatcher] Global_Lock 해제")
                        await self._callbacks.send_telegram(
                            "Global_Lock 해제\n\n"
                            "시장 안정화로 신규 매수 재개"
                        )

                # KOSDAQ 지수 조회
                kosdaq_price = await self._callbacks.get_kosdaq_index()
                if kosdaq_price <= 0:
                    continue

                now = datetime.now()

                # 설정된 기간 이상 지난 데이터 제거
                check_minutes = self._risk_settings.global_lock_check_minutes
                cutoff = now - timedelta(minutes=check_minutes)
                self._kosdaq_prices = [
                    (t, p) for t, p in self._kosdaq_prices if t >= cutoff
                ]

                # 현재 지수 추가
                self._kosdaq_prices.append((now, kosdaq_price))

                # 설정된 기간 전 대비 하락률 계산
                if len(self._kosdaq_prices) >= 2:
                    oldest = self._kosdaq_prices[0][1]
                    change_rate = (kosdaq_price - oldest) / oldest * 100

                    if (
                        change_rate <= self._kosdaq_crash_threshold
                        and not self._global_lock
                    ):
                        lock_minutes = self._risk_settings.global_lock_minutes
                        self._global_lock = True
                        self._global_lock_until = now + timedelta(
                            minutes=lock_minutes
                        )
                        self._logger.warning(
                            f"[MarketWatcher] 시장 급락 감지! "
                            f"KOSDAQ {change_rate:.2f}% → Global_Lock"
                        )
                        await self._callbacks.send_telegram(
                            f"시장 급락 감지!\n\n"
                            f"KOSDAQ: {change_rate:.2f}% ({check_minutes}분 내)\n"
                            f"Global_Lock 발동\n"
                            f"{lock_minutes}분간 신규 매수 중단\n\n"
                            f"기존 포지션 리스크 관리는 정상 동작"
                        )

            except Exception as e:
                self._logger.error(f"[MarketWatcher] 에러: {e}")
