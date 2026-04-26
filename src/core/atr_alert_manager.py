"""
ATR 지저깨 알림 관리자

Grand Trend V6: 3분봉 지저깨 실시간 알림 시스템

책임:
- 조건검색 0번 종목 감시 (주도주 후보 1차 필터링)
- Grand Trend 필터 기반 신호 탐지
- 텔레그램 알림 발송

지저깨 탐지 조건 (Grand Trend V6):
- trendFilter: Close > EMA200 AND ATR(10) > ATR(50) (EMA200 위 + 변동성 확장)
- zone: Low <= EMA20 AND Close >= EMA60 (헌팅 존)
- meaningful: CrossUp(C, EMA5) AND 양봉 AND V >= V[1] (의미 있는 반등)
"""

import asyncio
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

from src.core.indicator import Indicator
from src.core.candle_builder import Timeframe
from src.core.realtime_data_manager import Tier

if TYPE_CHECKING:
    from src.api.endpoints.market import MarketAPI
    from src.notification.telegram import TelegramBot
    from src.core.realtime_data_manager import RealTimeDataManager
    from src.core.candle_builder import CandleManager


# Grand Trend V6 신호 상수
MIN_CANDLES_REQUIRED = 210    # EMA200 + 10봉 여유 (800개 로딩 기준 충분)


@dataclass
class AtrAlertState:
    """종목별 알림 상태"""
    stock_code: str
    stock_name: str
    last_alert_time: Optional[datetime] = None
    alert_count_today: int = 0
    registered_at: datetime = field(default_factory=datetime.now)


