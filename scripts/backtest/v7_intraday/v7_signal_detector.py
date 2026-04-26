# -*- coding: utf-8 -*-
"""
V7 Purple 3분봉 백테스트 - V7 신호 탐지

V7 프로덕션 코드(src/core/indicator_purple.py, signal_detector_purple.py)와 동일한 로직
5가지 조건: PurpleOK, Trend, Zone, ReAbsStart, Trigger
"""

from datetime import datetime, time
from typing import Optional, List, Dict, Any, Tuple
import pandas as pd
import numpy as np

from .config import BacktestConfig, V7Signal


class V7SignalDetector:
    """
    V7 Purple 신호 탐지기 (백테스트용)

    프로덕션 PurpleIndicator, PurpleSignalDetector 로직을 동일하게 구현
    """

    # Score 가중치 (수정 불가 - CLAUDE.md 2.3)
    PRICE_VWAP_MULT = 2.0      # (C/W - 1) × 2
    FUND_LZ_MULT = 0.8         # LZ × 0.8
    RECOVERY_MULT = 1.2        # recovery × 1.2

    # 지표 기간
    WEIGHTED_PRICE_PERIOD = 40
    FUND_ZSCORE_PERIOD = 20
    SCORE_SMOOTH_PERIOD = 10
    H1L1_PERIOD = 40
    H2L2_PERIOD = 20
    RECOVERY_LOOKBACK = 20

    def __init__(self, config: BacktestConfig, logger):
        self.config = config
        self.logger = logger

    # ============================================================
    # EMA 계산 (adjust=False - CLAUDE.md 1.2)
    # ============================================================

    def ema(self, series: pd.Series, span: int) -> pd.Series:
        """지수이동평균 (adjust=False 필수)"""
        return series.ewm(span=span, adjust=False).mean()

    # ============================================================
    # Purple 지표 계산
    # ============================================================

    def money(self, df: pd.DataFrame) -> pd.Series:
        """거래대금 M = Close × Volume"""
        return df['close'] * df['volume']

    def weighted_price(self, df: pd.DataFrame, period: int = WEIGHTED_PRICE_PERIOD) -> pd.Series:
        """가중평균가격 W = sum(C × M, period) / sum(M, period)"""
        M = self.money(df)
        C = df['close']
        numerator = (C * M).rolling(window=period).sum()
        denominator = M.rolling(window=period).sum()
        return numerator / denominator.replace(0, np.nan)

    def log_normalized(self, df: pd.DataFrame) -> pd.Series:
        """로그 정규화 LG = log(M / max(H - L, 0.01))"""
        M = self.money(df)
        range_hl = (df['high'] - df['low']).clip(lower=0.01)
        return np.log(M / range_hl)

    def fund_zscore(self, df: pd.DataFrame, period: int = FUND_ZSCORE_PERIOD) -> pd.Series:
        """자금 Z-Score LZ = (LG - EMA(LG, period)) / max(MAD, 0.0001)"""
        LG = self.log_normalized(df)
        lg_ema = self.ema(LG, period)
        deviation = LG - lg_ema
        mad = self.ema(deviation.abs(), period)
        return deviation / mad.clip(lower=0.0001)

    def recovery_rate(self, df: pd.DataFrame, period: int = RECOVERY_LOOKBACK) -> pd.Series:
        """회복률 = (C - lowest(L, period)) / period"""
        lowest = df['low'].rolling(window=period).min()
        return (df['close'] - lowest) / period

    def score(self, df: pd.DataFrame, smooth_period: int = SCORE_SMOOTH_PERIOD) -> pd.Series:
        """
        Purple Score 계산

        S = EMA((C/W - 1)*2 + LZ*0.8 + recovery*1.2, 10)
        """
        W = self.weighted_price(df)
        LZ = self.fund_zscore(df)
        recovery = self.recovery_rate(df)
        C = df['close']

        price_component = (C / W.replace(0, np.nan) - 1) * self.PRICE_VWAP_MULT
        recovery_component = recovery * self.RECOVERY_MULT
        fund_component = LZ * self.FUND_LZ_MULT

        raw_score = price_component + fund_component + recovery_component
        return self.ema(raw_score, smooth_period)

    def rise_ratio(self, df: pd.DataFrame, period: int = H1L1_PERIOD) -> pd.Series:
        """상승률 = H1/L1 - 1"""
        H1 = df['high'].rolling(window=period).max()
        L1 = df['low'].rolling(window=period).min()
        return (H1 / L1.replace(0, np.nan)) - 1

    def convergence_ratio(self, df: pd.DataFrame, period: int = H2L2_PERIOD) -> pd.Series:
        """수렴률 = H2/L2 - 1"""
        H2 = df['high'].rolling(window=period).max()
        L2 = df['low'].rolling(window=period).min()
        return (H2 / L2.replace(0, np.nan)) - 1

    # ============================================================
    # 5가지 신호 조건 확인
    # ============================================================

    def check_purple_ok(self, df: pd.DataFrame, idx: int) -> Tuple[bool, Dict]:
        """
        PurpleOK 필터

        PurpleOK = (H1/L1 - 1) >= 4% AND (H2/L2 - 1) <= 7% AND M >= 5억
        """
        if idx < self.H1L1_PERIOD:
            return False, {}

        rise = self.rise_ratio(df).iloc[idx]
        conv = self.convergence_ratio(df).iloc[idx]
        M = self.money(df).iloc[idx]

        cond1 = rise >= self.config.min_rise_pct
        cond2 = conv <= self.config.max_convergence_pct
        cond3 = M >= self.config.min_bar_value

        return cond1 and cond2 and cond3, {
            "rise_pct": rise * 100,
            "convergence_pct": conv * 100,
            "money": M,
            "money_billion": M / 1_000_000_000
        }

    def check_trend(self, df: pd.DataFrame, idx: int) -> Tuple[bool, Dict]:
        """
        Trend 조건

        Trend = EMA60 > EMA60[3]
        """
        if idx < 60 + self.config.trend_lookback:
            return False, {}

        ema60 = self.ema(df['close'], 60)
        current = ema60.iloc[idx]
        prev = ema60.iloc[idx - self.config.trend_lookback]

        return current > prev, {
            "ema60": current,
            "ema60_prev": prev
        }

    def check_zone(self, df: pd.DataFrame, idx: int) -> Tuple[bool, Dict]:
        """
        Zone 조건

        Zone = C >= EMA60 × 0.995
        """
        if idx < 60:
            return False, {}

        close = df['close'].iloc[idx]
        ema60 = self.ema(df['close'], 60).iloc[idx]
        threshold = ema60 * (1 - self.config.zone_tolerance)

        return close >= threshold, {
            "close": close,
            "ema60": ema60,
            "zone_threshold": threshold,
            "zone_pct": (close / ema60 - 1) * 100 if ema60 > 0 else 0
        }

    def check_reabs_start(self, df: pd.DataFrame, idx: int) -> Tuple[bool, Dict]:
        """
        ReAbsStart 조건

        ReAbsStart = S > S[1]
        """
        if idx < 20:
            return False, {}

        score_series = self.score(df)
        current = score_series.iloc[idx]
        prev = score_series.iloc[idx - 1]

        return current > prev, {
            "score": current,
            "score_prev": prev,
            "score_delta": current - prev
        }

    def check_trigger(self, df: pd.DataFrame, idx: int) -> Tuple[bool, Dict]:
        """
        Trigger 조건

        Trigger = CrossUp(C, EMA3) AND 양봉
        """
        if idx < 3:
            return False, {}

        close = df['close']
        ema3 = self.ema(close, 3)

        # CrossUp: 이전 봉 close < EMA3, 현재 봉 close >= EMA3
        prev_close = close.iloc[idx - 1]
        prev_ema3 = ema3.iloc[idx - 1]
        curr_close = close.iloc[idx]
        curr_ema3 = ema3.iloc[idx]

        crossup = (prev_close < prev_ema3) and (curr_close >= curr_ema3)

        # 양봉: close > open
        is_bullish = close.iloc[idx] > df['open'].iloc[idx]

        return crossup and is_bullish, {
            "ema3": curr_ema3,
            "crossup": crossup,
            "is_bullish": is_bullish
        }

    def check_all_conditions(self, df: pd.DataFrame, idx: int) -> Tuple[bool, Dict]:
        """
        5가지 조건 모두 확인

        Signal = PurpleOK AND Trend AND Zone AND ReAbsStart AND Trigger
        """
        purple_ok, purple_details = self.check_purple_ok(df, idx)
        trend, trend_details = self.check_trend(df, idx)
        zone, zone_details = self.check_zone(df, idx)
        reabs, reabs_details = self.check_reabs_start(df, idx)
        trigger, trigger_details = self.check_trigger(df, idx)

        all_met = purple_ok and trend and zone and reabs and trigger

        conditions = {
            "purple_ok": purple_ok,
            "trend": trend,
            "zone": zone,
            "reabs_start": reabs,
            "trigger": trigger
        }

        details = {
            **purple_details,
            **trend_details,
            **zone_details,
            **reabs_details,
            **trigger_details,
            "conditions": conditions,
            "conditions_met": sum(conditions.values())
        }

        return all_met, details

    # ============================================================
    # 신호 탐지 메인
    # ============================================================

    def detect_signals(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> List[V7Signal]:
        """
        DataFrame에서 V7 신호 탐지

        Args:
            stock_code: 종목코드
            stock_name: 종목명
            df: 3분봉 DataFrame (datetime index, open/high/low/close/volume columns)

        Returns:
            V7Signal 리스트
        """
        if df is None or len(df) < self.config.min_candles_for_signal:
            return []

        signals = []

        # 인덱스가 datetime이면 리셋
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()
            datetime_col = 'datetime' if 'datetime' in df.columns else 'index'
            df.rename(columns={'index': 'datetime'}, inplace=True)

        for idx in range(self.config.min_candles_for_signal, len(df)):
            row = df.iloc[idx]
            signal_time = row['datetime'] if 'datetime' in df.columns else row.name

            # datetime 확인
            if isinstance(signal_time, str):
                signal_time = pd.to_datetime(signal_time)

            # 시간대 필터 (09:05 ~ 15:20)
            current_time = signal_time.time()
            if current_time < self.config.signal_start_time:
                continue
            if current_time > self.config.signal_end_time:
                continue

            # 10시대 진입 제외 (10:00~10:59) - 백테스트 결과 승률 19.5%로 최악
            if signal_time.hour == 10:
                continue

            # 3분봉 거래대금 50억 이상 필터 (주도주)
            candle_money = row['close'] * row['volume']
            if candle_money < 5_000_000_000:  # 50억
                continue

            # 5조건 확인
            is_signal, details = self.check_all_conditions(df, idx)

            if is_signal:
                ema3 = self.ema(df['close'], 3).iloc[idx]
                ema20 = self.ema(df['close'], 20).iloc[idx]
                ema60 = self.ema(df['close'], 60).iloc[idx]

                signal = V7Signal(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    signal_datetime=signal_time,
                    signal_price=int(row['close']),
                    score=details.get('score', 0),
                    score_prev=details.get('score_prev', 0),
                    rise_pct=details.get('rise_pct', 0),
                    convergence_pct=details.get('convergence_pct', 0),
                    money_billion=details.get('money_billion', 0),
                    zone_pct=details.get('zone_pct', 0),
                    ema3=ema3,
                    ema20=ema20,
                    ema60=ema60,
                    conditions=details.get('conditions', {})
                )
                signals.append(signal)

        return signals

    def get_first_signal(
        self,
        stock_code: str,
        stock_name: str,
        df: pd.DataFrame
    ) -> Optional[V7Signal]:
        """당일 첫 번째 신호만 반환 (실제 거래와 동일하게 1회 진입)"""
        signals = self.detect_signals(stock_code, stock_name, df)
        return signals[0] if signals else None

    # ============================================================
    # 분석용 유틸리티
    # ============================================================

    def get_condition_pass_rates(
        self,
        stock_code: str,
        df: pd.DataFrame
    ) -> Dict[str, float]:
        """조건별 통과율 계산"""
        if df is None or len(df) < self.config.min_candles_for_signal:
            return {}

        # 인덱스가 datetime이면 리셋
        if isinstance(df.index, pd.DatetimeIndex):
            df = df.reset_index()

        counts = {
            "purple_ok": 0,
            "trend": 0,
            "zone": 0,
            "reabs_start": 0,
            "trigger": 0,
            "total": 0
        }

        for idx in range(self.config.min_candles_for_signal, len(df)):
            row = df.iloc[idx]
            signal_time = row.get('datetime', row.name)

            if isinstance(signal_time, str):
                signal_time = pd.to_datetime(signal_time)

            current_time = signal_time.time()
            if current_time < self.config.signal_start_time:
                continue
            if current_time > self.config.signal_end_time:
                continue

            counts["total"] += 1

            purple_ok, _ = self.check_purple_ok(df, idx)
            trend, _ = self.check_trend(df, idx)
            zone, _ = self.check_zone(df, idx)
            reabs, _ = self.check_reabs_start(df, idx)
            trigger, _ = self.check_trigger(df, idx)

            if purple_ok:
                counts["purple_ok"] += 1
            if trend:
                counts["trend"] += 1
            if zone:
                counts["zone"] += 1
            if reabs:
                counts["reabs_start"] += 1
            if trigger:
                counts["trigger"] += 1

        if counts["total"] == 0:
            return {}

        rates = {}
        for cond in ["purple_ok", "trend", "zone", "reabs_start", "trigger"]:
            rates[cond] = counts[cond] / counts["total"] * 100

        return rates

    def calculate_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """모든 지표를 계산하여 DataFrame에 추가"""
        result = df.copy()

        result['ema3'] = self.ema(df['close'], 3)
        result['ema20'] = self.ema(df['close'], 20)
        result['ema60'] = self.ema(df['close'], 60)
        result['score'] = self.score(df)
        result['rise_ratio'] = self.rise_ratio(df)
        result['convergence_ratio'] = self.convergence_ratio(df)
        result['money'] = self.money(df)

        return result
