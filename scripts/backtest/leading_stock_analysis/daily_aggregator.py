# -*- coding: utf-8 -*-
"""
일봉 재구성 모듈
V6.2-Q

3분봉 데이터를 일봉으로 집계
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
import logging

from .config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


def aggregate_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """3분봉 → 일봉 집계

    Args:
        df: 3분봉 DataFrame (단일 종목)

    Returns:
        일봉 DataFrame
    """
    # 종목명 보존
    stock_name = df['stock_name'].iloc[0] if 'stock_name' in df.columns else 'unknown'

    daily = df.groupby('date_only').agg({
        'open': 'first',         # 시가 (첫 봉)
        'high': 'max',           # 고가 (최댓값)
        'low': 'min',            # 저가 (최솟값)
        'close': 'last',         # 종가 (마지막 봉)
        'trading_value': 'sum',  # 거래대금 합계
        'datetime': ['first', 'last'],  # 첫/마지막 시간
    }).reset_index()

    # 컬럼명 정리
    daily.columns = [
        'date', 'open', 'high', 'low', 'close',
        'trading_value', 'first_time', 'last_time'
    ]

    # 등락률 계산 (전일 종가 대비)
    daily['prev_close'] = daily['close'].shift(1)
    daily['change_rate'] = ((daily['close'] - daily['prev_close']) / daily['prev_close'] * 100).round(2)

    # 시가 대비 등락률 (당일 내)
    daily['intraday_range'] = ((daily['high'] - daily['low']) / daily['open'] * 100).round(2)
    daily['open_to_close'] = ((daily['close'] - daily['open']) / daily['open'] * 100).round(2)
    daily['open_to_high'] = ((daily['high'] - daily['open']) / daily['open'] * 100).round(2)
    daily['open_to_low'] = ((daily['low'] - daily['open']) / daily['open'] * 100).round(2)

    # 종목명 추가
    daily['stock_name'] = stock_name

    return daily


def aggregate_all_to_daily(data_dict: Dict[str, pd.DataFrame]) -> pd.DataFrame:
    """모든 종목 일봉 집계

    Args:
        data_dict: {종목명: 3분봉 DataFrame} 딕셔너리

    Returns:
        병합된 일봉 DataFrame
    """
    daily_list = []

    for stock_name, df in data_dict.items():
        daily = aggregate_to_daily(df)
        daily_list.append(daily)

    if not daily_list:
        return pd.DataFrame()

    merged = pd.concat(daily_list, ignore_index=True)
    merged = merged.sort_values(['stock_name', 'date']).reset_index(drop=True)

    logger.info(f"Aggregated {len(data_dict)} stocks to daily: {len(merged)} rows")
    return merged


def filter_event_days(
    daily_df: pd.DataFrame,
    min_trading_value: float = None,
    min_change_rate: float = None,
    config: AnalysisConfig = None
) -> pd.DataFrame:
    """이벤트 발생일 필터링

    조건:
    - 일봉 거래대금 >= min_trading_value (기본 1000억)
    - 종가 기준 등락률 >= min_change_rate (기본 10%)

    Args:
        daily_df: 일봉 DataFrame
        min_trading_value: 최소 거래대금 (원)
        min_change_rate: 최소 등락률 (%)
        config: AnalysisConfig 인스턴스

    Returns:
        이벤트 조건을 만족하는 일봉 DataFrame
    """
    if config is None:
        config = DEFAULT_CONFIG

    if min_trading_value is None:
        min_trading_value = config.min_trading_value

    if min_change_rate is None:
        min_change_rate = config.min_change_rate

    # 필터링
    mask = (
        (daily_df['trading_value'] >= min_trading_value) &
        (daily_df['change_rate'] >= min_change_rate)
    )

    events = daily_df[mask].copy()

    logger.info(
        f"Filtered events: {len(daily_df)} -> {len(events)} days "
        f"(trading_value >= {min_trading_value:.0f}억원, change_rate >= {min_change_rate}%)"
    )

    return events


def get_event_days_list(
    events_df: pd.DataFrame,
    data_dict: Dict[str, pd.DataFrame]
) -> List[Tuple[str, str, pd.DataFrame]]:
    """이벤트 발생일의 3분봉 데이터 리스트 반환

    Args:
        events_df: 이벤트 일봉 DataFrame
        data_dict: {종목명: 3분봉 DataFrame} 딕셔너리

    Returns:
        [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트
    """
    result = []

    for _, row in events_df.iterrows():
        stock_name = row['stock_name']
        event_date = row['date']

        if stock_name not in data_dict:
            continue

        df = data_dict[stock_name]
        day_data = df[df['date_only'] == event_date].copy()

        if len(day_data) > 0:
            result.append((stock_name, str(event_date), day_data))

    logger.info(f"Retrieved {len(result)} event day 3min data")
    return result


def calculate_daily_stats(daily_df: pd.DataFrame) -> Dict:
    """일봉 통계 계산

    Args:
        daily_df: 일봉 DataFrame

    Returns:
        통계 딕셔너리
    """
    return {
        'total_days': len(daily_df),
        'unique_stocks': daily_df['stock_name'].nunique(),
        'avg_trading_value': daily_df['trading_value'].mean(),
        'avg_change_rate': daily_df['change_rate'].mean(),
        'max_change_rate': daily_df['change_rate'].max(),
        'min_change_rate': daily_df['change_rate'].min(),
        'avg_intraday_range': daily_df['intraday_range'].mean(),
        'limit_up_count': len(daily_df[daily_df['change_rate'] >= 29.9]),
    }


def get_event_summary(events_df: pd.DataFrame) -> pd.DataFrame:
    """이벤트 요약 (종목별)

    Args:
        events_df: 이벤트 일봉 DataFrame

    Returns:
        종목별 요약 DataFrame
    """
    summary = events_df.groupby('stock_name').agg({
        'date': 'count',
        'trading_value': 'mean',
        'change_rate': ['mean', 'max'],
        'intraday_range': 'mean',
    }).reset_index()

    summary.columns = [
        'stock_name', 'event_count', 'avg_trading_value',
        'avg_change_rate', 'max_change_rate', 'avg_intraday_range'
    ]

    summary = summary.sort_values('event_count', ascending=False)
    return summary
