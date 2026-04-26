"""
Purple-ReAbs 지표 계산 모듈 (V7.0)

돌파 이후 에너지가 소진되지 않고 다시 응축되는 구간(Re-Absorption)을 포착하기 위한 지표.

주요 지표:
- W (Weighted Price): 거래대금 가중평균가격 (VWAP 유사)
- LG (Log Normalized): 거래대금 로그 정규화
- LZ (Fund Z-Score): 자금 에너지 Z-Score
- S (Score): 가격(60%) + 자금에너지(40%) 복합 지표
- H1L1/H2L2: 상승률/수렴률 판단용
- PurpleOK: 필터 조건 (상승률>=4%, 수렴률<=7%, 거래대금>=5억)
"""

from typing import Tuple, Optional
import pandas as pd
import numpy as np

from src.core.constants import PurpleConstants
from src.core.indicator_library import IndicatorLibrary


# ===== Purple-ReAbs 상수 (단일 소스: constants.py PurpleConstants) =====
WEIGHTED_PRICE_PERIOD = PurpleConstants.WEIGHTED_PRICE_PERIOD
FUND_ZSCORE_PERIOD = PurpleConstants.FUND_ZSCORE_PERIOD
SCORE_SMOOTH_PERIOD = PurpleConstants.SCORE_SMOOTH_PERIOD
H1L1_PERIOD = PurpleConstants.H1L1_PERIOD
H2L2_PERIOD = PurpleConstants.H2L2_PERIOD
RECOVERY_LOOKBACK = PurpleConstants.RECOVERY_LOOKBACK

PRICE_VWAP_MULT = PurpleConstants.PRICE_VWAP_MULT
FUND_LZ_MULT = PurpleConstants.FUND_LZ_MULT
RECOVERY_MULT = PurpleConstants.RECOVERY_MULT

MIN_RISE_PCT = PurpleConstants.MIN_RISE_PCT
MAX_CONVERGENCE_PCT = PurpleConstants.MAX_CONVERGENCE_PCT
MIN_BAR_VALUE = PurpleConstants.MIN_BAR_VALUE
ZONE_EMA60_TOLERANCE = PurpleConstants.ZONE_EMA60_TOLERANCE


