# -*- coding: utf-8 -*-
"""
파라미터 최적화 모듈

근접% 그리드 서치 및 손절 방식 비교
"""

from typing import List, Dict, Tuple
from dataclasses import dataclass
from copy import deepcopy
import pandas as pd

from .config import (
    EMASplitBuyConfig,
    SplitBuyTrade,
    SplitBuySignal,
    StopLossType,
    OptimizationResult,
    PROXIMITY_GRID,
    STOP_LOSS_TYPES
)
from .signal_detector import SignalDetector
from .trade_simulator import TradeSimulator


class Optimizer:
    """파라미터 최적화기"""

    def __init__(self, base_config: EMASplitBuyConfig, logger=None):
        self.base_config = base_config
        self._logger = logger

    def run_grid_search(
        self,
        stocks_data: Dict[str, pd.DataFrame],
        stock_info: Dict[str, str],
        proximity_grid: List[float] = None,
        stop_loss_types: List[StopLossType] = None
    ) -> List[OptimizationResult]:
        """
        그리드 서치 실행

        Args:
            stocks_data: {stock_code: DataFrame} 종목별 일봉 데이터
            stock_info: {stock_code: stock_name} 종목 정보
            proximity_grid: 근접% 그리드 (기본: [0.5, 1.0, 1.5, 2.0, 2.5, 3.0])
            stop_loss_types: 손절 방식 (기본: [FIXED_5%, ATR_TS])

        Returns:
            최적화 결과 리스트
        """
        if proximity_grid is None:
            proximity_grid = PROXIMITY_GRID
        if stop_loss_types is None:
            stop_loss_types = STOP_LOSS_TYPES

        results = []
        total_combinations = len(proximity_grid) ** 2 * len(stop_loss_types)
        current = 0

        for ema5_pct in proximity_grid:
            for ema8_pct in proximity_grid:
                for stop_type in stop_loss_types:
                    current += 1
                    if self._logger:
                        self._logger.info(
                            f"최적화 진행 중... {current}/{total_combinations} "
                            f"(EMA5: {ema5_pct}%, EMA8: {ema8_pct}%, Stop: {stop_type.value})"
                        )

                    # 설정 복사 및 수정
                    config = deepcopy(self.base_config)
                    config.ema5_proximity_pct = ema5_pct
                    config.ema8_proximity_pct = ema8_pct
                    config.stop_loss_type = stop_type

                    # 백테스트 실행
                    result = self._run_single_backtest(
                        config=config,
                        stocks_data=stocks_data,
                        stock_info=stock_info
                    )

                    results.append(result)

        return results

    def _run_single_backtest(
        self,
        config: EMASplitBuyConfig,
        stocks_data: Dict[str, pd.DataFrame],
        stock_info: Dict[str, str]
    ) -> OptimizationResult:
        """
        단일 설정으로 백테스트 실행

        Args:
            config: 백테스트 설정
            stocks_data: 종목별 일봉 데이터
            stock_info: 종목 정보

        Returns:
            최적화 결과
        """
        detector = SignalDetector(config)
        simulator = TradeSimulator(config)

        all_trades = []

        for stock_code, df in stocks_data.items():
            stock_name = stock_info.get(stock_code, stock_code)

            # 1차 매수 신호 탐지 (EMA5 근접만)
            signals = detector.detect_first_buy_signals(df, stock_code, stock_name)

            # 거래 시뮬레이션
            trades = simulator.simulate_trades(df, signals, stock_code, stock_name)
            all_trades.extend(trades)

        # 결과 집계
        summary = simulator.calculate_summary(all_trades)

        return OptimizationResult(
            ema5_proximity_pct=config.ema5_proximity_pct,
            ema8_proximity_pct=config.ema8_proximity_pct,
            stop_loss_type=config.stop_loss_type,
            trade_count=summary["trade_count"],
            win_rate=summary["win_rate"],
            avg_return=summary["avg_return"],
            total_net_pnl=summary["total_net_pnl"],
            profit_factor=summary["profit_factor"],
            max_drawdown=0,  # MDD는 별도 계산 필요
            hard_stop_count=summary["hard_stop_count"],
            atr_ts_count=summary["atr_ts_count"],
            max_holding_count=summary["max_holding_count"]
        )

    def find_best_parameters(
        self,
        results: List[OptimizationResult],
        metric: str = "profit_factor"
    ) -> OptimizationResult:
        """
        최적 파라미터 찾기

        Args:
            results: 최적화 결과 리스트
            metric: 최적화 기준 ("profit_factor", "win_rate", "avg_return", "total_net_pnl")

        Returns:
            최적 결과
        """
        if not results:
            return None

        # 최소 거래 수 필터 (최소 10건)
        valid_results = [r for r in results if r.trade_count >= 10]
        if not valid_results:
            valid_results = results

        if metric == "profit_factor":
            return max(valid_results, key=lambda r: r.profit_factor if r.profit_factor != float('inf') else 0)
        elif metric == "win_rate":
            return max(valid_results, key=lambda r: r.win_rate)
        elif metric == "avg_return":
            return max(valid_results, key=lambda r: r.avg_return)
        elif metric == "total_net_pnl":
            return max(valid_results, key=lambda r: r.total_net_pnl)
        else:
            return max(valid_results, key=lambda r: r.profit_factor if r.profit_factor != float('inf') else 0)

    def compare_stop_loss_types(
        self,
        results: List[OptimizationResult]
    ) -> Dict[StopLossType, Dict]:
        """
        손절 방식별 비교

        Args:
            results: 최적화 결과 리스트

        Returns:
            손절 방식별 통계
        """
        comparison = {}

        for stop_type in STOP_LOSS_TYPES:
            type_results = [r for r in results if r.stop_loss_type == stop_type]

            if not type_results:
                comparison[stop_type] = {
                    "count": 0,
                    "avg_win_rate": 0,
                    "avg_return": 0,
                    "avg_profit_factor": 0,
                    "total_trades": 0
                }
                continue

            # 평균 통계
            avg_win_rate = sum(r.win_rate for r in type_results) / len(type_results)
            avg_return = sum(r.avg_return for r in type_results) / len(type_results)

            # Profit Factor (inf 제외)
            valid_pf = [r.profit_factor for r in type_results if r.profit_factor != float('inf')]
            avg_pf = sum(valid_pf) / len(valid_pf) if valid_pf else 0

            total_trades = sum(r.trade_count for r in type_results)

            comparison[stop_type] = {
                "count": len(type_results),
                "avg_win_rate": avg_win_rate,
                "avg_return": avg_return,
                "avg_profit_factor": avg_pf,
                "total_trades": total_trades
            }

        return comparison

    def get_top_results(
        self,
        results: List[OptimizationResult],
        top_n: int = 10,
        metric: str = "profit_factor"
    ) -> List[OptimizationResult]:
        """
        상위 N개 결과 반환

        Args:
            results: 최적화 결과 리스트
            top_n: 반환할 개수
            metric: 정렬 기준

        Returns:
            상위 N개 결과
        """
        # 최소 거래 수 필터
        valid_results = [r for r in results if r.trade_count >= 5]

        if metric == "profit_factor":
            sorted_results = sorted(
                valid_results,
                key=lambda r: r.profit_factor if r.profit_factor != float('inf') else 0,
                reverse=True
            )
        elif metric == "win_rate":
            sorted_results = sorted(valid_results, key=lambda r: r.win_rate, reverse=True)
        elif metric == "avg_return":
            sorted_results = sorted(valid_results, key=lambda r: r.avg_return, reverse=True)
        else:
            sorted_results = sorted(valid_results, key=lambda r: r.total_net_pnl, reverse=True)

        return sorted_results[:top_n]

    def results_to_dataframe(
        self,
        results: List[OptimizationResult]
    ) -> pd.DataFrame:
        """
        결과를 DataFrame으로 변환

        Args:
            results: 최적화 결과 리스트

        Returns:
            DataFrame
        """
        data = []
        for r in results:
            data.append({
                "EMA5_근접%": r.ema5_proximity_pct,
                "EMA8_근접%": r.ema8_proximity_pct,
                "손절방식": r.stop_loss_type.value,
                "거래수": r.trade_count,
                "승률%": round(r.win_rate, 2),
                "평균수익률%": round(r.avg_return, 2),
                "순손익": r.total_net_pnl,
                "Profit_Factor": round(r.profit_factor, 2) if r.profit_factor != float('inf') else "∞",
                "고정손절": r.hard_stop_count,
                "ATR_TS": r.atr_ts_count,
                "보유일초과": r.max_holding_count
            })

        return pd.DataFrame(data)
