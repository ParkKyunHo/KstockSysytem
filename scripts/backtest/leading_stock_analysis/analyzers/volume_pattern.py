# -*- coding: utf-8 -*-
"""
거래량 패턴 분석
V6.2-Q

- 거래량 급증/급감 시점
- 거래량 분포 패턴
- 거래량-가격 상관관계
- 거래량 이동평균 돌파
- 누적 거래량 곡선
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class VolumePatternResult:
    """거래량 패턴 분석 결과"""
    surge_analysis: Dict               # 거래량 급증 분석
    drop_analysis: Dict                # 거래량 급감 분석
    distribution_pattern: Dict         # 분포 패턴
    volume_price_correlation: Dict     # 거래량-가격 상관
    ma_breakout: Dict                  # 이동평균 돌파
    cumulative_curve: Dict             # 누적 거래량 곡선


class VolumePatternAnalyzer:
    """거래량 패턴 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> VolumePatternResult:
        """거래량 패턴 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            VolumePatternResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 거래량 급증 분석
        surge_analysis = self._analyze_volume_surge(event_days)

        # 2. 거래량 급감 분석
        drop_analysis = self._analyze_volume_drop(event_days)

        # 3. 분포 패턴
        distribution_pattern = self._analyze_distribution_pattern(event_days)

        # 4. 거래량-가격 상관관계
        volume_price_correlation = self._analyze_volume_price_correlation(event_days)

        # 5. 이동평균 돌파
        ma_breakout = self._analyze_ma_breakout(event_days)

        # 6. 누적 거래량 곡선
        cumulative_curve = self._analyze_cumulative_curve(event_days)

        return VolumePatternResult(
            surge_analysis=surge_analysis,
            drop_analysis=drop_analysis,
            distribution_pattern=distribution_pattern,
            volume_price_correlation=volume_price_correlation,
            ma_breakout=ma_breakout,
            cumulative_curve=cumulative_curve,
        )

    def _analyze_volume_surge(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """거래량 급증 시점 분석 (이전 봉 대비 200%+)

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            급증 분석 딕셔너리
        """
        surge_data = []

        for stock_name, date, df in event_days:
            if df.empty or 'trading_value' not in df.columns:
                continue

            df = df.copy().reset_index(drop=True)

            # 이전 봉 대비 변화율
            df['prev_value'] = df['trading_value'].shift(1)
            df['value_ratio'] = df['trading_value'] / df['prev_value']

            # 급증 감지 (200%+)
            threshold = self.config.volume_spike_threshold
            surges = df[df['value_ratio'] >= threshold].copy()

            for _, row in surges.iterrows():
                # 급증 후 가격 변화
                surge_idx = row.name
                if surge_idx + 1 < len(df):
                    next_price_change = (df.loc[surge_idx + 1, 'close'] - row['close']) / row['close'] * 100
                else:
                    next_price_change = 0

                # 급증 시 가격 변화 (해당 봉)
                bar_price_change = (row['close'] - row['open']) / row['open'] * 100 if row['open'] > 0 else 0

                surge_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'surge_time': row['datetime'].strftime('%H:%M'),
                    'surge_hour': row['datetime'].hour,
                    'volume_ratio': row['value_ratio'],
                    'trading_value': row['trading_value'],
                    'bar_price_change': bar_price_change,
                    'next_price_change': next_price_change,
                })

        if not surge_data:
            return {'raw_data': pd.DataFrame(), 'hourly_stats': pd.DataFrame()}

        surge_df = pd.DataFrame(surge_data)

        # 시간대별 급증 빈도
        hourly_stats = surge_df.groupby('surge_hour').agg({
            'stock_name': 'count',
            'volume_ratio': 'mean',
            'bar_price_change': 'mean',
        }).reset_index()

        hourly_stats.columns = ['hour', 'surge_count', 'avg_volume_ratio', 'avg_price_change']

        # 급증 시 가격 상승/하락 비율
        up_ratio = (surge_df['bar_price_change'] > 0).mean() * 100

        summary = {
            'total_surges': len(surge_df),
            'avg_volume_ratio': surge_df['volume_ratio'].mean(),
            'price_up_ratio': up_ratio,
            'avg_bar_price_change': surge_df['bar_price_change'].mean(),
        }

        return {
            'raw_data': surge_df,
            'hourly_stats': hourly_stats,
            'summary': summary,
        }

    def _analyze_volume_drop(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """거래량 급감 시점 분석 (이전 봉 대비 50% 이하)

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            급감 분석 딕셔너리
        """
        drop_data = []

        for stock_name, date, df in event_days:
            if df.empty or 'trading_value' not in df.columns:
                continue

            df = df.copy().reset_index(drop=True)

            # 이전 봉 대비 변화율
            df['prev_value'] = df['trading_value'].shift(1)
            df['value_ratio'] = df['trading_value'] / df['prev_value']

            # 급감 감지 (50% 이하)
            threshold = self.config.volume_drop_threshold
            drops = df[(df['value_ratio'] <= threshold) & (df['value_ratio'] > 0)].copy()

            for _, row in drops.iterrows():
                drop_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'drop_time': row['datetime'].strftime('%H:%M'),
                    'drop_hour': row['datetime'].hour,
                    'volume_ratio': row['value_ratio'],
                    'price_change': (row['close'] - row['open']) / row['open'] * 100 if row['open'] > 0 else 0,
                })

        if not drop_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        drop_df = pd.DataFrame(drop_data)

        # 시간대별 급감 빈도
        hourly_stats = drop_df.groupby('drop_hour').size().reset_index(name='count')

        summary = {
            'total_drops': len(drop_df),
            'avg_volume_ratio': drop_df['volume_ratio'].mean(),
            'most_common_hour': drop_df['drop_hour'].mode().iloc[0] if len(drop_df) > 0 else None,
        }

        return {
            'raw_data': drop_df,
            'hourly_stats': hourly_stats,
            'summary': summary,
        }

    def _analyze_distribution_pattern(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """거래량 분포 패턴 분류

        - early_burst: 초반 폭발형 (09:00-10:00에 50%+)
        - gradual_increase: 점진 증가형
        - late_surge: 후반 급증형 (14:00 이후 40%+)
        - balanced: 균형형

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            분포 패턴 딕셔너리
        """
        patterns = {
            'early_burst': 0,
            'late_surge': 0,
            'gradual_increase': 0,
            'balanced': 0,
        }

        pattern_details = []

        for stock_name, date, df in event_days:
            if df.empty or 'trading_value' not in df.columns:
                continue

            df = df.copy()

            daily_total = df['trading_value'].sum()
            if daily_total <= 0:
                continue

            # 시간대별 비율
            df['hour'] = df['datetime'].dt.hour

            early = df[df['hour'] < 10]['trading_value'].sum() / daily_total
            mid = df[(df['hour'] >= 10) & (df['hour'] < 14)]['trading_value'].sum() / daily_total
            late = df[df['hour'] >= 14]['trading_value'].sum() / daily_total

            # 패턴 분류
            if early > 0.5:
                pattern = 'early_burst'
            elif late > 0.4:
                pattern = 'late_surge'
            elif mid > early and mid > late:
                pattern = 'gradual_increase'
            else:
                pattern = 'balanced'

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
        frequencies = {k: v / total * 100 if total > 0 else 0 for k, v in patterns.items()}

        return {
            'counts': patterns,
            'frequencies': frequencies,
            'details': pd.DataFrame(pattern_details) if pattern_details else pd.DataFrame(),
        }

    def _analyze_volume_price_correlation(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """거래량-가격 상관관계 분석

        거래량 급증 시 가격 상승/하락 비율

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            상관관계 딕셔너리
        """
        corr_data = []

        for stock_name, date, df in event_days:
            if df.empty or 'trading_value' not in df.columns:
                continue

            df = df.copy().reset_index(drop=True)

            # 각 봉의 가격 변화와 거래량
            df['price_change'] = (df['close'] - df['open']) / df['open'] * 100
            df['price_change'] = df['price_change'].replace([np.inf, -np.inf], 0)

            # 상관계수 계산
            valid = df[['trading_value', 'price_change']].dropna()
            if len(valid) > 5:
                corr = valid['trading_value'].corr(valid['price_change'])
                corr_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'correlation': corr,
                    'avg_price_change': valid['price_change'].mean(),
                    'volume_weighted_return': np.average(
                        valid['price_change'],
                        weights=valid['trading_value']
                    ) if valid['trading_value'].sum() > 0 else 0,
                })

        if not corr_data:
            return {'raw_data': pd.DataFrame(), 'avg_correlation': np.nan}

        corr_df = pd.DataFrame(corr_data)

        return {
            'raw_data': corr_df,
            'avg_correlation': corr_df['correlation'].mean(),
            'positive_corr_ratio': (corr_df['correlation'] > 0).mean() * 100,
            'avg_volume_weighted_return': corr_df['volume_weighted_return'].mean(),
        }

    def _analyze_ma_breakout(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """거래량 5봉 이동평균 돌파 분석

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            MA 돌파 딕셔너리
        """
        breakout_data = []

        for stock_name, date, df in event_days:
            if df.empty or 'trading_value' not in df.columns:
                continue

            df = df.copy().reset_index(drop=True)

            # 5봉 거래량 이동평균
            df['volume_ma5'] = df['trading_value'].rolling(5).mean()

            # MA 돌파 감지 (현재 거래량 > MA × 1.5)
            df['ma_breakout'] = df['trading_value'] > df['volume_ma5'] * 1.5

            breakouts = df[df['ma_breakout']].copy()

            for _, row in breakouts.iterrows():
                idx = row.name
                if idx + 3 < len(df):
                    # 돌파 후 3봉 수익률
                    future_price = df.loc[idx + 3, 'close']
                    ret = (future_price - row['close']) / row['close'] * 100
                else:
                    ret = np.nan

                breakout_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'breakout_time': row['datetime'].strftime('%H:%M'),
                    'breakout_hour': row['datetime'].hour,
                    'volume_ratio': row['trading_value'] / row['volume_ma5'] if row['volume_ma5'] > 0 else 0,
                    'return_3bars': ret,
                    'bar_return': (row['close'] - row['open']) / row['open'] * 100 if row['open'] > 0 else 0,
                })

        if not breakout_data:
            return {'raw_data': pd.DataFrame(), 'summary': {}}

        breakout_df = pd.DataFrame(breakout_data)

        summary = {
            'total_breakouts': len(breakout_df),
            'avg_volume_ratio': breakout_df['volume_ratio'].mean(),
            'avg_return_3bars': breakout_df['return_3bars'].mean(),
            'win_rate_3bars': (breakout_df['return_3bars'] > 0).mean() * 100,
        }

        return {
            'raw_data': breakout_df,
            'summary': summary,
        }

    def _analyze_cumulative_curve(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """누적 거래량 곡선 분석

        S커브 (초중반 집중) vs J커브 (후반 급증) vs 선형

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            누적 곡선 딕셔너리
        """
        curve_data = []

        for stock_name, date, df in event_days:
            if df.empty or 'trading_value' not in df.columns:
                continue

            df = df.copy().reset_index(drop=True)

            # 누적 거래량
            df['cumulative'] = df['trading_value'].cumsum()
            total = df['trading_value'].sum()

            if total <= 0:
                continue

            df['cumulative_pct'] = df['cumulative'] / total * 100

            # 중간 지점 (봉 수의 50%) 도달 시 누적 비율
            mid_idx = len(df) // 2
            mid_cumulative = df.iloc[mid_idx]['cumulative_pct'] if mid_idx < len(df) else 50

            # 25% 지점 누적 비율
            q1_idx = len(df) // 4
            q1_cumulative = df.iloc[q1_idx]['cumulative_pct'] if q1_idx < len(df) else 25

            # 75% 지점 누적 비율
            q3_idx = 3 * len(df) // 4
            q3_cumulative = df.iloc[q3_idx]['cumulative_pct'] if q3_idx < len(df) else 75

            # 곡선 형태 분류
            if mid_cumulative > 60:
                curve_type = 'S_curve'  # 초중반 집중
            elif mid_cumulative < 40:
                curve_type = 'J_curve'  # 후반 집중
            else:
                curve_type = 'linear'   # 선형

            curve_data.append({
                'stock_name': stock_name,
                'date': date,
                'q1_cumulative': q1_cumulative,
                'mid_cumulative': mid_cumulative,
                'q3_cumulative': q3_cumulative,
                'curve_type': curve_type,
            })

        if not curve_data:
            return {'raw_data': pd.DataFrame(), 'curve_stats': {}}

        curve_df = pd.DataFrame(curve_data)

        # 곡선 유형별 통계
        curve_stats = curve_df.groupby('curve_type').size().reset_index(name='count')
        curve_stats['frequency'] = curve_stats['count'] / len(curve_df) * 100

        summary = {
            'avg_mid_cumulative': curve_df['mid_cumulative'].mean(),
            'curve_distribution': curve_stats.set_index('curve_type')['frequency'].to_dict(),
        }

        return {
            'raw_data': curve_df,
            'curve_stats': curve_stats,
            'summary': summary,
        }

    def _empty_result(self) -> VolumePatternResult:
        """빈 결과 반환"""
        return VolumePatternResult(
            surge_analysis={'raw_data': pd.DataFrame()},
            drop_analysis={'raw_data': pd.DataFrame()},
            distribution_pattern={'counts': {}, 'frequencies': {}},
            volume_price_correlation={'raw_data': pd.DataFrame(), 'avg_correlation': np.nan},
            ma_breakout={'raw_data': pd.DataFrame()},
            cumulative_curve={'raw_data': pd.DataFrame()},
        )