class PurpleIndicator:
    """
    Purple-ReAbs 전략 지표 계산 유틸리티

    모든 메서드는 정적(static)으로, pandas DataFrame/Series를 입력받아
    지표가 계산된 결과를 반환합니다.

    Usage:
        W = PurpleIndicator.weighted_price(df)
        S = PurpleIndicator.score(df)
        purple_ok = PurpleIndicator.purple_ok(df)
    """

    @staticmethod
    def ema(series: pd.Series, span: int) -> pd.Series:
        """
        지수이동평균 (Exponential Moving Average)

        SNIPER_TRAP과 동일: adjust=False 사용

        Args:
            series: 가격/지표 시리즈
            span: 기간

        Returns:
            EMA 시리즈
        """
        return IndicatorLibrary.ema(series, span)

    @staticmethod
    def money(df: pd.DataFrame) -> pd.Series:
        """
        거래대금 (Money)

        M = Close × Volume

        Args:
            df: OHLCV DataFrame

        Returns:
            거래대금 시리즈
        """
        return df['close'] * df['volume']

    @staticmethod
    def weighted_price(df: pd.DataFrame, period: int = WEIGHTED_PRICE_PERIOD) -> pd.Series:
        """
        가중평균가격 (Weighted Average Price) - VWAP 유사

        W = sum(C × M, period) / sum(M, period)

        거래대금 가중 평균가격으로, 기관/외국인의 평균 진입가 추정에 사용.

        Args:
            df: OHLCV DataFrame
            period: 계산 기간 (기본 40봉)

        Returns:
            가중평균가격 시리즈
        """
        M = PurpleIndicator.money(df)
        C = df['close']

        # sum(C × M, period) / sum(M, period)
        numerator = (C * M).rolling(window=period).sum()
        denominator = M.rolling(window=period).sum()

        # 0으로 나누기 방지
        return numerator / denominator.replace(0, np.nan)

    @staticmethod
    def log_normalized(df: pd.DataFrame) -> pd.Series:
        """
        거래대금 로그 정규화 (LG)

        LG = log(M / max(H - L, 0.01))

        거래대금을 변동폭으로 정규화하여 에너지 밀도 측정.
        높은 LG = 좁은 레인지에서 큰 거래대금 = 에너지 축적

        Args:
            df: OHLCV DataFrame

        Returns:
            로그 정규화 시리즈
        """
        M = PurpleIndicator.money(df)
        range_hl = (df['high'] - df['low']).clip(lower=0.01)  # 최소값 0.01로 제한
        ratio = M / range_hl

        # volume=0인 봉에서 log(0) → -inf 경고 방지: NaN 처리
        return np.log(ratio.where(ratio > 0, np.nan))

    @staticmethod
    def fund_zscore(df: pd.DataFrame, period: int = FUND_ZSCORE_PERIOD) -> pd.Series:
        """
        자금 에너지 Z-Score (LZ)

        LZ = (LG - EMA(LG, period)) / max(EMA(|LG - EMA(LG, period)|, period), 0.0001)

        LG의 평균 대비 편차를 표준화. 자금 유입/유출의 강도 측정.

        Args:
            df: OHLCV DataFrame
            period: Z-Score 기간 (기본 20봉)

        Returns:
            Z-Score 시리즈
        """
        LG = PurpleIndicator.log_normalized(df)

        # EMA(LG, period)
        lg_ema = PurpleIndicator.ema(LG, period)

        # LG - EMA(LG, period)
        deviation = LG - lg_ema

        # EMA(|deviation|, period) - MAD (Mean Absolute Deviation)
        mad = PurpleIndicator.ema(deviation.abs(), period)

        # Z-Score = deviation / max(mad, 0.0001)
        return deviation / mad.clip(lower=0.0001)

    @staticmethod
    def h1l1(df: pd.DataFrame, period: int = H1L1_PERIOD) -> Tuple[pd.Series, pd.Series]:
        """
        H1/L1(40) - 40봉 최고가/최저가

        상승률 계산용: (H1/L1 - 1) >= 4%

        Args:
            df: OHLCV DataFrame
            period: 기간 (기본 40봉)

        Returns:
            (H1, L1) 튜플: (최고가 시리즈, 최저가 시리즈)
        """
        return IndicatorLibrary.h1l1(df['high'], df['low'], period)

    @staticmethod
    def h2l2(df: pd.DataFrame, period: int = H2L2_PERIOD) -> Tuple[pd.Series, pd.Series]:
        """
        H2/L2(20) - 20봉 최고가/최저가

        수렴률 계산용: (H2/L2 - 1) <= 7%

        Args:
            df: OHLCV DataFrame
            period: 기간 (기본 20봉)

        Returns:
            (H2, L2) 튜플: (최고가 시리즈, 최저가 시리즈)
        """
        return IndicatorLibrary.h2l2(df['high'], df['low'], period)

    @staticmethod
    def rise_ratio(df: pd.DataFrame, period: int = H1L1_PERIOD) -> pd.Series:
        """
        상승률 (Rise Ratio)

        H1/L1 - 1: 40봉 내 최대 상승폭

        Args:
            df: OHLCV DataFrame
            period: 기간 (기본 40봉)

        Returns:
            상승률 시리즈 (0.04 = 4%)
        """
        H1, L1 = PurpleIndicator.h1l1(df, period)
        return (H1 / L1.replace(0, np.nan)) - 1

    @staticmethod
    def convergence_ratio(df: pd.DataFrame, period: int = H2L2_PERIOD) -> pd.Series:
        """
        수렴률 (Convergence Ratio)

        H2/L2 - 1: 20봉 내 변동폭 (낮을수록 수렴 상태)

        Args:
            df: OHLCV DataFrame
            period: 기간 (기본 20봉)

        Returns:
            수렴률 시리즈 (0.07 = 7%)
        """
        H2, L2 = PurpleIndicator.h2l2(df, period)
        return (H2 / L2.replace(0, np.nan)) - 1

    @staticmethod
    def recovery_rate(df: pd.DataFrame, period: int = RECOVERY_LOOKBACK) -> pd.Series:
        """
        저점 대비 회복률

        (C - lowest(L, period)) / period

        최근 저점에서 얼마나 회복했는지 측정.

        Args:
            df: OHLCV DataFrame
            period: 기간 (기본 20봉)

        Returns:
            회복률 시리즈
        """
        lowest = df['low'].rolling(window=period).min()
        return (df['close'] - lowest) / period

    @staticmethod
    def score(df: pd.DataFrame, smooth_period: int = SCORE_SMOOTH_PERIOD) -> pd.Series:
        """
        Purple Score (S)

        복합 지표로, 가격 위치(60%) + 자금 에너지(40%)를 결합.

        S = EMA((C/W - 1)*2 + LZ*0.8 + (C - lowest(L, 20))/20*1.2, 10)

        Score 해석:
        - S < 0: 자금 이탈
        - 0 ~ 0.5: 관망
        - 0.5 ~ 1.0: 에너지 축적
        - S > 1: 재상승 임박

        Args:
            df: OHLCV DataFrame
            smooth_period: EMA 스무딩 기간 (기본 10봉)

        Returns:
            Score 시리즈
        """
        W = PurpleIndicator.weighted_price(df)
        LZ = PurpleIndicator.fund_zscore(df)
        recovery = PurpleIndicator.recovery_rate(df)
        C = df['close']

        # Price Component (60%): (C/W - 1)*2 + recovery*1.2
        price_component = (C / W.replace(0, np.nan) - 1) * PRICE_VWAP_MULT
        recovery_component = recovery * RECOVERY_MULT

        # Fund Component (40%): LZ*0.8
        fund_component = LZ * FUND_LZ_MULT

        # 결합 및 스무딩
        raw_score = price_component + fund_component + recovery_component
        return PurpleIndicator.ema(raw_score, smooth_period)

    @staticmethod
    def is_landing_zone(close: pd.Series, ema60: pd.Series, tolerance: float = ZONE_EMA60_TOLERANCE) -> pd.Series:
        """
        Landing Zone 판단

        Zone = C >= EMA60 × (1 - tolerance)

        EMA60 근처 (0.5% 하회까지 허용)에 있는지 판단.

        Args:
            close: 종가 시리즈
            ema60: EMA60 시리즈
            tolerance: 허용 범위 (기본 0.5%)

        Returns:
            bool 시리즈 (True: Landing Zone)
        """
        threshold = ema60 * (1 - tolerance)
        return close >= threshold

    @staticmethod
    def purple_ok(
        df: pd.DataFrame,
        min_rise: float = MIN_RISE_PCT,
        max_convergence: float = MAX_CONVERGENCE_PCT,
        min_money: float = MIN_BAR_VALUE
    ) -> pd.Series:
        """
        PurpleOK 필터

        PurpleOK = (H1/L1 - 1) >= 4% AND (H2/L2 - 1) <= 7% AND M >= 5억

        3가지 조건:
        1. 상승률: 40봉 내 최소 4% 상승 (모멘텀 확인)
        2. 수렴률: 20봉 내 7% 이하 변동 (에너지 응축)
        3. 거래대금: 봉당 5억 이상 (기관 참여)

        Args:
            df: OHLCV DataFrame
            min_rise: 최소 상승률 (기본 4%)
            max_convergence: 최대 수렴률 (기본 7%)
            min_money: 최소 거래대금 (기본 5억)

        Returns:
            bool 시리즈 (True: PurpleOK 통과)
        """
        rise = PurpleIndicator.rise_ratio(df)
        convergence = PurpleIndicator.convergence_ratio(df)
        M = PurpleIndicator.money(df)

        condition1 = rise >= min_rise            # 상승률 >= 4%
        condition2 = convergence <= max_convergence  # 수렴률 <= 7%
        condition3 = M >= min_money              # 거래대금 >= 5억

        return condition1 & condition2 & condition3

    @staticmethod
    def reabs_start(score_series: pd.Series) -> pd.Series:
        """
        Re-Absorption 시작 판단

        ReAbsStart = S > S[1]

        Score가 직전 봉보다 상승 = 자금 재유입 시작

        Args:
            score_series: Score(S) 시리즈

        Returns:
            bool 시리즈 (True: Re-Absorption 시작)
        """
        return score_series > score_series.shift(1)

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
        return IndicatorLibrary.crossup(series, threshold)


