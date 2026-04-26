"""
기술적 지표 계산 모듈 (V6.2-Q)

SNIPER_TRAP 전략에 필요한 기술적 지표를 계산합니다:
- EMA (지수이동평균): 3선, 20선, 60선, 200선
- SMA (단순이동평균)
- ATR (Average True Range): 변동성 지표
- Volume Average (거래량 평균)

Phase 1 리팩토링:
- 공용 메서드는 IndicatorLibrary로 위임
- 기존 API 100% 호환 유지
"""

from typing import Optional
import pandas as pd
import numpy as np

from src.core.indicator_library import IndicatorLibrary


class Indicator:
    """
    기술적 지표 계산 유틸리티

    모든 메서드는 정적(static)으로, pandas Series를 입력받아
    지표가 계산된 Series를 반환합니다.

    Usage:
        df['ema3'] = Indicator.ema(df['close'], span=3)
        df['ceiling20'] = Indicator.ceiling(df['high'], period=20)
    """

    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        """
        지수이동평균 (Exponential Moving Average)

        Args:
            series: 가격 시리즈 (보통 종가)
            span: 기간 (예: 3, 20, 60)

        Returns:
            EMA 시리즈
        """
        return IndicatorLibrary.ema(series, span)

    @staticmethod
    def sma(series: pd.Series, period: int) -> pd.Series:
        """
        단순이동평균 (Simple Moving Average)

        Args:
            series: 가격 시리즈
            period: 기간

        Returns:
            SMA 시리즈
        """
        return IndicatorLibrary.sma(series, period)

    @staticmethod
    def avg_volume(volumes: pd.Series, span: int = 20) -> pd.Series:
        """
        거래량 이동평균 (EMA)

        Args:
            volumes: 거래량 시리즈
            span: 기간

        Returns:
            거래량 EMA 시리즈
        """
        return IndicatorLibrary.ema(volumes, span)

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
        return IndicatorLibrary.volume_ratio(volumes, span)

    @staticmethod
    def disparity(price: pd.Series, ma: pd.Series) -> pd.Series:
        """
        이격도 (Disparity)

        가격이 이동평균에서 얼마나 벗어났는지를 백분율로 표시합니다.
        이격도 = (현재가 / 이동평균) * 100

        Args:
            price: 현재가 시리즈
            ma: 이동평균 시리즈

        Returns:
            이격도 시리즈 (%)
        """
        return IndicatorLibrary.disparity(price, ma)

    @staticmethod
    def ma_slope(ma: pd.Series, period: int = 3) -> pd.Series:
        """
        이동평균 기울기 (우상향/우하향 판단)

        Args:
            ma: 이동평균 시리즈
            period: 기울기 계산 기간

        Returns:
            기울기 시리즈 (양수: 우상향, 음수: 우하향)
        """
        return IndicatorLibrary.ma_slope(ma, period)

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
        return IndicatorLibrary.is_uptrend(ma, period)

    @staticmethod
    def is_golden_cross(fast_ma: pd.Series, slow_ma: pd.Series) -> pd.Series:
        """
        골든 크로스 (빠른 MA가 느린 MA를 상향 돌파)

        Args:
            fast_ma: 빠른 이동평균 (예: 3선)
            slow_ma: 느린 이동평균 (예: 20선)

        Returns:
            bool 시리즈 (True: 크로스 발생)
        """
        return IndicatorLibrary.is_golden_cross(fast_ma, slow_ma)

    @staticmethod
    def is_dead_cross(fast_ma: pd.Series, slow_ma: pd.Series) -> pd.Series:
        """
        데드 크로스 (빠른 MA가 느린 MA를 하향 돌파)

        Args:
            fast_ma: 빠른 이동평균
            slow_ma: 느린 이동평균

        Returns:
            bool 시리즈 (True: 크로스 발생)
        """
        return IndicatorLibrary.is_dead_cross(fast_ma, slow_ma)

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
        return IndicatorLibrary.candle_body(open_price, close)

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
        return IndicatorLibrary.is_bullish(open_price, close)

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
        return IndicatorLibrary.is_bearish(open_price, close)

    @staticmethod
    def upper_shadow(high: pd.Series, open_price: pd.Series, close: pd.Series) -> pd.Series:
        """
        윗꼬리 길이

        Args:
            high: 고가 시리즈
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            윗꼬리 길이 시리즈
        """
        return IndicatorLibrary.upper_shadow(high, open_price, close)

    @staticmethod
    def lower_shadow(low: pd.Series, open_price: pd.Series, close: pd.Series) -> pd.Series:
        """
        아랫꼬리 길이

        Args:
            low: 저가 시리즈
            open_price: 시가 시리즈
            close: 종가 시리즈

        Returns:
            아랫꼬리 길이 시리즈
        """
        return IndicatorLibrary.lower_shadow(low, open_price, close)

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
        return IndicatorLibrary.price_change_rate(price, period)

    @staticmethod
    def highest_high(highs: pd.Series, period: int) -> pd.Series:
        """
        N봉 중 최고가

        Args:
            highs: 고가 시리즈
            period: 기간

        Returns:
            최고가 시리즈
        """
        return IndicatorLibrary.highest_high(highs, period)

    @staticmethod
    def lowest_low(lows: pd.Series, period: int) -> pd.Series:
        """
        N봉 중 최저가

        Args:
            lows: 저가 시리즈
            period: 기간

        Returns:
            최저가 시리즈
        """
        return IndicatorLibrary.lowest_low(lows, period)

    # ========================================
    # Grand Trend V6.2-A: VWAP 근사값 (구조 경고용)
    # ========================================

    @staticmethod
    def hlc3(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """
        HLC3 (Typical Price) - VWAP 근사값

        Grand Trend V6.2-A에서 구조 경고(Structure Warning) 판정에 사용됩니다.
        실제 VWAP는 거래량 가중 평균이지만, 단순 평균으로 근사합니다.

        수식: (High + Low + Close) / 3

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈

        Returns:
            HLC3 (Typical Price) 시리즈
        """
        return IndicatorLibrary.hlc3(high, low, close)

    # ========================================
    # ATR 관련 지표 (PRD v3.2.4 - 3분봉 지저깨 알림용)
    # ========================================

    @staticmethod
    def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
        """
        True Range (진정한 범위)

        갭 상승/하락을 포함한 실제 가격 변동폭을 계산합니다.
        TR = max(H-L, |H-PrevClose|, |L-PrevClose|)

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈

        Returns:
            True Range 시리즈
        """
        return IndicatorLibrary.true_range(high, low, close)

    @staticmethod
    def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Average True Range (ATR) - TradingView RMA 방식

        True Range의 RMA (Wilder's Moving Average)로, 변동성 지표입니다.
        TradingView와 동일한 계산 방식을 사용합니다.

        RMA vs EMA:
        - RMA (Wilder): alpha = 1/period
        - EMA (표준):   alpha = 2/(period+1)

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈
            period: 기간 (기본값 14)

        Returns:
            ATR 시리즈 (RMA 기반)
        """
        return IndicatorLibrary.atr(high, low, close, period)

    @staticmethod
    def atr_stop(
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        period: int = 14,
        multiplier: float = 2.5
    ) -> pd.Series:
        """
        ATR Stop Line (빨간선) - Trailing 미적용 원시값

        수식: Highest(H, Period) - ATR(Period) × Multiplier

        Trailing 로직은 별도 관리 필요:
        - 상승 시: 새 값으로 갱신
        - 하락 시: 기존 값 유지

        Args:
            high: 고가 시리즈
            low: 저가 시리즈
            close: 종가 시리즈
            period: 기간 (HTS 기본값 14)
            multiplier: ATR 배수 (기본 2.5, 권장 2.0~3.0)

        Returns:
            ATR Stop 시리즈 (Trailing 미적용)
        """
        return IndicatorLibrary.atr_stop(high, low, close, period, multiplier)


def calculate_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Ju-Do-Ju Sniper 전략에 필요한 모든 지표를 계산하여 추가

    Args:
        df: OHLCV DataFrame (columns: open, high, low, close, volume)

    Returns:
        지표가 추가된 DataFrame
    """
    result = df.copy()

    # EMA: 3선, 20선, 60선
    result["ema3"] = Indicator.ema(df["close"], span=3)
    result["ema20"] = Indicator.ema(df["close"], span=20)
    result["ema60"] = Indicator.ema(df["close"], span=60)

    # 거래량 지표
    result["avg_volume20"] = Indicator.avg_volume(df["volume"], span=20)
    result["volume_ratio"] = Indicator.volume_ratio(df["volume"], span=20)

    # 이격도
    result["disparity20"] = Indicator.disparity(df["close"], result["ema20"])
    result["disparity60"] = Indicator.disparity(df["close"], result["ema60"])

    # 기울기 (우상향/우하향)
    result["ema60_slope"] = Indicator.ma_slope(result["ema60"], period=3)
    result["ema60_uptrend"] = Indicator.is_uptrend(result["ema60"], period=3)

    # 양봉/음봉
    result["is_bullish"] = Indicator.is_bullish(df["open"], df["close"])

    return result