class AtrAlertManager:
    """
    Grand Trend V6 지저깨 알림 관리자

    조건검색 0번 종목을 감시하여 3분봉 기준
    Grand Trend 필터 충족 시 텔레그램 알림을 발송합니다.

    필터 조건:
    - trendFilter: Close > EMA200 AND ATR(10) > ATR(50)
    - zone: Low <= EMA20 AND Close >= EMA60
    - meaningful: CrossUp(C, EMA5) AND 양봉 AND V >= V[1]
    """

    def __init__(
        self,
        market_api: "MarketAPI",
        telegram: Optional["TelegramBot"],
        logger,
        data_manager: "RealTimeDataManager",
        candle_manager: "CandleManager",
        period: int = 10,  # Grand Trend V6: ATR(10)
        cooldown_seconds: int = 300,
        max_alerts_per_day: int = 3,
    ):
        """
        Args:
            market_api: 시장 데이터 API
            telegram: 텔레그램 봇 (Optional)
            logger: 로거
            data_manager: 실시간 데이터 관리자 (캔들 로드용)
            candle_manager: 캔들 매니저 (캐시 조회용)
            period: ATR 단기 기간 (Grand Trend V6: 10)
            cooldown_seconds: 알림 쿨다운 (기본 300초 = 5분)
            max_alerts_per_day: 같은 종목 당 일일 최대 알림 (기본 3)
        """
        self._market_api = market_api
        self._telegram = telegram
        self._logger = logger.bind(component="AtrAlertManager") if hasattr(logger, "bind") else logger
        self._data_manager = data_manager
        self._candle_manager = candle_manager

        # Grand Trend V6: ATR 설정
        self._atr_short_period = period      # ATR(10)
        self._atr_long_period = 50           # ATR(50)

        # 알림 제한 설정
        self._cooldown_seconds = cooldown_seconds
        self._max_alerts_per_day = max_alerts_per_day

        # 종목별 상태
        self._states: Dict[str, AtrAlertState] = {}

        # 동시 요청 제한용 세마포어
        self._semaphore = asyncio.Semaphore(3)

        # 통계
        self.stats = {
            "registered": 0,
            "alerts_sent": 0,
            "signals_checked": 0,
        }

        self._logger.info(
            "[Grand Trend] 알림 관리자 초기화 완료",
            atr_short=self._atr_short_period,
            atr_long=self._atr_long_period,
        )

    async def register_stock(self, stock_code: str, stock_name: str) -> bool:
        """
        조건검색 신호 수신 시 종목 등록

        Args:
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            bool: 등록 성공 여부
        """
        if stock_code in self._states:
            self._logger.debug(f"[Grand Trend] {stock_code} 이미 등록됨")
            return False

        async with self._semaphore:
            try:
                # 1. RealTimeDataManager에 Tier 1 등록 + 캔들 로드
                self._data_manager.register_stock(stock_code, Tier.TIER_1, stock_name)
                await self._data_manager.promote_to_tier1(stock_code)

                # 2. 캐시된 캔들 확인 (Grand Trend V6: EMA200 필요)
                candles_df = self._candle_manager.get_candles(stock_code, Timeframe.M3)

                if candles_df is None or len(candles_df) < MIN_CANDLES_REQUIRED:
                    self._logger.debug(
                        f"[Grand Trend] {stock_code} 캔들 부족: "
                        f"{len(candles_df) if candles_df is not None else 0}개 "
                        f"(최소 {MIN_CANDLES_REQUIRED}개 필요)"
                    )
                    return False

                # 상태 등록 (Grand Trend V6: ATR Trailing Stop 불필요)
                self._states[stock_code] = AtrAlertState(
                    stock_code=stock_code,
                    stock_name=stock_name,
                )

                self.stats["registered"] += 1
                self._logger.info(
                    f"[Grand Trend] 종목 등록: {stock_name}({stock_code})",
                    candle_count=len(candles_df),
                )

                return True

            except Exception as e:
                self._logger.error(f"[Grand Trend] {stock_code} 등록 실패: {e}")
                return False

    async def check_on_candle_complete(self, stock_code: str, candle) -> bool:
        """
        3분봉 완성 시 Grand Trend V6 지저깨 신호 체크

        Grand Trend V6 필터 (PRD 일치):
        - trendFilter: Close > EMA200 AND EMA60 > EMA60[5]
        - zone: Low <= EMA20 AND Close >= EMA60
        - meaningful: CrossUp(C, EMA3) AND 양봉 AND V >= V[1]

        Args:
            stock_code: 종목코드
            candle: 완성된 3분봉 캔들

        Returns:
            bool: 알림 발송 여부
        """
        if stock_code not in self._states:
            return False

        state = self._states[stock_code]
        self.stats["signals_checked"] += 1

        # 쿨다운 + 일일 제한 체크
        if not self._can_alert(state):
            return False

        try:
            # 캐시된 캔들 사용
            candles_df = self._candle_manager.get_candles(stock_code, Timeframe.M3)

            if candles_df is None or len(candles_df) < MIN_CANDLES_REQUIRED:
                return False

            # === Grand Trend V6 지표 계산 ===
            closes = candles_df['close']
            highs = candles_df['high']
            lows = candles_df['low']
            opens = candles_df['open']
            volumes = candles_df['volume']

            # EMA 계산
            ema3 = Indicator.ema(closes, span=3)   # PRD: meaningful에 EMA3 사용
            ema5 = Indicator.ema(closes, span=5)
            ema20 = Indicator.ema(closes, span=20)
            ema60 = Indicator.ema(closes, span=60)
            ema200 = Indicator.ema(closes, span=200)

            # ATR 계산
            atr10 = Indicator.atr(highs, lows, closes, period=self._atr_short_period)
            atr50 = Indicator.atr(highs, lows, closes, period=self._atr_long_period)

            # 현재 봉 데이터
            curr_close = float(closes.iloc[-1])
            curr_open = float(opens.iloc[-1])
            curr_low = float(lows.iloc[-1])
            curr_volume = float(volumes.iloc[-1])

            # 이전 봉 데이터
            prev_close = float(closes.iloc[-2])
            prev_volume = float(volumes.iloc[-2])
            prev_ema3 = float(ema3.iloc[-2])  # PRD: EMA3 사용

            # 현재 지표 값
            curr_ema3 = float(ema3.iloc[-1])  # PRD: EMA3 사용
            curr_ema20 = float(ema20.iloc[-1])
            curr_ema60 = float(ema60.iloc[-1])
            curr_ema200 = float(ema200.iloc[-1])
            ema60_5ago = float(ema60.iloc[-6])  # PRD: trendFilter용 5봉 전 EMA60
            curr_atr10 = float(atr10.iloc[-1])
            curr_atr50 = float(atr50.iloc[-1])

            # === Grand Trend V6 필터 체크 (PRD 일치) ===

            # [trendFilter] EMA200 위 + EMA60 추세 각도: Close > EMA200 AND EMA60 > EMA60[5]
            filter_trend = curr_close > curr_ema200 and curr_ema60 > ema60_5ago

            # [zone] 헌팅 존: Low <= EMA20 AND Close >= EMA60
            filter_zone = curr_low <= curr_ema20 and curr_close >= curr_ema60

            # [meaningful] 의미 있는 반등: CrossUp(C, EMA3) AND 양봉 AND V >= V[1]
            cross_up_ema3 = prev_close < prev_ema3 and curr_close > curr_ema3
            is_bullish = curr_close > curr_open
            volume_up = curr_volume >= prev_volume
            filter_meaningful = cross_up_ema3 and is_bullish and volume_up

            # 필터 체크 로그 (PRD: EMA60 추세 각도 표시)
            self._logger.info(
                f"[Grand Trend] {stock_code} 필터: "
                f"Trend={filter_trend} Zone={filter_zone} Mean={filter_meaningful} | "
                f"C={int(curr_close):,} EMA200={int(curr_ema200):,} "
                f"EMA60={int(curr_ema60):,} EMA60[-5]={int(ema60_5ago):,}"
            )

            # 모든 필터 통과 시 알림 발송
            if filter_trend and filter_zone and filter_meaningful:
                await self._send_alert(
                    state=state,
                    curr_close=int(curr_close),
                    curr_open=int(curr_open),
                    ema3=int(curr_ema3),
                    ema20=int(curr_ema20),
                    ema60=int(curr_ema60),
                    ema60_5ago=int(ema60_5ago),
                    ema200=int(curr_ema200),
                )
                return True

            return False

        except Exception as e:
            self._logger.error(f"[Grand Trend] {stock_code} 신호 체크 실패: {e}")
            return False

    async def _send_alert(
        self,
        state: AtrAlertState,
        curr_close: int,
        curr_open: int,
        ema3: int,
        ema20: int,
        ema60: int,
        ema60_5ago: int,
        ema200: int,
    ) -> None:
        """Grand Trend V6 지저깨 알림 발송 (PRD 일치)"""
        if not self._telegram:
            self._logger.warning("[Grand Trend] 텔레그램 봇 미설정")
            return

        change_rate = (curr_close - curr_open) / curr_open * 100 if curr_open > 0 else 0

        message = f"""[Grand Trend 지저깨] {state.stock_name} ({state.stock_code})
현재가: {curr_close:,}원 ({change_rate:+.2f}%)
EMA200: {ema200:,}원 (트렌드 필터 충족)
EMA60: {ema60:,} > {ema60_5ago:,} (추세 상승)
EMA: 3({ema3:,}) / 20({ema20:,}) / 60({ema60:,})
[헌팅 존 진입 + EMA3 돌파 양봉]"""

        try:
            await self._telegram.send_message(message)
            self._logger.info(
                f"[Grand Trend] 알림 발송: {state.stock_name}({state.stock_code})",
                close=curr_close,
                ema200=ema200,
            )

            # 상태 업데이트
            state.last_alert_time = datetime.now()
            state.alert_count_today += 1
            self.stats["alerts_sent"] += 1

        except Exception as e:
            self._logger.error(f"[Grand Trend] 알림 발송 실패: {e}")

    def _can_alert(self, state: AtrAlertState) -> bool:
        """알림 가능 여부 (쿨다운 + 일일 제한)"""
        # 일일 제한
        if state.alert_count_today >= self._max_alerts_per_day:
            return False

        # 쿨다운
        if state.last_alert_time:
            elapsed = (datetime.now() - state.last_alert_time).total_seconds()
            if elapsed < self._cooldown_seconds:
                return False

        return True

    def reset_daily_counts(self) -> None:
        """일일 알림 카운트 리셋 (매일 09:00 호출)"""
        for state in self._states.values():
            state.alert_count_today = 0
        self._logger.info(f"[ATR Alert] 일일 카운트 리셋: {len(self._states)}개 종목")

    def unregister_stock(self, stock_code: str) -> bool:
        """종목 등록 해제"""
        if stock_code in self._states:
            del self._states[stock_code]
            self._logger.info(f"[ATR Alert] 종목 해제: {stock_code}")
            return True
        return False

    def clear_all(self) -> None:
        """모든 종목 해제 (장 종료 시)"""
        count = len(self._states)
        self._states.clear()
        self._logger.info(f"[ATR Alert] 전체 해제: {count}개 종목")

    def get_registered_stocks(self) -> List[str]:
        """등록된 종목 목록 반환"""
        return list(self._states.keys())

    def get_state(self, stock_code: str) -> Optional[AtrAlertState]:
        """종목 상태 조회"""
        return self._states.get(stock_code)