def calculate_purple_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Purple-ReAbs 전략에 필요한 모든 지표를 계산하여 추가

    Args:
        df: OHLCV DataFrame (columns: open, high, low, close, volume)

    Returns:
        지표가 추가된 DataFrame
    """
    result = df.copy()

    # EMA
    result['ema3'] = PurpleIndicator.ema(df['close'], span=3)
    result['ema20'] = PurpleIndicator.ema(df['close'], span=20)
    result['ema60'] = PurpleIndicator.ema(df['close'], span=60)

    # Purple 지표
    result['weighted_price'] = PurpleIndicator.weighted_price(df)
    result['log_normalized'] = PurpleIndicator.log_normalized(df)
    result['fund_zscore'] = PurpleIndicator.fund_zscore(df)
    result['score'] = PurpleIndicator.score(df)

    # H1L1/H2L2
    H1, L1 = PurpleIndicator.h1l1(df)
    result['h1'] = H1
    result['l1'] = L1
    result['rise_ratio'] = PurpleIndicator.rise_ratio(df)

    H2, L2 = PurpleIndicator.h2l2(df)
    result['h2'] = H2
    result['l2'] = L2
    result['convergence_ratio'] = PurpleIndicator.convergence_ratio(df)

    # 거래대금
    result['money'] = PurpleIndicator.money(df)

    # PurpleOK
    result['purple_ok'] = PurpleIndicator.purple_ok(df)

    # Re-Absorption
    result['reabs_start'] = PurpleIndicator.reabs_start(result['score'])

    # Zone
    result['landing_zone'] = PurpleIndicator.is_landing_zone(df['close'], result['ema60'])

    # Trigger 요소
    result['crossup_ema3'] = PurpleIndicator.crossup(df['close'], result['ema3'])
    result['is_bullish'] = df['close'] > df['open']

    return result
