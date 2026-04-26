# -*- coding: utf-8 -*-
"""
시간대별 거래대금 분석
V6.2-Q

- 시간대별 거래대금 절대값
- 시간대별 거래대금 비율 (%)
- 거래대금 피크 시점
- 거래대금 분포 패턴 (초반/중반/후반 집중형)
- 거래대금 급증 시점
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class TimeDistributionResult:
    """시간대별 분석 결과"""
    bucket_stats: pd.DataFrame         # 시간대별 통계
    peak_times: pd.DataFrame           # 피크 시점 분포
    pattern_classification: Dict       # 패턴 분류 결과
    surge_analysis: pd.DataFrame       # 급증 분석
    raw_data: Optional[pd.DataFrame] = None


class TimeDistributionAnalyzer:
    """시간대별 거래대금 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> TimeDistributionResult:
        """시간대별 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            TimeDistributionResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 시간대별 통계
        bucket_stats = self._analyze_time_buckets(event_days)

        # 2. 피크 시점 분포
        peak_times = self._analyze_peak_times(event_days)

        # 3. 패턴 분류
        pattern_classification = self._classify_patterns(event_days)

        # 4. 급증 분석
        surge_analysis = self._analyze_surges(event_days)

        return TimeDistributionResult(
            bucket_stats=bucket_stats,
            peak_times=peak_times,
            pattern_classification=pattern_classification,
            surge_analysis=surge_analysis,
        )

    def _analyze_time_buckets(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """시간대별 거래대금 통계

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            시간대별 통계 DataFrame
        """
        all_bucket_data = []

        for stock_name, date, df in event_days:
            df = df.copy()
            df['time_only'] = df['datetime'].dt.time

            daily_total = df['trading_value'].sum()
            if daily_total <= 0:
                continue

            for start_str, end_str in self.config.time_buckets:
                start = pd.to_datetime(start_str).time()
                end = pd.to_datetime(end_str).time()

                bucket_mask = (df['time_only'] >= start) & (df['time_only'] < end)
                bucket_value = df.loc[bucket_mask, 'trading_value'].sum()
                bucket_ratio = bucket_value / daily_total * 100

                all_bucket_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'time_bucket': f"{start_str[:5]}-{end_str[:5]}",
                    'trading_value': bucket_value,
                    'ratio': bucket_ratio,
                    'daily_total': daily_total,
                })

        if not all_bucket_data:
            return pd.DataFrame()

        bucket_df = pd.DataFrame(all_bucket_data)

        # 시간대별 평균/중앙값 계산
        summary = bucket_df.groupby('time_bucket').agg({
            'trading_value': ['mean', 'median', 'std'],
            'ratio': ['mean', 'median', 'std', 'min', 'max'],
        }).reset_index()

        summary.columns = [
            'time_bucket',
            'avg_value', 'median_value', 'std_value',
            'avg_ratio', 'median_ratio', 'std_ratio', 'min_ratio', 'max_ratio'
        ]

        # 시간순 정렬
        summary = summary.sort_values('time_bucket').reset_index(drop=True)

        return summary

    def _analyze_peak_times(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """거래대금 피크 시점 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            피크 시점 분포 DataFrame
        """
        peak_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            # 최대 거래대금 봉 찾기
            max_idx = df['trading_value'].idxmax()
            peak_row = df.loc[max_idx]

            peak_time = peak_row['datetime']
            peak_value = peak_row['trading_value']
            daily_total = df['trading_value'].sum()

            # 시간대 분류
            peak_hour = peak_time.hour
            if peak_hour < 10:
                period = 'early_morning'  # 09:00-10:00
            elif peak_hour < 11:
                period = 'mid_morning'    # 10:00-11:00
            elif peak_hour < 13:
                period = 'noon'           # 11:00-13:00
            elif peak_hour < 14:
                period = 'early_afternoon'  # 13:00-14:00
            else:
                period = 'late_afternoon'   # 14:00-15:30

            peak_data.append({
                'stock_name': stock_name,
                'date': date,
                'peak_time': peak_time.strftime('%H:%M'),
                'peak_hour': peak_hour,
                'period': period,
                'peak_value': peak_value,
                'peak_ratio': peak_value / daily_total * 100 if daily_total > 0 else 0,
            })

        if not peak_data:
            return pd.DataFrame()

        peak_df = pd.DataFrame(peak_data)

        # 시간대별 분포 요약
        summary = peak_df.groupby('period').agg({
            'stock_name': 'count',
            'peak_ratio': ['mean', 'std'],
        }).reset_index()

        summary.columns = ['period', 'count', 'avg_peak_ratio', 'std_peak_ratio']
        summary['frequency'] = summary['count'] / len(peak_df) * 100

        return summary

    def _classify_patterns(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """거래대금 분포 패턴 분류

        패턴:
        - early_concentrated: 초반 집중형 (09:00-10:30 > 50%)
        - mid_concentrated: 중반 집중형 (10:30-14:00 > 50%)
        - late_concentrated: 후반 집중형 (14:00-15:30 > 40%)
        - distributed: 분산형

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            패턴 분류 딕셔너리
        """
        patterns = {
            'early_concentrated': 0,
            'mid_concentrated': 0,
            'late_concentrated': 0,
            'distributed': 0,
        }

        pattern_details = []

        for stock_name, date, df in event_days:
            df = df.copy()
            df['time_only'] = df['datetime'].dt.time

            daily_total = df['trading_value'].sum()
            if daily_total <= 0:
                continue

            # 시간대별 비율 계산
            early = df[df['datetime'].dt.hour < 10]['trading_value'].sum() / daily_total
            early += df[(df['datetime'].dt.hour == 10) & (df['datetime'].dt.minute < 30)]['trading_value'].sum() / daily_total

            late = df[df['datetime'].dt.hour >= 14]['trading_value'].sum() / daily_total

            mid = 1 - early - late

            # 패턴 분류
            if early > 0.5:
                pattern = 'early_concentrated'
            elif late > 0.4:
                pattern = 'late_concentrated'
            elif mid > 0.5:
                pattern = 'mid_concentrated'
            else:
                pattern = 'distributed'

            patterns[pattern] += 1
            pattern_details.append({
                'stock_name': stock_name,
                'date': date,
                'pattern': pattern,
                'early_ratio': early * 100,
                'mid_ratio': mid * 100,
                'late_ratio': late * 100,
            })

        total = sum(patterns.values())
        pattern_frequencies = {k: v / total * 100 if total > 0 else 0 for k, v in patterns.items()}

        return {
            'counts': patterns,
            'frequencies': pattern_frequencies,
            'details': pd.DataFrame(pattern_details) if pattern_details else pd.DataFrame(),
        }

    def _analyze_surges(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """거래대금 급증 시점 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            급증 분석 DataFrame
        """
        surge_data = []

        for stock_name, date, df in event_days:
            if len(df) < 2:
                continue

            df = df.copy().reset_index(drop=True)

            # 이전 봉 대비 거래대금 변화율
            df['prev_value'] = df['trading_value'].shift(1)
            df['value_change'] = df['trading_value'] / df['prev_value']

            # 급증 감지 (150%+)
            threshold = self.config.volume_surge_threshold
            surges = df[df['value_change'] >= threshold].copy()

            for _, row in surges.iterrows():
                surge_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'surge_time': row['datetime'].strftime('%H:%M'),
                    'surge_hour': row['datetime'].hour,
                    'change_ratio': row['value_change'],
                    'trading_value': row['trading_value'],
                    'price_change': (row['close'] - row['open']) / row['open'] * 100 if row['open'] > 0 else 0,
                })

        if not surge_data:
            return pd.DataFrame()

        surge_df = pd.DataFrame(surge_data)

        # 시간대별 급증 빈도
        hourly_summary = surge_df.groupby('surge_hour').agg({
            'stock_name': 'count',
            'change_ratio': 'mean',
            'price_change': 'mean',
        }).reset_index()

        hourly_summary.columns = ['hour', 'surge_count', 'avg_change_ratio', 'avg_price_change']

        return hourly_summary

    def _empty_result(self) -> TimeDistributionResult:
        """빈 결과 반환"""
        return TimeDistributionResult(
            bucket_stats=pd.DataFrame(),
            peak_times=pd.DataFrame(),
            pattern_classification={'counts': {}, 'frequencies': {}, 'details': pd.DataFrame()},
            surge_analysis=pd.DataFrame(),
        )
