# -*- coding: utf-8 -*-
"""
진입 타이밍 분석
V6.2-Q

- 최적 진입 시점 도출
- 손절선 활용 시 손실 제한 효과
- 시간대별 진입 성과 비교
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class EntryTimingResult:
    """진입 타이밍 분석 결과"""
    optimal_entry_time: Dict           # 최적 진입 시점
    stop_loss_effectiveness: Dict      # 손절선 효과
    hourly_performance: pd.DataFrame   # 시간대별 성과
    entry_signals_analysis: Dict       # 진입 신호별 분석


class EntryTimingAnalyzer:
    """진입 타이밍 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> EntryTimingResult:
        """진입 타이밍 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            EntryTimingResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 최적 진입 시점 분석
        optimal_entry_time = self._find_optimal_entry_time(event_days)

        # 2. 손절선 효과 분석
        stop_loss_effectiveness = self._analyze_stop_loss_effectiveness(event_days)

        # 3. 시간대별 성과
        hourly_performance = self._analyze_hourly_performance(event_days)

        # 4. 진입 신호별 분석
        entry_signals_analysis = self._analyze_entry_signals(event_days)

        return EntryTimingResult(
            optimal_entry_time=optimal_entry_time,
            stop_loss_effectiveness=stop_loss_effectiveness,
            hourly_performance=hourly_performance,
            entry_signals_analysis=entry_signals_analysis,
        )

    def _find_optimal_entry_time(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """최적 진입 시점 분석

        장 시작 후 N분 기다렸다가 진입했을 때의 수익률 비교

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            최적 진입 시점 딕셔너리
        """
        wait_times = [0, 3, 6, 9, 15, 30, 60, 90, 120]  # 분
        wait_results = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)
            market_open = df['datetime'].min()
            close_price = df.iloc[-1]['close']

            for wait in wait_times:
                entry_time = market_open + pd.Timedelta(minutes=wait)
                entry_df = df[df['datetime'] >= entry_time]

                if entry_df.empty:
                    continue

                entry_price = entry_df.iloc[0]['open']
                ret = (close_price - entry_price) / entry_price * 100

                # 진입 후 MFE/MAE
                after_entry = df[df['datetime'] >= entry_time]
                mfe = (after_entry['high'].max() - entry_price) / entry_price * 100
                mae = (after_entry['low'].min() - entry_price) / entry_price * 100

                wait_results.append({
                    'stock_name': stock_name,
                    'date': date,
                    'wait_minutes': wait,
                    'entry_price': entry_price,
                    'return_to_close': ret,
                    'mfe': mfe,
                    'mae': mae,
                })

        if not wait_results:
            return {'raw_data': pd.DataFrame(), 'optimal_wait': None}

        wait_df = pd.DataFrame(wait_results)

        # 대기 시간별 통계
        summary = wait_df.groupby('wait_minutes').agg({
            'return_to_close': ['mean', 'median', 'std'],
            'mfe': 'mean',
            'mae': 'mean',
            'stock_name': 'count',
        }).reset_index()

        summary.columns = [
            'wait_minutes', 'avg_return', 'median_return', 'std_return',
            'avg_mfe', 'avg_mae', 'sample_count'
        ]

        # 승률 계산
        win_rates = wait_df.groupby('wait_minutes')['return_to_close'].apply(
            lambda x: (x > 0).mean() * 100
        ).reset_index()
        win_rates.columns = ['wait_minutes', 'win_rate']

        summary = summary.merge(win_rates, on='wait_minutes')

        # Sharpe-like ratio
        summary['sharpe_like'] = summary['avg_return'] / summary['std_return'].replace(0, np.nan)

        # 최적 대기 시간
        optimal_by_return = summary.loc[summary['avg_return'].idxmax(), 'wait_minutes']
        optimal_by_sharpe = summary.loc[summary['sharpe_like'].idxmax(), 'wait_minutes']
        optimal_by_winrate = summary.loc[summary['win_rate'].idxmax(), 'wait_minutes']

        return {
            'raw_data': wait_df,
            'summary': summary,
            'optimal_by_return': optimal_by_return,
            'optimal_by_sharpe': optimal_by_sharpe,
            'optimal_by_winrate': optimal_by_winrate,
        }

    def _analyze_stop_loss_effectiveness(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """손절선 효과 분석

        -2%, -3%, -4%, -5% 손절 시 결과 비교

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            손절선 효과 딕셔너리
        """
        stop_loss_rates = self.config.stop_loss_rates
        sl_results = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            entry_price = df.iloc[0]['open']

            for sl_rate in stop_loss_rates:
                sl_price = entry_price * (1 + sl_rate)

                # 손절 터치 여부 확인
                sl_touched = False
                exit_price = df.iloc[-1]['close']  # 기본: 종가
                exit_time = df.iloc[-1]['datetime']

                for _, row in df.iloc[1:].iterrows():
                    if row['low'] <= sl_price:
                        sl_touched = True
                        exit_price = sl_price
                        exit_time = row['datetime']
                        break

                realized_return = (exit_price - entry_price) / entry_price * 100

                # 손절 없이 종가까지 보유 시 수익률
                no_sl_return = (df.iloc[-1]['close'] - entry_price) / entry_price * 100

                # 손절 효과 (손절 안 했을 때 대비)
                sl_benefit = realized_return - no_sl_return if sl_touched else 0

                sl_results.append({
                    'stock_name': stock_name,
                    'date': date,
                    'stop_loss_rate': sl_rate * 100,
                    'sl_touched': sl_touched,
                    'realized_return': realized_return,
                    'no_sl_return': no_sl_return,
                    'sl_benefit': sl_benefit,
                })

        if not sl_results:
            return {'raw_data': pd.DataFrame(), 'summary': pd.DataFrame()}

        sl_df = pd.DataFrame(sl_results)

        # 손절 수준별 통계
        summary = sl_df.groupby('stop_loss_rate').agg({
            'sl_touched': 'mean',  # 손절 발동 비율
            'realized_return': ['mean', 'std'],
            'no_sl_return': 'mean',
            'sl_benefit': 'mean',
            'stock_name': 'count',
        }).reset_index()

        summary.columns = [
            'stop_loss_rate', 'trigger_rate', 'avg_return', 'std_return',
            'avg_no_sl_return', 'avg_sl_benefit', 'sample_count'
        ]

        summary['trigger_rate'] = summary['trigger_rate'] * 100

        # 최적 손절 수준
        best_sl = summary.loc[summary['avg_return'].idxmax(), 'stop_loss_rate']

        return {
            'raw_data': sl_df,
            'summary': summary,
            'best_stop_loss': best_sl,
        }

    def _analyze_hourly_performance(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """시간대별 진입 성과 비교

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            시간대별 성과 딕셔너리
        """
        hourly_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)
            close_price = df.iloc[-1]['close']

            # 각 시간대 첫 봉에서 진입
            for hour in range(9, 15):
                hour_df = df[df['datetime'].dt.hour == hour]
                if hour_df.empty:
                    continue

                entry_row = hour_df.iloc[0]
                entry_price = entry_row['open']

                ret = (close_price - entry_price) / entry_price * 100

                # 1시간 후 수익률
                entry_time = entry_row['datetime']
                target_1h = entry_time + pd.Timedelta(hours=1)
                after_1h = df[df['datetime'] >= target_1h]
                ret_1h = (after_1h.iloc[0]['close'] - entry_price) / entry_price * 100 if not after_1h.empty else np.nan

                # 30분 후 수익률
                target_30m = entry_time + pd.Timedelta(minutes=30)
                after_30m = df[df['datetime'] >= target_30m]
                ret_30m = (after_30m.iloc[0]['close'] - entry_price) / entry_price * 100 if not after_30m.empty else np.nan

                hourly_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'entry_hour': hour,
                    'return_to_close': ret,
                    'return_30m': ret_30m,
                    'return_1h': ret_1h,
                })

        if not hourly_data:
            return {'raw_data': pd.DataFrame(), 'summary': pd.DataFrame()}

        hourly_df = pd.DataFrame(hourly_data)

        # 시간대별 통계
        summary = hourly_df.groupby('entry_hour').agg({
            'return_to_close': ['mean', 'median', 'std'],
            'return_30m': 'mean',
            'return_1h': 'mean',
            'stock_name': 'count',
        }).reset_index()

        summary.columns = [
            'entry_hour', 'avg_return', 'median_return', 'std_return',
            'avg_return_30m', 'avg_return_1h', 'sample_count'
        ]

        # 승률
        win_rates = hourly_df.groupby('entry_hour')['return_to_close'].apply(
            lambda x: (x > 0).mean() * 100
        ).reset_index()
        win_rates.columns = ['entry_hour', 'win_rate']

        summary = summary.merge(win_rates, on='entry_hour')

        # 최적 진입 시간
        best_hour = summary.loc[summary['avg_return'].idxmax(), 'entry_hour']

        return {
            'raw_data': hourly_df,
            'summary': summary,
            'best_entry_hour': best_hour,
        }

    def _analyze_entry_signals(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """진입 신호별 분석

        - BandHigh 돌파 시 진입
        - ceiling_break 신호 시 진입
        - 거래량 급증 시 진입

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            진입 신호별 분석 딕셔너리
        """
        signal_results = {
            'band_high_breakout': [],
            'ceiling_break': [],
            'volume_surge': [],
        }

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)
            close_price = df.iloc[-1]['close']

            # 1. BandHigh 돌파 신호
            if 'band_high' in df.columns:
                df['bh_breakout'] = df['close'] > df['band_high']
                if df['bh_breakout'].any():
                    idx = df['bh_breakout'].idxmax()
                    entry_price = df.loc[idx, 'close']
                    ret = (close_price - entry_price) / entry_price * 100
                    signal_results['band_high_breakout'].append({
                        'stock_name': stock_name,
                        'date': date,
                        'return_to_close': ret,
                    })

            # 2. ceiling_break 신호
            if 'ceiling_break' in df.columns:
                df['has_cb'] = df['ceiling_break'] > 0
                if df['has_cb'].any():
                    idx = df['has_cb'].idxmax()
                    entry_price = df.loc[idx, 'close']
                    ret = (close_price - entry_price) / entry_price * 100
                    signal_results['ceiling_break'].append({
                        'stock_name': stock_name,
                        'date': date,
                        'return_to_close': ret,
                    })

            # 3. 거래량 급증 신호
            if 'trading_value' in df.columns:
                df['prev_value'] = df['trading_value'].shift(1)
                df['value_ratio'] = df['trading_value'] / df['prev_value']
                df['volume_surge'] = df['value_ratio'] >= 2.0

                if df['volume_surge'].any():
                    idx = df['volume_surge'].idxmax()
                    entry_price = df.loc[idx, 'close']
                    ret = (close_price - entry_price) / entry_price * 100
                    signal_results['volume_surge'].append({
                        'stock_name': stock_name,
                        'date': date,
                        'return_to_close': ret,
                    })

        # 각 신호별 통계
        summary = {}
        for signal_name, results in signal_results.items():
            if not results:
                continue

            signal_df = pd.DataFrame(results)
            summary[signal_name] = {
                'count': len(signal_df),
                'avg_return': signal_df['return_to_close'].mean(),
                'median_return': signal_df['return_to_close'].median(),
                'std_return': signal_df['return_to_close'].std(),
                'win_rate': (signal_df['return_to_close'] > 0).mean() * 100,
            }

        return {
            'raw_data': {k: pd.DataFrame(v) for k, v in signal_results.items()},
            'summary': summary,
        }

    def _empty_result(self) -> EntryTimingResult:
        """빈 결과 반환"""
        return EntryTimingResult(
            optimal_entry_time={'raw_data': pd.DataFrame(), 'optimal_wait': None},
            stop_loss_effectiveness={'raw_data': pd.DataFrame()},
            hourly_performance={'raw_data': pd.DataFrame()},
            entry_signals_analysis={'raw_data': {}, 'summary': {}},
        )
