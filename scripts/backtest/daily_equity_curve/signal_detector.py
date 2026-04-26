# -*- coding: utf-8 -*-
"""
Daily Equity Curve - Signal Detector

지저깨 신호 탐지 (일봉 기반)
"""

from datetime import date
from typing import List, Tuple, Optional
import pandas as pd
import numpy as np

from .config import BacktestConfig


class SignalDetector:
    """
    지저깨 신호 탐지

    5가지 조건 모두 충족 시 매수 신호:
    1. Angle: EMA60 > EMA60[5] (60일선 우상향)
    2. Zone: low <= EMA20 AND close >= EMA60 (눌림목 진입)
    3. Meaningful: CrossUp(close, EMA3) AND 양봉 AND volume >= volume[1]
    4. BodySize: (close - open) / open >= 0.003 (0.3% 이상)
    5. Above120: close > EMA120 (120선 위)
    """

    def __init__(self, config: BacktestConfig):
        self.config = config

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        필요한 지표 계산

        Args:
            df: OHLCV DataFrame (date, open, high, low, close, volume)

        Returns:
            지표가 추가된 DataFrame
        """
        result = df.copy()

        # EMA 계산 (adjust=False 필수)
        result["ema3"] = result["close"].ewm(span=self.config.ema_short, adjust=False).mean()
        result["ema20"] = result["close"].ewm(span=self.config.ema_mid, adjust=False).mean()
        result["ema60"] = result["close"].ewm(span=self.config.ema_long, adjust=False).mean()
        result["ema120"] = result["close"].ewm(span=self.config.ema_trend, adjust=False).mean()

        # ATR 계산 (Wilder's RMA)
        prev_close = result["close"].shift(1)
        tr1 = result["high"] - result["low"]
        tr2 = abs(result["high"] - prev_close)
        tr3 = abs(result["low"] - prev_close)
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        result["atr"] = tr.ewm(alpha=1/self.config.atr_period, adjust=False).mean()

        # 고점 기준가
        result["highest_high"] = result["high"].rolling(
            window=self.config.base_price_period
        ).max()

        return result

    def detect_signals(
        self,
        df: pd.DataFrame,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> List[Tuple[date, int]]:
        """
        지저깨 신호 탐지

        Args:
            df: 지표가 계산된 DataFrame
            start_date: 탐지 시작일
            end_date: 탐지 종료일

        Returns:
            [(신호일, 종가), ...] 리스트
        """
        signals = []

        # 날짜 필터 (datetime64와 date 비교를 위해 pandas Timestamp 사용)
        if start_date:
            start_ts = pd.Timestamp(start_date)
            df = df[df["date"] >= start_ts]
        if end_date:
            end_ts = pd.Timestamp(end_date)
            df = df[df["date"] <= end_ts]

        if len(df) < self.config.angle_period + 1:
            return signals

        # 조건 계산
        for i in range(self.config.angle_period, len(df)):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1]

            # 1. Angle: EMA60 > EMA60[5] (60일선 우상향)
            ema60_current = row["ema60"]
            ema60_past = df.iloc[i - self.config.angle_period]["ema60"]
            angle_ok = ema60_current > ema60_past

            if not angle_ok:
                continue

            # 2. Zone: low <= EMA20 AND close >= EMA60 (눌림목)
            zone_ok = row["low"] <= row["ema20"] and row["close"] >= row["ema60"]

            if not zone_ok:
                continue

            # 3. Meaningful: CrossUp(close, EMA3) AND 양봉 AND volume >= volume[1]
            # CrossUp: 전일 close < ema3, 당일 close >= ema3
            prev_close = prev_row["close"]
            prev_ema3 = prev_row["ema3"]
            curr_close = row["close"]
            curr_ema3 = row["ema3"]

            cross_up = (prev_close < prev_ema3) and (curr_close >= curr_ema3)
            is_bullish = row["close"] > row["open"]
            volume_ok = row["volume"] >= prev_row["volume"]

            meaningful_ok = cross_up and is_bullish and volume_ok

            if not meaningful_ok:
                continue

            # 4. BodySize: (close - open) / open >= 0.003
            body_size = (row["close"] - row["open"]) / row["open"]
            body_ok = body_size >= self.config.min_body_size

            if not body_ok:
                continue

            # 5. Above120: close > EMA120
            above120_ok = row["close"] > row["ema120"]

            if not above120_ok:
                continue

            # 모든 조건 충족
            signal_date = row["date"]
            if isinstance(signal_date, pd.Timestamp):
                signal_date = signal_date.date()

            signals.append((signal_date, int(row["close"])))

        return signals

    def detect_all_signals(
        self,
        daily_data: dict,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None
    ) -> dict:
        """
        모든 종목의 신호 탐지

        Args:
            daily_data: {stock_code: DataFrame} 딕셔너리
            start_date: 탐지 시작일
            end_date: 탐지 종료일

        Returns:
            {stock_code: [(신호일, 종가), ...]} 딕셔너리
        """
        all_signals = {}

        for stock_code, df in daily_data.items():
            # 지표 계산
            df_with_indicators = self.calculate_indicators(df)

            # 신호 탐지
            signals = self.detect_signals(
                df_with_indicators,
                start_date=start_date,
                end_date=end_date
            )

            if signals:
                all_signals[stock_code] = signals

        return all_signals
