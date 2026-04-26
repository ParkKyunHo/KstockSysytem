# -*- coding: utf-8 -*-
"""
신호 탐지 모듈

거래대금 1000억+ 봉에서 EMA 근접 신호 탐지
Lookahead bias 방지: 봉 마감 후 신호 판단 -> 다음 봉 시가 진입
"""

from datetime import date
from typing import List, Optional, Tuple
import pandas as pd

from .config import EMASplitBuyConfig, SplitBuySignal
from .indicators import is_near_ema5, is_near_ema8, get_warmup_period


class SignalDetector:
    """신호 탐지기"""

    def __init__(self, config: EMASplitBuyConfig, logger=None):
        self.config = config
        self._logger = logger

    def detect_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str
    ) -> List[SplitBuySignal]:
        """
        EMA 근접 신호 탐지

        거래대금 1000억 이상인 봉에서 5일선/8일선 근접 신호 탐지

        Args:
            df: 지표가 계산된 일봉 데이터
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            신호 리스트
        """
        signals = []
        warmup = get_warmup_period()

        # 거래대금 필터
        min_value = self.config.min_trading_value

        for i in range(warmup, len(df)):
            row = df.iloc[i]

            # 거래대금 체크
            trading_value = row.get('trading_value', 0)
            if trading_value < min_value:
                continue

            close = row['close']
            ema5 = row['ema5']
            ema8 = row['ema8']
            signal_date = row['date']

            # 5일선 근접 체크
            if is_near_ema5(close, ema5, self.config.ema5_proximity_pct):
                dist_pct = abs(close - ema5) / ema5 * 100
                signals.append(SplitBuySignal(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    signal_date=signal_date,
                    signal_price=int(close),
                    signal_type="EMA5",
                    ema5=ema5,
                    ema8=ema8,
                    distance_pct=dist_pct,
                    trading_value=int(trading_value)
                ))

            # 8일선 근접 체크 (5일선과 동시 근접 시 5일선만 인정)
            elif is_near_ema8(close, ema8, self.config.ema8_proximity_pct):
                dist_pct = abs(close - ema8) / ema8 * 100
                signals.append(SplitBuySignal(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    signal_date=signal_date,
                    signal_price=int(close),
                    signal_type="EMA8",
                    ema5=ema5,
                    ema8=ema8,
                    distance_pct=dist_pct,
                    trading_value=int(trading_value)
                ))

        return signals

    def detect_first_buy_signals(
        self,
        df: pd.DataFrame,
        stock_code: str,
        stock_name: str
    ) -> List[SplitBuySignal]:
        """
        1차 매수 신호만 탐지 (EMA5 근접)

        Args:
            df: 지표가 계산된 일봉 데이터
            stock_code: 종목코드
            stock_name: 종목명

        Returns:
            1차 매수 신호 리스트 (EMA5 근접만)
        """
        signals = []
        warmup = get_warmup_period()
        min_value = self.config.min_trading_value

        for i in range(warmup, len(df)):
            row = df.iloc[i]

            # 거래대금 체크
            trading_value = row.get('trading_value', 0)
            if trading_value < min_value:
                continue

            close = row['close']
            ema5 = row['ema5']
            ema8 = row['ema8']
            signal_date = row['date']

            # 5일선 근접 체크만
            if is_near_ema5(close, ema5, self.config.ema5_proximity_pct):
                dist_pct = abs(close - ema5) / ema5 * 100
                signals.append(SplitBuySignal(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    signal_date=signal_date,
                    signal_price=int(close),
                    signal_type="EMA5",
                    ema5=ema5,
                    ema8=ema8,
                    distance_pct=dist_pct,
                    trading_value=int(trading_value)
                ))

        return signals

    def check_second_buy_signal(
        self,
        df: pd.DataFrame,
        check_date: date
    ) -> Tuple[bool, Optional[float]]:
        """
        2차 매수 신호 체크 (EMA8 근접)

        Args:
            df: 지표가 계산된 일봉 데이터
            check_date: 체크할 날짜

        Returns:
            (신호 여부, 거리 %)
        """
        row = df[df['date'] == check_date]
        if row.empty:
            return False, None

        row = row.iloc[0]

        # 거래대금 체크
        trading_value = row.get('trading_value', 0)
        if trading_value < self.config.min_trading_value:
            return False, None

        close = row['close']
        ema8 = row['ema8']

        if is_near_ema8(close, ema8, self.config.ema8_proximity_pct):
            dist_pct = abs(close - ema8) / ema8 * 100
            return True, dist_pct

        return False, None

    def check_both_ema_proximity(
        self,
        df: pd.DataFrame,
        check_date: date
    ) -> Tuple[bool, bool]:
        """
        5일선과 8일선 모두 근접한지 체크

        Args:
            df: 지표가 계산된 일봉 데이터
            check_date: 체크할 날짜

        Returns:
            (5일선 근접 여부, 8일선 근접 여부)
        """
        row = df[df['date'] == check_date]
        if row.empty:
            return False, False

        row = row.iloc[0]
        close = row['close']
        ema5 = row['ema5']
        ema8 = row['ema8']

        near_ema5 = is_near_ema5(close, ema5, self.config.ema5_proximity_pct)
        near_ema8 = is_near_ema8(close, ema8, self.config.ema8_proximity_pct)

        return near_ema5, near_ema8

    def get_signal_stats(
        self,
        signals: List[SplitBuySignal]
    ) -> dict:
        """
        신호 통계

        Args:
            signals: 신호 리스트

        Returns:
            통계 딕셔너리
        """
        if not signals:
            return {
                "total": 0,
                "ema5_count": 0,
                "ema8_count": 0,
                "avg_distance_pct": 0
            }

        ema5_signals = [s for s in signals if s.signal_type == "EMA5"]
        ema8_signals = [s for s in signals if s.signal_type == "EMA8"]

        return {
            "total": len(signals),
            "ema5_count": len(ema5_signals),
            "ema8_count": len(ema8_signals),
            "avg_distance_pct": sum(s.distance_pct for s in signals) / len(signals)
        }
