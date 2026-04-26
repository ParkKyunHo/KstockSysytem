"""
통합 기술적 지표 라이브러리 (Phase 1 리팩토링)

모든 전략(V6 SNIPER_TRAP, V7 Purple-ReAbs)에서 공통으로 사용하는 기술적 지표.

CLAUDE.md 불변 조건:
- EMA adjust=False (모든 EMA 계산)

사용법:
    from src.core.indicator_library import IndicatorLibrary

    ema3 = IndicatorLibrary.ema(df['close'], span=3)
    atr = IndicatorLibrary.atr(df['high'], df['low'], df['close'], period=10)
"""

from typing import Tuple
import pandas as pd
import numpy as np


class IndicatorLibrary:
    """
    공용 기술적 지표 라이브러리

    모든 메서드는 정적(static)으로, pandas Series를 입력받아
    지표가 계산된 Series를 반환합니다.

    V6/V7 전략 모두에서 사용되며, 코드 중복을 제거하고
    일관된 계산 방식을 보장합니다.
    """

    # =========================================
    # 이동평균 (Moving Averages)
    # =========================================

    @staticmethod
    def ema(series: pd.Series, span: int, adjust: bool = False) -> pd.Series:
        """
        지수이동평균 (Exponential Moving Average)

        CLAUDE.md 불변 조건: adjust=False (기본값)

        Args:
            series: 가격/지표 시리즈
            span: 기간 (예: 3, 20, 60, 200)
            adjust: EMA 조정 여부 (기본 False - CLAUDE.md 준수)

        Returns:
            EMA 시리즈
        """
        return series.ewm(span=span, adjust=adjust).mean()

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """
        단순이동평균 (Simple Moving Average)

        Args:
            series: 가격/지표 시리즈
            period: 기간

        Returns:
            SMA 시리즈
        """
        return series.rolling(window=period).mean()

    @staticmethod
    def rma(series: pd.Series, period: int) -> pd.Series:
        """
        Wilder's Moving Average (RMA)

        TradingView의 ATR 계산에 사용되는 방식.
        alpha = 1/period

        Args:
            series: 시리즈
            period: 기간

        Returns:
            RMA 시리즈
        """
        return series.ewm(alpha=1/period, adjust=False).mean()

    # =========================================
    # 변동성 지표 (Volatility)
    # =========================================

    @staticmethod
    def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """
        True Range (진정한 범위)

        갭 상승/하락을 포함한 실제 가격 변동폭.
        TR = max(H-L, |H-PrevClose|, |L-PrevClose|)

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈

        Returns:
            True Range 시리즈
        """
        prev_close = close.shift(1)
        tr1 = high - low  # 당일 고저차
        tr2 = abs(high - prev_close)  # 갭 상승
        tr3 = abs(low - prev_close)  # 갭 하락
        return pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    @staticmethod
    def atr(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14
    ) -> pd.Series:
        """
        Average True Range (ATR) - TradingView RMA 방식

        변동성 지표로, 트레일링 스탑 계산에 사용.
        RMA (Wilder's) 사용: alpha = 1/period

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈
            period: 기간 (기본값 14)

        Returns:
            ATR 시리즈
        """
        tr = IndicatorLibrary.true_range(high, low, close)
        return IndicatorLibrary.rma(tr, period)

    # =========================================
    # 최고/최저 (High/Low)
    # =========================================

    @staticmethod
    def highest_high(series: pd.Series, period: int) -> pd.Series:
        """
        N봉 최고가

        Args:
            series: 고가 시리즈
            period: 기간

        Returns:
            최고가 시리즈
        """
        return series.rolling(window=period).max()

    @staticmethod
    def lowest_low(series: pd.Series, period: int) -> pd.Series:
        """
        N봉 최저가

        Args:
            series: 저가 시리즈
            period: 기간

        Returns:
            최저가 시리즈
        """
        return series.rolling(window=period).min()

    @staticmethod
    def h1l1(
        high: pd.Series,
        low: pd.Series,
        period: int = 40
    ) -> Tuple[pd.Series, pd.Series]:
        """
        H1/L1 - N봉 최고가/최저가 쌍

        V7 Purple 전략의 상승률 계산용.

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            period: 기간 (기본 40)

        Returns:
            (H1, L1) 튜플
        """
        H1 = IndicatorLibrary.highest_high(high, period)
        L1 = IndicatorLibrary.lowest_low(low, period)
        return H1, L1

    @staticmethod
    def h2l2(
        high: pd.Series,
        low: pd.Series,
        period: int = 20
    ) -> Tuple[pd.Series, pd.Series]:
        """
        H2/L2 - N봉 최고가/최저가 쌍

        V7 Purple 전략의 수렴률 계산용.

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            period: 기간 (기본 20)

        Returns:
            (H2, L2) 튜플
        """
        H2 = IndicatorLibrary.highest_high(high, period)
        L2 = IndicatorLibrary.lowest_low(low, period)
        return H2, L2

    # =========================================
    # 돌파/크로스 (Cross)
    # =========================================

    @staticmethod
    def crossup(series: pd.Series, threshold: pd.Series) -> pd.Series:
        """
        상향 돌파 (CrossUp)

        이전 봉: series < threshold
        현재 봉: series >= threshold

        Args:
            series: 비교 대상 시리즈 (예: close)
            threshold: 기준선 시리즈 (예: EMA3)

        Returns:
            bool 시리즈 (True: 상향 돌파)
        """
        prev_below = series.shift(1) < threshold.shift(1)
        curr_above = series >= threshold
        return prev_below & curr_above

    @staticmethod
    def crossdown(series: pd.Series, threshold: pd.Series) -> pd.Series:
        """
        하향 돌파 (CrossDown)

        이전 봉: series > threshold
        현재 봉: series <= threshold

        Args:
            series: 비교 대상 시리즈
            threshold: 기준선 시리즈

        Returns:
            bool 시리즈 (True: 하향 돌파)
        """
        prev_above = series.shift(1) > threshold.shift(1)
        curr_below = series <= threshold
        return prev_above & curr_below

    @staticmethod
    def is_golden_cross(fast_ma: pd.Series, slow_ma: pd.Series) -> pd.Series:
        """
        골든 크로스 (빠른 MA가 느린 MA를 상향 돌파)

        Args:
            fast_ma: 빠른 이동평균 (예: EMA3)
            slow_ma: 느린 이동평균 (예: EMA20)

        Returns:
            bool 시리즈
        """
        return IndicatorLibrary.crossup(fast_ma, slow_ma)

    @staticmethod
    def is_dead_cross(fast_ma: pd.Series, slow_ma: pd.Series) -> pd.Series:
        """
        데드 크로스 (빠른 MA가 느린 MA를 하향 돌파)

        Args:
            fast_ma: 빠른 이동평균
            slow_ma: 느린 이동평균

        Returns:
            bool 시리즈
        """
        return IndicatorLibrary.crossdown(fast_ma, slow_ma)

    # =========================================
    # 캔들 분석 (Candle)
    # =========================================

    @staticmethod
    def is_bullish(open_price: pd.Series, close: pd.Series) -> pd.Series:
        """
        양봉 여부

        Args:
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            bool 시리즈 (True: 양봉)
        """
        return close > open_price

    @staticmethod
    def is_bearish(open_price: pd.Series, close: pd.Series) -> pd.Series:
        """
        음봉 여부

        Args:
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            bool 시리즈 (True: 음봉)
        """
        return close < open_price

    @staticmethod
    def candle_body(open_price: pd.Series, close: pd.Series) -> pd.Series:
        """
        봉 몸통 크기 (종가 - 시가)

        양수: 양봉, 음수: 음봉

        Args:
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            몸통 크기 시리즈
        """
        return close - open_price

    @staticmethod
    def upper_shadow(
        high: pd.Series,
        open_price: pd.Series,
        close: pd.Series
    ) -> pd.Series:
        """
        윗꼬리 길이

        Args:
            high: 고가 시리즈
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            윗꼬리 길이 시리즈
        """
        body_top = pd.concat([open_price, close], axis=1).max(axis=1)
        return high - body_top

    @staticmethod
    def lower_shadow(
        low: pd.Series,
        open_price: pd.Series,
        close: pd.Series
    ) -> pd.Series:
        """
        아랫꼬리 길이

        Args:
            low: 저가 시리즈
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            아랫꼬리 길이 시리즈
        """
        body_bottom = pd.concat([open_price, close], axis=1).min(axis=1)
        return body_bottom - low

    # =========================================
    # 기타 지표 (Misc)
    # =========================================

    @staticmethod
    def hlc3(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """
        HLC3 (Typical Price)

        VWAP 근사값으로 사용. 구조 경고 판정에 활용.
        수식: (High + Low + Close) / 3

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈

        Returns:
            HLC3 시리즈
        """
        return (high + low + close) / 3

    @staticmethod
    def disparity(price: pd.Series, ma: pd.Series) -> pd.Series:
        """
        이격도 (Disparity)

        가격이 이동평균에서 얼마나 벗어났는지 백분율.
        이격도 = (현재가 / 이동평균) * 100

        Args:
            price: 현재가 시리즈
            ma: 이동평균 시리즈

        Returns:
            이격도 시리즈 (%)
        """
        return (price / ma.replace(0, np.nan)) * 100

    @staticmethod
    def ma_slope(ma: pd.Series, period: int = 3) -> pd.Series:
        """
        이동평균 기울기

        Args:
            ma: 이동평균 시리즈
            period: 기울기 계산 기간

        Returns:
            기울기 시리즈 (양수: 우상향)
        """
        return ma.diff(period)

    @staticmethod
    def is_uptrend(ma: pd.Series, period: int = 3) -> pd.Series:
        """
        우상향 여부

        Args:
            ma: 이동평균 시리즈
            period: 판단 기간

        Returns:
            bool 시리즈 (True: 우상향)
        """
        return IndicatorLibrary.ma_slope(ma, period) > 0

    @staticmethod
    def price_change_rate(price: pd.Series, period: int = 1) -> pd.Series:
        """
        가격 변화율 (%)

        Args:
            price: 가격 시리즈
            period: 비교 기간

        Returns:
            변화율 시리즈 (%)
        """
        return price.pct_change(period) * 100

    @staticmethod
    def volume_ratio(volumes: pd.Series, span: int = 20) -> pd.Series:
        """
        거래량 비율 (현재 거래량 / 평균 거래량)

        Args:
            volumes: 거래량 시리즈
            span: 평균 계산 기간

        Returns:
            거래량 비율 시리즈
        """
        avg_vol = IndicatorLibrary.ema(volumes, span)
        return volumes / avg_vol.replace(0, np.nan)

    @staticmethod
    def atr_stop(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
        multiplier: float = 2.5
    ) -> pd.Series:
        """
        ATR Stop Line (Trailing 미적용 원시값)

        수식: Highest(H, Period) - ATR(Period) x Multiplier

        Trailing 로직은 별도 관리 필요:
        - 상승 시: 새 값으로 갱신
        - 하락 시: 기존 값 유지

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈
            period: 기간
            multiplier: ATR 배수 (기본 2.5)

        Returns:
            ATR Stop 시리즈
        """
        highest = IndicatorLibrary.highest_high(high, period)
        atr_val = IndicatorLibrary.atr(high, low, close, period)
        return highest - (atr_val * multiplier)
