# -*- coding: utf-8 -*-
"""
보유 시간별 수익률 분석
V6.2-Q

- 5분, 15분, 30분, 1시간, 2시간 보유 수익률
- 종가 보유 수익률
- 최적 보유 시간 도출
- 시간대별 보유 효율 비교
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class HoldingPeriodResult:
    """보유 시간별 분석 결과"""
    period_returns: pd.DataFrame       # 각 보유 기간별 수익률
    optimal_period: Dict               # 최적 보유 시간
    entry_time_efficiency: pd.DataFrame  # 진입 시간대별 효율
    risk_reward_analysis: Dict         # 리스크/보상 분석


class HoldingPeriodAnalyzer:
    """보유 시간별 수익률 분석기"""

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> HoldingPeriodResult:
        """보유 시간별 분석 실행

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트

        Returns:
            HoldingPeriodResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 각 보유 기간별 수익률 분석
        period_returns = self._analyze_period_returns(event_days)

        # 2. 최적 보유 시간 도출
        optimal_period = self._find_optimal_period(period_returns)

        # 3. 진입 시간대별 효율
        entry_time_efficiency = self._analyze_entry_time_efficiency(event_days)

        # 4. 리스크/보상 분석
        risk_reward_analysis = self._analyze_risk_reward(event_days)

        return HoldingPeriodResult(
            period_returns=period_returns,
            optimal_period=optimal_period,
            entry_time_efficiency=entry_time_efficiency,
            risk_reward_analysis=risk_reward_analysis,
        )

    def _analyze_period_returns(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """각 보유 기간별 수익률 분석 (시가 기준 진입)

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            보유 기간별 통계 DataFrame
        """
        holding_periods = self.config.holding_periods_minutes
        all_returns = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            # 시가 진입 가정 (첫 봉의 시가)
            entry_price = df.iloc[0]['open']
            entry_time = df.iloc[0]['datetime']

            entry_data = {
                'stock_name': stock_name,
                'date': date,
                'entry_price': entry_price,
            }

            # 각 보유 기간별 수익률
            for minutes in holding_periods:
                target_time = entry_time + pd.Timedelta(minutes=minutes)
                future_df = df[df['datetime'] >= target_time]

                if future_df.empty:
                    entry_data[f'return_{minutes}m'] = np.nan
                    entry_data[f'mfe_{minutes}m'] = np.nan
                    entry_data[f'mae_{minutes}m'] = np.nan
                else:
                    # 해당 시점 수익률
                    exit_price = future_df.iloc[0]['close']
                    ret = (exit_price - entry_price) / entry_price * 100
                    entry_data[f'return_{minutes}m'] = ret

                    # 해당 기간 내 MFE/MAE
                    period_df = df[(df['datetime'] >= entry_time) & (df['datetime'] < target_time)]
                    if not period_df.empty:
                        mfe = (period_df['high'].max() - entry_price) / entry_price * 100
                        mae = (period_df['low'].min() - entry_price) / entry_price * 100
                        entry_data[f'mfe_{minutes}m'] = mfe
                        entry_data[f'mae_{minutes}m'] = mae
                    else:
                        entry_data[f'mfe_{minutes}m'] = np.nan
                        entry_data[f'mae_{minutes}m'] = np.nan

            # 종가 수익률
            close_price = df.iloc[-1]['close']
            entry_data['return_to_close'] = (close_price - entry_price) / entry_price * 100

            all_returns.append(entry_data)

        if not all_returns:
            return pd.DataFrame()

        returns_df = pd.DataFrame(all_returns)

        # 기간별 통계 요약 생성
        summary_rows = []
        for minutes in holding_periods:
            col = f'return_{minutes}m'
            mfe_col = f'mfe_{minutes}m'
            mae_col = f'mae_{minutes}m'

            valid = returns_df[col].dropna()
            if len(valid) == 0:
                continue

            summary_rows.append({
                'period': f'{minutes}m',
                'minutes': minutes,
                'mean': valid.mean(),
                'median': valid.median(),
                'std': valid.std(),
                'win_rate': (valid > 0).mean() * 100,
                'avg_mfe': returns_df[mfe_col].mean() if mfe_col in returns_df else np.nan,
                'avg_mae': returns_df[mae_col].mean() if mae_col in returns_df else np.nan,
                'sample_count': len(valid),
            })

        # 종가 수익률 추가
        close_valid = returns_df['return_to_close'].dropna()
        if len(close_valid) > 0:
            summary_rows.append({
                'period': 'to_close',
                'minutes': 9999,
                'mean': close_valid.mean(),
                'median': close_valid.median(),
                'std': close_valid.std(),
                'win_rate': (close_valid > 0).mean() * 100,
                'avg_mfe': np.nan,
                'avg_mae': np.nan,
                'sample_count': len(close_valid),
            })

        return {
            'raw_data': returns_df,
            'summary': pd.DataFrame(summary_rows),
        }

    def _find_optimal_period(self, period_returns: Dict) -> Dict:
        """최적 보유 시간 도출

        수익률/리스크 비율 및 승률 기준

        Args:
            period_returns: 기간별 수익률 딕셔너리

        Returns:
            최적 보유 시간 딕셔너리
        """
        if not period_returns or 'summary' not in period_returns:
            return {'optimal_by_mean': None, 'optimal_by_sharpe': None}

        summary = period_returns['summary']
        if summary.empty:
            return {'optimal_by_mean': None, 'optimal_by_sharpe': None}

        # 종가 제외
        analysis_df = summary[summary['minutes'] < 9999].copy()

        if analysis_df.empty:
            return {'optimal_by_mean': None, 'optimal_by_sharpe': None}

        # 평균 수익률 기준 최적
        optimal_by_mean = analysis_df.loc[analysis_df['mean'].idxmax(), 'period']

        # Sharpe-like ratio (mean/std) 기준 최적
        analysis_df['sharpe_like'] = analysis_df['mean'] / analysis_df['std'].replace(0, np.nan)
        optimal_by_sharpe_idx = analysis_df['sharpe_like'].idxmax()
        optimal_by_sharpe = analysis_df.loc[optimal_by_sharpe_idx, 'period'] if pd.notna(optimal_by_sharpe_idx) else None

        # 승률 기준 최적
        optimal_by_winrate = analysis_df.loc[analysis_df['win_rate'].idxmax(), 'period']

        return {
            'optimal_by_mean': optimal_by_mean,
            'optimal_by_sharpe': optimal_by_sharpe,
            'optimal_by_winrate': optimal_by_winrate,
            'analysis': analysis_df[['period', 'mean', 'std', 'win_rate', 'sharpe_like']].to_dict('records'),
        }

    def _analyze_entry_time_efficiency(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> pd.DataFrame:
        """진입 시간대별 보유 효율 분석

        09시 진입 vs 10시 진입 vs 11시 진입 등 비교

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            진입 시간대별 효율 DataFrame
        """
        entry_hours = [9, 10, 11, 12, 13, 14]
        efficiency_data = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            for entry_hour in entry_hours:
                # 해당 시간의 첫 봉 찾기
                hour_df = df[df['datetime'].dt.hour == entry_hour]
                if hour_df.empty:
                    continue

                entry_row = hour_df.iloc[0]
                entry_price = entry_row['open']
                entry_time = entry_row['datetime']

                # 종가까지 수익률
                close_price = df.iloc[-1]['close']
                return_to_close = (close_price - entry_price) / entry_price * 100

                # 진입 후 MFE/MAE
                after_entry = df[df['datetime'] >= entry_time]
                if after_entry.empty:
                    continue

                mfe = (after_entry['high'].max() - entry_price) / entry_price * 100
                mae = (after_entry['low'].min() - entry_price) / entry_price * 100

                # 1시간 보유 수익률
                target_1h = entry_time + pd.Timedelta(hours=1)
                after_1h = df[df['datetime'] >= target_1h]
                return_1h = (after_1h.iloc[0]['close'] - entry_price) / entry_price * 100 if not after_1h.empty else np.nan

                efficiency_data.append({
                    'stock_name': stock_name,
                    'date': date,
                    'entry_hour': entry_hour,
                    'return_to_close': return_to_close,
                    'return_1h': return_1h,
                    'mfe': mfe,
                    'mae': mae,
                    'efficiency': return_to_close / mfe * 100 if mfe > 0 else 0,
                })

        if not efficiency_data:
            return pd.DataFrame()

        eff_df = pd.DataFrame(efficiency_data)

        # 시간대별 통계
        summary = eff_df.groupby('entry_hour').agg({
            'return_to_close': ['mean', 'median', 'std'],
            'return_1h': 'mean',
            'mfe': 'mean',
            'mae': 'mean',
            'efficiency': 'mean',
            'stock_name': 'count',
        }).reset_index()

        summary.columns = [
            'entry_hour', 'avg_return', 'median_return', 'std_return',
            'avg_return_1h', 'avg_mfe', 'avg_mae', 'avg_efficiency', 'sample_count'
        ]

        return {
            'raw_data': eff_df,
            'summary': summary,
        }

    def _analyze_risk_reward(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]]
    ) -> Dict:
        """리스크/보상 분석

        - 손절 수준별 결과 시뮬레이션
        - 익절 수준별 결과 시뮬레이션

        Args:
            event_days: 이벤트 데이터 리스트

        Returns:
            리스크/보상 분석 딕셔너리
        """
        stop_loss_rates = self.config.stop_loss_rates
        take_profit_rates = [0.02, 0.03, 0.05, 0.07, 0.10]  # 2%, 3%, 5%, 7%, 10%

        simulation_results = []

        for stock_name, date, df in event_days:
            if df.empty:
                continue

            df = df.copy().reset_index(drop=True)

            entry_price = df.iloc[0]['open']
            entry_time = df.iloc[0]['datetime']

            for sl_rate in stop_loss_rates:
                for tp_rate in take_profit_rates:
                    sl_price = entry_price * (1 + sl_rate)
                    tp_price = entry_price * (1 + tp_rate)

                    # 봉 순회하면서 먼저 닿는 것 확인
                    result = 'hold'  # 기본값
                    exit_price = df.iloc[-1]['close']  # 종가

                    for _, row in df.iloc[1:].iterrows():
                        if row['low'] <= sl_price:
                            result = 'stop_loss'
                            exit_price = sl_price
                            break
                        elif row['high'] >= tp_price:
                            result = 'take_profit'
                            exit_price = tp_price
                            break

                    realized_return = (exit_price - entry_price) / entry_price * 100

                    simulation_results.append({
                        'stock_name': stock_name,
                        'date': date,
                        'stop_loss': sl_rate * 100,
                        'take_profit': tp_rate * 100,
                        'result': result,
                        'realized_return': realized_return,
                    })

        if not simulation_results:
            return {'raw_data': pd.DataFrame(), 'summary': pd.DataFrame()}

        sim_df = pd.DataFrame(simulation_results)

        # 각 SL/TP 조합별 통계
        summary = sim_df.groupby(['stop_loss', 'take_profit']).agg({
            'realized_return': ['mean', 'std'],
            'result': lambda x: (x == 'take_profit').mean() * 100,  # TP 비율
            'stock_name': 'count',
        }).reset_index()

        summary.columns = [
            'stop_loss', 'take_profit', 'avg_return', 'std_return',
            'tp_hit_rate', 'sample_count'
        ]

        # 최적 SL/TP 찾기
        if not summary.empty:
            best_by_return = summary.loc[summary['avg_return'].idxmax()]
            best_by_sharpe = summary.loc[(summary['avg_return'] / summary['std_return'].replace(0, np.nan)).idxmax()]
        else:
            best_by_return = None
            best_by_sharpe = None

        return {
            'raw_data': sim_df,
            'summary': summary,
            'best_by_return': best_by_return.to_dict() if best_by_return is not None else None,
            'best_by_sharpe': best_by_sharpe.to_dict() if best_by_sharpe is not None else None,
        }

    def _empty_result(self) -> HoldingPeriodResult:
        """빈 결과 반환"""
        return HoldingPeriodResult(
            period_returns=pd.DataFrame(),
            optimal_period={'optimal_by_mean': None, 'optimal_by_sharpe': None},
            entry_time_efficiency=pd.DataFrame(),
            risk_reward_analysis={'raw_data': pd.DataFrame()},
        )
