# -*- coding: utf-8 -*-
"""
지표 계산 모듈

EMA5, EMA8, ATR14 계산 (adjust=False 준수)
"""

import pandas as pd
import numpy as np
from typing import Tuple


def calculate_ema(series: pd.Series, span: int) -> pd.Series:
    """
    EMA (Exponential Moving Average) 계산

    IMPORTANT: adjust=False 사용 (시스템 불변조건)

    Args:
        series: 가격 시리즈
        span: EMA 기간

    Returns:
        EMA 시리즈
    """
    return series.ewm(span=span, adjust=False).mean()


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14
) -> pd.Series:
    """
    ATR (Average True Range) 계산

    RMA (Wilder's Moving Average) 방식 사용

    Args:
        high: 고가 시리즈
        low: 저가 시리즈
        close: 종가 시리즈
        period: ATR 기간 (기본 14)

    Returns:
        ATR 시리즈
    """
    # True Range 계산
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = abs(high - prev_close)
    tr3 = abs(low - prev_close)
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # RMA (Wilder's) = EMA with alpha=1/period
    atr = true_range.ewm(alpha=1/period, adjust=False).mean()

    return atr


def calculate_hlc3(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series
) -> pd.Series:
    """
    HLC3 (Typical Price) 계산

    Args:
        high: 고가 시리즈
        low: 저가 시리즈
        close: 종가 시리즈

    Returns:
        HLC3 시리즈
    """
    return (high + low + close) / 3


def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    모든 필요 지표 계산

    Args:
        df: 일봉 데이터 (date, open, high, low, close, volume, trading_value)

    Returns:
        지표가 추가된 DataFrame
    """
    result = df.copy()

    # EMA 계산
    result['ema3'] = calculate_ema(result['close'], 3)  # Phase 3: EMA3 이탈 청산용
    result['ema5'] = calculate_ema(result['close'], 5)
    result['ema8'] = calculate_ema(result['close'], 8)

    # EMA와의 거리 (%)
    result['dist_ema5_pct'] = (result['close'] - result['ema5']) / result['ema5'] * 100
    result['dist_ema8_pct'] = (result['close'] - result['ema8']) / result['ema8'] * 100

    # 절대값 거리
    result['abs_dist_ema5_pct'] = result['dist_ema5_pct'].abs()
    result['abs_dist_ema8_pct'] = result['dist_ema8_pct'].abs()

    # ATR
    result['atr14'] = calculate_atr(
        result['high'],
        result['low'],
        result['close'],
        period=14
    )

    # HLC3
    result['hlc3'] = calculate_hlc3(
        result['high'],
        result['low'],
        result['close']
    )

    # ATR 트레일링 스탑 기준값 (HLC3 - ATR * 6.0)
    result['atr_ts_base'] = result['hlc3'] - result['atr14'] * 6.0

    return result


def is_near_ema5(close: float, ema5: float, proximity_pct: float) -> bool:
    """
    5일선 근접 여부 확인

    Args:
        close: 종가
        ema5: 5일 EMA
        proximity_pct: 근접 기준 (%)

    Returns:
        근접 여부
    """
    if ema5 == 0:
        return False
    distance_pct = abs(close - ema5) / ema5 * 100
    return distance_pct <= proximity_pct


def is_near_ema8(close: float, ema8: float, proximity_pct: float) -> bool:
    """
    8일선 근접 여부 확인

    Args:
        close: 종가
        ema8: 8일 EMA
        proximity_pct: 근접 기준 (%)

    Returns:
        근접 여부
    """
    if ema8 == 0:
        return False
    distance_pct = abs(close - ema8) / ema8 * 100
    return distance_pct <= proximity_pct


def calculate_trailing_stop(
    hlc3: float,
    atr: float,
    multiplier: float = 6.0
) -> int:
    """
    ATR 트레일링 스탑 계산

    Args:
        hlc3: HLC3 값
        atr: ATR 값
        multiplier: ATR 배수 (기본 6.0)

    Returns:
        트레일링 스탑 가격
    """
    ts = hlc3 - (atr * multiplier)
    return int(max(ts, 0))


def get_warmup_period() -> int:
    """
    지표 안정화에 필요한 최소 봉 수

    EMA8이 가장 짧은 기간이지만, ATR14가 필요하므로
    최소 20봉 정도는 필요

    Returns:
        최소 봉 수
    """
    return 20


# =============================================================================
# Phase 2: 3분봉 지표 함수 (V6.2-A 로직)
# =============================================================================

def calculate_indicators_3min(df: pd.DataFrame) -> pd.DataFrame:
    """
    3분봉 데이터에 필요 지표 계산 (V6.2-A 청산 로직용)

    Args:
        df: 3분봉 데이터 (datetime, open, high, low, close, volume)

    Returns:
        지표가 추가된 DataFrame
            - atr10: ATR(10)
            - ema9: EMA9
            - hlc3: HLC3
    """
    result = df.copy()

    # ATR(10)
    result['atr10'] = calculate_atr(
        result['high'],
        result['low'],
        result['close'],
        period=10
    )

    # EMA9
    result['ema9'] = calculate_ema(result['close'], 9)

    # HLC3
    result['hlc3'] = calculate_hlc3(
        result['high'],
        result['low'],
        result['close']
    )

    return result


def check_structure_warning(
    df: pd.DataFrame,
    current_idx: int,
    consecutive_bars: int = 2
) -> bool:
    """
    Structure Warning 조건 체크

    조건: EMA9 또는 HLC3를 consecutive_bars봉 연속 하회 시 발동

    Args:
        df: 3분봉 데이터 (지표 포함)
        current_idx: 현재 봉 인덱스
        consecutive_bars: 연속 봉 수 (기본 2)

    Returns:
        Structure Warning 발동 여부
    """
    if current_idx < consecutive_bars - 1:
        return False

    # 최근 consecutive_bars 봉 확인
    for i in range(consecutive_bars):
        idx = current_idx - i
        if idx < 0:
            return False

        row = df.iloc[idx]
        close = row['close']
        ema9 = row['ema9']
        hlc3 = row['hlc3']

        # EMA9과 HLC3 모두 상회하면 Warning 아님
        if close >= ema9 and close >= hlc3:
            return False

    # consecutive_bars 봉 연속 EMA9 또는 HLC3 하회
    return True


def calculate_trailing_stop_3min(
    hlc3: float,
    atr: float,
    is_structure_warning: bool,
    mult_base: float = 6.0,
    mult_tight: float = 4.5
) -> int:
    """
    3분봉 ATR 트레일링 스탑 계산 (V6.2-A)

    Args:
        hlc3: HLC3 값
        atr: ATR 값
        is_structure_warning: Structure Warning 발동 여부
        mult_base: 기본 ATR 배수 (6.0)
        mult_tight: 타이트닝 ATR 배수 (4.5)

    Returns:
        트레일링 스탑 가격
    """
    multiplier = mult_tight if is_structure_warning else mult_base
    ts = hlc3 - (atr * multiplier)
    return int(max(ts, 0))
