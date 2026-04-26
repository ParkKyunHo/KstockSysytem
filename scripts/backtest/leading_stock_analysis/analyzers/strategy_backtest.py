# -*- coding: utf-8 -*-
"""
SNIPER_TRAP 전략 백테스트 분석
V6.2-Q

3분봉 데이터에 실제 SNIPER_TRAP 전략 조건을 적용하여
시간대별, 조건별 성과를 분석
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from collections import defaultdict
from dataclasses import dataclass
import logging

from ..config import DEFAULT_CONFIG, AnalysisConfig

logger = logging.getLogger(__name__)


@dataclass
class StrategyBacktestResult:
    """전략 백테스트 결과"""
    signals: pd.DataFrame                  # 발생한 신호 목록
    time_analysis: pd.DataFrame            # 시간대별 성과
    condition_analysis: Dict               # 조건별 성과
    parameter_sensitivity: Dict            # 파라미터 민감도
    optimal_conditions: Dict               # 최적 조건


class StrategyBacktestAnalyzer:
    """SNIPER_TRAP 전략 백테스트 분석기"""

    # SNIPER_TRAP 기본 파라미터
    EMA_SHORT = 3
    EMA_MID = 20
    EMA_LONG = 60
    EMA_TREND = 200
    ANGLE_PERIOD = 5
    MIN_BODY_SIZE = 0.3  # %

    def __init__(self, config: AnalysisConfig = None):
        self.config = config or DEFAULT_CONFIG

    def ema(self, series: pd.Series, period: int) -> pd.Series:
        """EMA 계산 (adjust=False)"""
        return series.ewm(span=period, adjust=False).mean()

    def analyze(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]],
        full_data_dict: Dict[str, pd.DataFrame] = None
    ) -> StrategyBacktestResult:
        """전략 백테스트 분석

        Args:
            event_days: [(종목명, 날짜, 3분봉 DataFrame), ...] 리스트
            full_data_dict: 종목별 전체 히스토리 (EMA 계산용)

        Returns:
            StrategyBacktestResult
        """
        if not event_days:
            return self._empty_result()

        # 1. 모든 이벤트에서 SNIPER_TRAP 신호 탐지
        all_signals = self._detect_all_signals(event_days, full_data_dict)

        if all_signals.empty:
            logger.warning("No SNIPER_TRAP signals detected")
            return self._empty_result()

        # 2. 시간대별 성과 분석
        time_analysis = self._analyze_by_time(all_signals)

        # 3. 조건별 성과 분석
        condition_analysis = self._analyze_by_condition(all_signals)

        # 4. 파라미터 민감도 분석
        parameter_sensitivity = self._analyze_parameter_sensitivity(event_days, full_data_dict)

        # 5. 최적 조건 도출
        optimal_conditions = self._find_optimal_conditions(all_signals, time_analysis)

        return StrategyBacktestResult(
            signals=all_signals,
            time_analysis=time_analysis,
            condition_analysis=condition_analysis,
            parameter_sensitivity=parameter_sensitivity,
            optimal_conditions=optimal_conditions,
        )

    def _detect_all_signals(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]],
        full_data_dict: Dict[str, pd.DataFrame] = None
    ) -> pd.DataFrame:
        """모든 이벤트에서 SNIPER_TRAP 신호 탐지

        전체 히스토리를 사용하여 EMA를 계산하고, 이벤트 발생일에서 신호 탐지

        Args:
            event_days: 이벤트 데이터 리스트
            full_data_dict: 종목별 전체 히스토리 (EMA 계산용)

        Returns:
            신호 DataFrame
        """
        signals = []

        # 종목별로 이벤트 그룹화
        events_by_stock = defaultdict(list)
        for stock_name, date, df in event_days:
            events_by_stock[stock_name].append((date, df))

        for stock_name, events in events_by_stock.items():
            # 전체 히스토리 가져오기
            if full_data_dict and stock_name in full_data_dict:
                full_df = full_data_dict[stock_name].copy()
            else:
                # full_data_dict 없으면 이벤트 데이터 연결
                all_dfs = [df for _, df in events]
                full_df = pd.concat(all_dfs, ignore_index=True)
                full_df = full_df.sort_values('datetime').drop_duplicates(subset='datetime')
                full_df = full_df.reset_index(drop=True)

            if len(full_df) < self.EMA_TREND + self.ANGLE_PERIOD:
                logger.debug(f"{stock_name}: 데이터 부족 ({len(full_df)}봉)")
                continue

            # 전체 히스토리에서 EMA 계산
            full_df['ema3'] = self.ema(full_df['close'], self.EMA_SHORT)
            full_df['ema20'] = self.ema(full_df['close'], self.EMA_MID)
            full_df['ema60'] = self.ema(full_df['close'], self.EMA_LONG)
            full_df['ema200'] = self.ema(full_df['close'], self.EMA_TREND)

            # 이벤트 날짜별로 신호 탐지
            for date, event_df in events:
                day_signals = self._detect_signals_for_day_with_ema(
                    full_df, event_df, stock_name, date
                )
                signals.extend(day_signals)

        if not signals:
            return pd.DataFrame()

        return pd.DataFrame(signals)

    def _detect_signals_for_day(
        self,
        df: pd.DataFrame,
        stock_name: str,
        date: str
    ) -> List[Dict]:
        """하루 데이터에서 신호 탐지

        Args:
            df: 3분봉 DataFrame
            stock_name: 종목명
            date: 날짜

        Returns:
            신호 딕셔너리 리스트
        """
        signals = []
        df = df.copy().reset_index(drop=True)

        # EMA 계산
        df['ema3'] = self.ema(df['close'], self.EMA_SHORT)
        df['ema20'] = self.ema(df['close'], self.EMA_MID)
        df['ema60'] = self.ema(df['close'], self.EMA_LONG)
        df['ema200'] = self.ema(df['close'], self.EMA_TREND)

        # 종가 계산 (수익률용)
        close_price = df.iloc[-1]['close']

        # 각 봉에서 신호 체크
        for i in range(self.ANGLE_PERIOD + 1, len(df)):
            row = df.iloc[i]
            prev = df.iloc[i - 1]
            ema60_5ago = df.iloc[i - self.ANGLE_PERIOD]['ema60']

            # NaN 체크
            if any(pd.isna([row['ema3'], row['ema20'], row['ema60'], row['ema200'], ema60_5ago])):
                continue

            # ============================================
            # SNIPER_TRAP 조건 체크
            # ============================================

            # 1. TrendFilter: C > EMA200 AND EMA60 > EMA60(5)
            trend_filter = (row['close'] > row['ema200']) and (row['ema60'] > ema60_5ago)

            # 2. Zone: L <= EMA20 AND C >= EMA60
            zone = (row['low'] <= row['ema20']) and (row['close'] >= row['ema60'])

            # 3. Meaningful: CrossUp(C, EMA3) + 양봉 + 거래량 증가
            prev_below_m3 = prev['close'] < prev['ema3']
            curr_above_m3 = row['close'] >= row['ema3']
            crossup_m3 = prev_below_m3 and curr_above_m3
            is_bullish = row['close'] > row['open']

            # 거래량 비교 (trading_value 사용)
            if 'trading_value' in df.columns:
                volume_increase = row['trading_value'] >= prev['trading_value']
                volume_ratio = row['trading_value'] / prev['trading_value'] if prev['trading_value'] > 0 else 0
            else:
                volume_increase = True  # 거래량 데이터 없으면 통과
                volume_ratio = 1.0

            meaningful = crossup_m3 and is_bullish and volume_increase

            # 4. BodySize: (C-O)/O >= 0.3%
            if row['open'] == 0:
                continue
            body_size_pct = (row['close'] - row['open']) / row['open'] * 100
            body_size_ok = body_size_pct >= self.MIN_BODY_SIZE

            # ============================================
            # 신호 발생 시 기록
            # ============================================
            if trend_filter and zone and meaningful and body_size_ok:
                entry_price = row['close']
                entry_time = row['datetime']

                # 수익률 계산
                return_to_close = (close_price - entry_price) / entry_price * 100

                # 이후 데이터에서 MFE/MAE 계산
                after_entry = df.iloc[i:]
                mfe = (after_entry['high'].max() - entry_price) / entry_price * 100
                mae = (after_entry['low'].min() - entry_price) / entry_price * 100

                # N분 후 수익률
                returns = {}
                for minutes in [15, 30, 60, 120]:
                    target_time = entry_time + pd.Timedelta(minutes=minutes)
                    future = df[df['datetime'] >= target_time]
                    if not future.empty:
                        future_price = future.iloc[0]['close']
                        returns[f'return_{minutes}m'] = (future_price - entry_price) / entry_price * 100
                    else:
                        returns[f'return_{minutes}m'] = np.nan

                # EMA 이격도
                ema20_divergence = (entry_price - row['ema20']) / row['ema20'] * 100
                ema60_divergence = (entry_price - row['ema60']) / row['ema60'] * 100

                signals.append({
                    'stock_name': stock_name,
                    'date': date,
                    'entry_time': entry_time.strftime('%H:%M'),
                    'entry_hour': entry_time.hour,
                    'entry_minute': entry_time.minute,
                    'entry_price': entry_price,
                    'close_price': close_price,
                    'return_to_close': return_to_close,
                    'mfe': mfe,
                    'mae': mae,
                    **returns,
                    'body_size_pct': body_size_pct,
                    'volume_ratio': volume_ratio,
                    'ema20_divergence': ema20_divergence,
                    'ema60_divergence': ema60_divergence,
                    # 개별 조건 충족 여부 (분석용)
                    'trend_filter': trend_filter,
                    'zone': zone,
                    'meaningful': meaningful,
                    'body_size_ok': body_size_ok,
                })

                # 하루에 첫 신호만 (중복 방지)
                break

        return signals

    def _detect_signals_for_day_with_ema(
        self,
        full_df: pd.DataFrame,
        event_df: pd.DataFrame,
        stock_name: str,
        date: str
    ) -> List[Dict]:
        """전체 히스토리의 EMA를 사용하여 이벤트일 신호 탐지

        Args:
            full_df: EMA가 계산된 전체 히스토리 DataFrame
            event_df: 이벤트 발생일 DataFrame
            stock_name: 종목명
            date: 날짜

        Returns:
            신호 딕셔너리 리스트
        """
        signals = []

        # 이벤트일 데이터의 datetime 범위 파악
        if event_df.empty:
            return signals

        event_date = pd.to_datetime(date).date()
        event_start = event_df['datetime'].min()
        event_end = event_df['datetime'].max()

        # 전체 히스토리에서 이벤트일 데이터 찾기
        day_mask = full_df['datetime'].dt.date == event_date
        day_df = full_df[day_mask].copy()

        if len(day_df) < self.ANGLE_PERIOD + 1:
            return signals

        # 종가 계산 (수익률용)
        close_price = day_df.iloc[-1]['close']

        # 각 봉에서 신호 체크
        day_indices = day_df.index.tolist()

        for idx in day_indices:
            # 전체 히스토리에서의 위치 확인
            pos = full_df.index.get_loc(idx)
            if pos < self.ANGLE_PERIOD:
                continue

            row = full_df.loc[idx]
            prev_idx = full_df.index[pos - 1]
            prev = full_df.loc[prev_idx]
            ema60_5ago_idx = full_df.index[pos - self.ANGLE_PERIOD]
            ema60_5ago = full_df.loc[ema60_5ago_idx]['ema60']

            # NaN 체크
            if any(pd.isna([row['ema3'], row['ema20'], row['ema60'], row['ema200'], ema60_5ago])):
                continue

            # ============================================
            # SNIPER_TRAP 조건 체크
            # ============================================

            # 1. TrendFilter: C > EMA200 AND EMA60 > EMA60(5)
            trend_filter = (row['close'] > row['ema200']) and (row['ema60'] > ema60_5ago)

            # 2. Zone: L <= EMA20 AND C >= EMA60
            zone = (row['low'] <= row['ema20']) and (row['close'] >= row['ema60'])

            # 3. Meaningful: CrossUp(C, EMA3) + 양봉 + 거래량 증가
            prev_below_m3 = prev['close'] < prev['ema3']
            curr_above_m3 = row['close'] >= row['ema3']
            crossup_m3 = prev_below_m3 and curr_above_m3
            is_bullish = row['close'] > row['open']

            # 거래량 비교 (trading_value 사용)
            if 'trading_value' in full_df.columns:
                volume_increase = row['trading_value'] >= prev['trading_value']
                volume_ratio = row['trading_value'] / prev['trading_value'] if prev['trading_value'] > 0 else 0
            else:
                volume_increase = True
                volume_ratio = 1.0

            meaningful = crossup_m3 and is_bullish and volume_increase

            # 4. BodySize: (C-O)/O >= 0.3%
            if row['open'] == 0:
                continue
            body_size_pct = (row['close'] - row['open']) / row['open'] * 100
            body_size_ok = body_size_pct >= self.MIN_BODY_SIZE

            # ============================================
            # 신호 발생 시 기록
            # ============================================
            if trend_filter and zone and meaningful and body_size_ok:
                entry_price = row['close']
                entry_time = row['datetime']

                # 수익률 계산
                return_to_close = (close_price - entry_price) / entry_price * 100

                # 이후 데이터에서 MFE/MAE 계산 (당일 데이터만)
                after_entry = day_df[day_df['datetime'] >= entry_time]
                if after_entry.empty:
                    continue

                mfe = (after_entry['high'].max() - entry_price) / entry_price * 100
                mae = (after_entry['low'].min() - entry_price) / entry_price * 100

                # N분 후 수익률
                returns = {}
                for minutes in [15, 30, 60, 120]:
                    target_time = entry_time + pd.Timedelta(minutes=minutes)
                    future = day_df[day_df['datetime'] >= target_time]
                    if not future.empty:
                        future_price = future.iloc[0]['close']
                        returns[f'return_{minutes}m'] = (future_price - entry_price) / entry_price * 100
                    else:
                        returns[f'return_{minutes}m'] = np.nan

                # EMA 이격도
                ema20_divergence = (entry_price - row['ema20']) / row['ema20'] * 100
                ema60_divergence = (entry_price - row['ema60']) / row['ema60'] * 100

                signals.append({
                    'stock_name': stock_name,
                    'date': date,
                    'entry_time': entry_time.strftime('%H:%M'),
                    'entry_hour': entry_time.hour,
                    'entry_minute': entry_time.minute,
                    'entry_price': entry_price,
                    'close_price': close_price,
                    'return_to_close': return_to_close,
                    'mfe': mfe,
                    'mae': mae,
                    **returns,
                    'body_size_pct': body_size_pct,
                    'volume_ratio': volume_ratio,
                    'ema20_divergence': ema20_divergence,
                    'ema60_divergence': ema60_divergence,
                    # 개별 조건 충족 여부 (분석용)
                    'trend_filter': trend_filter,
                    'zone': zone,
                    'meaningful': meaningful,
                    'body_size_ok': body_size_ok,
                })

                # 하루에 첫 신호만 (중복 방지)
                break

        return signals

    def _analyze_by_time(self, signals: pd.DataFrame) -> pd.DataFrame:
        """시간대별 성과 분석

        Args:
            signals: 신호 DataFrame

        Returns:
            시간대별 성과 DataFrame
        """
        if signals.empty:
            return pd.DataFrame()

        # 시간대별 그룹화
        time_stats = signals.groupby('entry_hour').agg({
            'return_to_close': ['mean', 'median', 'std', 'count'],
            'mfe': 'mean',
            'mae': 'mean',
            'return_15m': 'mean',
            'return_30m': 'mean',
            'return_60m': 'mean',
        }).reset_index()

        time_stats.columns = [
            'entry_hour', 'avg_return', 'median_return', 'std_return', 'signal_count',
            'avg_mfe', 'avg_mae', 'avg_return_15m', 'avg_return_30m', 'avg_return_60m'
        ]

        # 승률 계산
        win_rates = signals.groupby('entry_hour')['return_to_close'].apply(
            lambda x: (x > 0).mean() * 100
        ).reset_index()
        win_rates.columns = ['entry_hour', 'win_rate']

        time_stats = time_stats.merge(win_rates, on='entry_hour')

        # Sharpe-like 계산
        time_stats['sharpe_like'] = time_stats['avg_return'] / time_stats['std_return'].replace(0, np.nan)

        return time_stats.sort_values('entry_hour')

    def _analyze_by_condition(self, signals: pd.DataFrame) -> Dict:
        """조건별 성과 분석

        Args:
            signals: 신호 DataFrame

        Returns:
            조건별 성과 딕셔너리
        """
        if signals.empty:
            return {}

        results = {}

        # 1. 캔들 크기별 분석
        signals['body_size_group'] = pd.cut(
            signals['body_size_pct'],
            bins=[0, 0.5, 1.0, 2.0, np.inf],
            labels=['0.3-0.5%', '0.5-1%', '1-2%', '>2%']
        )
        body_stats = signals.groupby('body_size_group', observed=True).agg({
            'return_to_close': ['mean', 'count'],
            'mfe': 'mean',
        }).reset_index()
        body_stats.columns = ['body_size_group', 'avg_return', 'count', 'avg_mfe']
        results['body_size'] = body_stats

        # 2. 거래량 비율별 분석
        signals['volume_group'] = pd.cut(
            signals['volume_ratio'],
            bins=[0, 1.0, 1.5, 2.0, np.inf],
            labels=['<100%', '100-150%', '150-200%', '>200%']
        )
        volume_stats = signals.groupby('volume_group', observed=True).agg({
            'return_to_close': ['mean', 'count'],
            'mfe': 'mean',
        }).reset_index()
        volume_stats.columns = ['volume_group', 'avg_return', 'count', 'avg_mfe']
        results['volume_ratio'] = volume_stats

        # 3. EMA20 이격도별 분석
        signals['ema20_div_group'] = pd.cut(
            signals['ema20_divergence'],
            bins=[-np.inf, 0, 2, 5, np.inf],
            labels=['<0%', '0-2%', '2-5%', '>5%']
        )
        ema20_stats = signals.groupby('ema20_div_group', observed=True).agg({
            'return_to_close': ['mean', 'count'],
        }).reset_index()
        ema20_stats.columns = ['ema20_div_group', 'avg_return', 'count']
        results['ema20_divergence'] = ema20_stats

        # 4. 시간 + 거래량 조합 분석
        signals['time_volume_combo'] = signals.apply(
            lambda x: f"{x['entry_hour']}시_vol{'>150%' if x['volume_ratio'] >= 1.5 else '<150%'}",
            axis=1
        )
        combo_stats = signals.groupby('time_volume_combo').agg({
            'return_to_close': ['mean', 'count'],
        }).reset_index()
        combo_stats.columns = ['combo', 'avg_return', 'count']
        combo_stats = combo_stats.sort_values('avg_return', ascending=False)
        results['time_volume_combo'] = combo_stats

        return results

    def _analyze_parameter_sensitivity(
        self,
        event_days: List[Tuple[str, str, pd.DataFrame]],
        full_data_dict: Dict[str, pd.DataFrame] = None
    ) -> Dict:
        """파라미터 민감도 분석

        다양한 파라미터 조합으로 백테스트

        Args:
            event_days: 이벤트 데이터 리스트
            full_data_dict: 종목별 전체 히스토리

        Returns:
            파라미터 민감도 딕셔너리
        """
        results = {}

        # 1. BodySize 임계값 민감도
        body_sizes = [0.2, 0.3, 0.4, 0.5, 0.7, 1.0]
        body_results = []

        for min_body in body_sizes:
            original = self.MIN_BODY_SIZE
            self.MIN_BODY_SIZE = min_body
            signals = self._detect_all_signals(event_days, full_data_dict)
            self.MIN_BODY_SIZE = original

            if not signals.empty:
                body_results.append({
                    'min_body_size': min_body,
                    'signal_count': len(signals),
                    'avg_return': signals['return_to_close'].mean(),
                    'win_rate': (signals['return_to_close'] > 0).mean() * 100,
                })

        results['body_size_sensitivity'] = pd.DataFrame(body_results)

        # 2. 시간 필터 민감도
        time_filters = [(9, 0), (9, 20), (9, 30), (10, 0)]
        time_results = []

        # 원본 신호에서 시간 필터 적용
        all_signals = self._detect_all_signals(event_days, full_data_dict)
        if not all_signals.empty:
            for hour, minute in time_filters:
                filtered = all_signals[
                    (all_signals['entry_hour'] > hour) |
                    ((all_signals['entry_hour'] == hour) & (all_signals['entry_minute'] >= minute))
                ]
                if len(filtered) > 0:
                    time_results.append({
                        'start_time': f'{hour:02d}:{minute:02d}',
                        'signal_count': len(filtered),
                        'avg_return': filtered['return_to_close'].mean(),
                        'win_rate': (filtered['return_to_close'] > 0).mean() * 100,
                    })

            results['time_filter_sensitivity'] = pd.DataFrame(time_results)

        return results

    def _find_optimal_conditions(
        self,
        signals: pd.DataFrame,
        time_analysis: pd.DataFrame
    ) -> Dict:
        """최적 조건 도출

        Args:
            signals: 신호 DataFrame
            time_analysis: 시간대별 분석 DataFrame

        Returns:
            최적 조건 딕셔너리
        """
        if signals.empty or time_analysis.empty:
            return {}

        optimal = {}

        # 1. 최적 시간대
        best_time = time_analysis.loc[time_analysis['avg_return'].idxmax()]
        optimal['best_entry_hour'] = {
            'hour': int(best_time['entry_hour']),
            'avg_return': best_time['avg_return'],
            'win_rate': best_time['win_rate'],
            'signal_count': int(best_time['signal_count']),
        }

        # 2. 권장 시간 필터
        good_hours = time_analysis[time_analysis['avg_return'] > time_analysis['avg_return'].median()]
        optimal['recommended_hours'] = good_hours['entry_hour'].tolist()

        # 3. 최적 조건 조합 (상위 20% 신호 분석)
        top_signals = signals.nlargest(int(len(signals) * 0.2), 'return_to_close')
        optimal['top_performers'] = {
            'avg_entry_hour': top_signals['entry_hour'].mean(),
            'avg_body_size': top_signals['body_size_pct'].mean(),
            'avg_volume_ratio': top_signals['volume_ratio'].mean(),
            'avg_ema20_div': top_signals['ema20_divergence'].mean(),
        }

        # 4. 조건 필터 권장
        optimal['recommended_filters'] = []

        # 시간 필터
        if best_time['entry_hour'] <= 10:
            optimal['recommended_filters'].append(
                f"진입 시간: {int(best_time['entry_hour'])}시 (가장 높은 수익률)"
            )

        # 거래량 필터
        high_vol_signals = signals[signals['volume_ratio'] >= 1.5]
        if len(high_vol_signals) > 0:
            high_vol_return = high_vol_signals['return_to_close'].mean()
            low_vol_return = signals[signals['volume_ratio'] < 1.5]['return_to_close'].mean()
            if high_vol_return > low_vol_return * 1.2:
                optimal['recommended_filters'].append(
                    f"거래량 >= 150% (수익률 {high_vol_return:.1f}% vs {low_vol_return:.1f}%)"
                )

        # 캔들 크기 필터
        big_body_signals = signals[signals['body_size_pct'] >= 0.5]
        if len(big_body_signals) > 0:
            big_body_return = big_body_signals['return_to_close'].mean()
            small_body_return = signals[signals['body_size_pct'] < 0.5]['return_to_close'].mean()
            if big_body_return > small_body_return * 1.2:
                optimal['recommended_filters'].append(
                    f"캔들 크기 >= 0.5% (수익률 {big_body_return:.1f}% vs {small_body_return:.1f}%)"
                )

        return optimal

    def _empty_result(self) -> StrategyBacktestResult:
        """빈 결과 반환"""
        return StrategyBacktestResult(
            signals=pd.DataFrame(),
            time_analysis=pd.DataFrame(),
            condition_analysis={},
            parameter_sensitivity={},
            optimal_conditions={},
        )
