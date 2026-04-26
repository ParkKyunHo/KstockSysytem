# -*- coding: utf-8 -*-
"""
엑셀 출력 모듈

백테스트 결과를 엑셀 파일로 저장
- Sheet 1: 요약
- Sheet 2: 거래내역
- Sheet 3: 최적화결과
"""

from pathlib import Path
from datetime import datetime
from typing import List, Dict
import pandas as pd

from collections import defaultdict

from .config import (
    EMASplitBuyConfig,
    SplitBuyTrade,
    SplitBuySignal,
    OptimizationResult,
    StopLossType,
    ExitReason
)


class ExcelExporter:
    """엑셀 출력기"""

    def __init__(self, logger=None):
        self._logger = logger

    def export(
        self,
        output_path: str,
        config: EMASplitBuyConfig,
        trades: List[SplitBuyTrade],
        signals: List[SplitBuySignal],
        summary: Dict,
        optimization_results: List[OptimizationResult] = None,
        include_monthly: bool = False
    ):
        """
        엑셀 파일 저장

        Args:
            output_path: 출력 파일 경로
            config: 백테스트 설정
            trades: 거래 내역
            signals: 신호 내역
            summary: 통계 요약
            optimization_results: 최적화 결과 (선택)
            include_monthly: 월별 통계 포함 여부 (Phase 2)
        """
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            # Sheet 1: 요약
            self._write_summary_sheet(writer, config, summary)

            # Sheet 2: 거래내역
            self._write_trades_sheet(writer, trades)

            # Sheet 3: 월별 수익률 (Phase 2)
            if include_monthly:
                self._write_monthly_sheet(writer, trades)

            # Sheet 4: 최적화결과 (있는 경우)
            if optimization_results:
                self._write_optimization_sheet(writer, optimization_results)

        if self._logger:
            self._logger.info(f"엑셀 저장 완료: {output_path}")

    def _write_summary_sheet(
        self,
        writer: pd.ExcelWriter,
        config: EMASplitBuyConfig,
        summary: Dict
    ):
        """요약 시트 작성"""
        data = [
            ["EMA_SPLIT_BUY 백테스트 결과", ""],
            ["", ""],
            ["설정", "값"],
            ["5일선 근접%", f"{config.ema5_proximity_pct}%"],
            ["8일선 근접%", f"{config.ema8_proximity_pct}%"],
            ["손절 방식", config.stop_loss_type.value],
            ["최대 보유일", f"{config.max_holding_days}일"],
            ["투자금액", f"{config.investment_per_trade:,}원"],
            ["", ""],
            ["거래 통계", "값"],
            ["총 거래수", summary.get("trade_count", 0)],
            ["승리", summary.get("win_count", 0)],
            ["패배", summary.get("loss_count", 0)],
            ["승률", f"{summary.get('win_rate', 0):.2f}%"],
            ["", ""],
            ["손익", "값"],
            ["순손익", f"{summary.get('total_net_pnl', 0):,}원"],
            ["평균 수익률", f"{summary.get('avg_return', 0):.2f}%"],
            ["최대 수익률", f"{summary.get('max_return', 0):.2f}%"],
            ["최저 수익률", f"{summary.get('min_return', 0):.2f}%"],
            ["Profit Factor", f"{summary.get('profit_factor', 0):.2f}"],
            ["", ""],
            ["청산 유형", "건수"],
            ["고정 5% 손절", summary.get("hard_stop_count", 0)],
            ["ATR 트레일링", summary.get("atr_ts_count", 0)],
            ["3일 보유 청산", summary.get("max_holding_count", 0)],
            ["", ""],
            ["평균 보유일", f"{summary.get('avg_holding_days', 0):.1f}일"],
        ]

        df = pd.DataFrame(data, columns=["항목", "값"])
        df.to_excel(writer, sheet_name="요약", index=False)

    def _write_trades_sheet(
        self,
        writer: pd.ExcelWriter,
        trades: List[SplitBuyTrade]
    ):
        """거래내역 시트 작성"""
        data = []
        for t in trades:
            data.append({
                "종목코드": t.stock_code,
                "종목명": t.stock_name,
                "1차신호일": t.first_signal_date.strftime("%Y-%m-%d") if t.first_signal_date else "",
                "1차진입일": t.first_entry_date.strftime("%Y-%m-%d") if t.first_entry_date else "",
                "1차진입가": t.first_entry_price,
                "1차수량": t.first_qty,
                "2차신호일": t.second_signal_date.strftime("%Y-%m-%d") if t.second_signal_date else "",
                "2차진입일": t.second_entry_date.strftime("%Y-%m-%d") if t.second_entry_date else "",
                "2차진입가": t.second_entry_price if t.second_entry_price else "",
                "2차수량": t.second_qty if t.second_qty else "",
                "총수량": t.total_qty,
                "평균진입가": round(t.avg_entry_price, 0),
                "청산일": t.exit_date.strftime("%Y-%m-%d") if t.exit_date else "",
                "청산가": t.exit_price if t.exit_price else "",
                "청산사유": t.exit_reason.value if t.exit_reason else "",
                "보유일": t.holding_days,
                "순손익": t.net_pnl,
                "수익률%": round(t.return_rate, 2),
            })

        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name="거래내역", index=False)

    def _write_monthly_sheet(
        self,
        writer: pd.ExcelWriter,
        trades: List[SplitBuyTrade]
    ):
        """월별 수익률 시트 작성 (Phase 2)"""
        # 청산월 기준으로 그룹화
        monthly_data = defaultdict(list)

        for t in trades:
            if t.exit_date:
                year_month = t.exit_date.strftime("%Y-%m")
                monthly_data[year_month].append(t)

        # 월별 통계 계산
        data = []
        cumulative_pnl = 0

        for year_month in sorted(monthly_data.keys()):
            month_trades = monthly_data[year_month]
            wins = [t for t in month_trades if t.net_pnl > 0]
            losses = [t for t in month_trades if t.net_pnl <= 0]

            month_pnl = sum(t.net_pnl for t in month_trades)
            cumulative_pnl += month_pnl

            win_rate = (len(wins) / len(month_trades) * 100) if month_trades else 0
            avg_return = sum(t.return_rate for t in month_trades) / len(month_trades) if month_trades else 0

            # Profit Factor
            total_profit = sum(t.net_pnl for t in wins)
            total_loss = abs(sum(t.net_pnl for t in losses))
            pf = total_profit / total_loss if total_loss > 0 else (float('inf') if total_profit > 0 else 0)

            data.append({
                "년월": year_month,
                "거래수": len(month_trades),
                "승": len(wins),
                "패": len(losses),
                "승률%": round(win_rate, 2),
                "월손익": month_pnl,
                "평균수익률%": round(avg_return, 2),
                "PF": round(pf, 2) if pf != float('inf') else 999.99,
                "누적손익": cumulative_pnl
            })

        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name="월별수익률", index=False)

    def _write_optimization_sheet(
        self,
        writer: pd.ExcelWriter,
        results: List[OptimizationResult]
    ):
        """최적화결과 시트 작성"""
        data = []
        for r in results:
            pf_value = r.profit_factor if r.profit_factor != float('inf') else 999.99
            data.append({
                "EMA5_근접%": r.ema5_proximity_pct,
                "EMA8_근접%": r.ema8_proximity_pct,
                "손절방식": r.stop_loss_type.value,
                "거래수": r.trade_count,
                "승률%": round(r.win_rate, 2),
                "평균수익률%": round(r.avg_return, 2),
                "순손익": r.total_net_pnl,
                "Profit_Factor": round(pf_value, 2),
                "고정손절": r.hard_stop_count,
                "ATR_TS": r.atr_ts_count,
                "보유일초과": r.max_holding_count
            })

        df = pd.DataFrame(data)

        # Profit Factor 기준 정렬
        df = df.sort_values("Profit_Factor", ascending=False)

        df.to_excel(writer, sheet_name="최적화결과", index=False)


def print_console_summary(
    config: EMASplitBuyConfig,
    summary: Dict,
    comparison: Dict[StopLossType, Dict] = None
):
    """
    콘솔 요약 출력

    Args:
        config: 백테스트 설정
        summary: 통계 요약
        comparison: 손절 방식 비교 (선택)
    """
    print()
    print("=" * 70)
    print("  EMA_SPLIT_BUY 백테스트 결과")
    print("=" * 70)
    print(f"  5일선 근접: {config.ema5_proximity_pct}% | 8일선 근접: {config.ema8_proximity_pct}%")
    print(f"  손절 방식: {config.stop_loss_type.value}")
    print("-" * 70)
    print(f"  거래 수: {summary.get('trade_count', 0)}건")
    print(f"  승: {summary.get('win_count', 0)}건 / 패: {summary.get('loss_count', 0)}건")
    print(f"  승률: {summary.get('win_rate', 0):.2f}%")
    print("-" * 70)
    print(f"  순손익: {summary.get('total_net_pnl', 0):,}원")
    print(f"  평균 수익률: {summary.get('avg_return', 0):.2f}%")
    print(f"  최대 수익률: {summary.get('max_return', 0):.2f}%")
    print(f"  최저 수익률: {summary.get('min_return', 0):.2f}%")
    print(f"  Profit Factor: {summary.get('profit_factor', 0):.2f}")
    print("-" * 70)
    print("  [청산 유형별 분포]")
    print(f"    고정 5% 손절: {summary.get('hard_stop_count', 0)}건")
    print(f"    ATR 트레일링: {summary.get('atr_ts_count', 0)}건")
    print(f"    3일 보유 청산: {summary.get('max_holding_count', 0)}건")
    print(f"  평균 보유일: {summary.get('avg_holding_days', 0):.1f}일")

    if comparison:
        print("-" * 70)
        print("  [손절 방식 비교]")
        for stop_type, stats in comparison.items():
            print(f"    {stop_type.value}:")
            print(f"      거래수: {stats['total_trades']}건 | 승률: {stats['avg_win_rate']:.2f}%")
            print(f"      평균수익률: {stats['avg_return']:.2f}% | PF: {stats['avg_profit_factor']:.2f}")

    print("=" * 70)
    print()


def print_optimization_top_results(
    results: List[OptimizationResult],
    top_n: int = 5
):
    """
    최적화 상위 결과 출력

    Args:
        results: 최적화 결과 리스트
        top_n: 출력할 개수
    """
    # Profit Factor 기준 정렬
    valid_results = [r for r in results if r.trade_count >= 5]
    sorted_results = sorted(
        valid_results,
        key=lambda r: r.profit_factor if r.profit_factor != float('inf') else 0,
        reverse=True
    )[:top_n]

    print()
    print("-" * 70)
    print(f"  [최적화 상위 {top_n}개 결과]")
    print("-" * 70)
    print(f"  {'순위':^4} | {'EMA5%':^6} | {'EMA8%':^6} | {'손절':^10} | {'거래':^5} | {'승률':^7} | {'PF':^6}")
    print("-" * 70)

    for i, r in enumerate(sorted_results, 1):
        pf_str = f"{r.profit_factor:.2f}" if r.profit_factor != float('inf') else "∞"
        print(
            f"  {i:^4} | {r.ema5_proximity_pct:^6.1f} | {r.ema8_proximity_pct:^6.1f} | "
            f"{r.stop_loss_type.value:^10} | {r.trade_count:^5} | {r.win_rate:^6.1f}% | {pf_str:^6}"
        )

    print("-" * 70)
    print()


def print_monthly_summary(trades: List[SplitBuyTrade]):
    """
    월별 수익률 콘솔 출력

    Args:
        trades: 거래 리스트
    """
    from collections import defaultdict

    # 청산월 기준으로 그룹화
    monthly_data = defaultdict(list)
    for t in trades:
        if t.exit_date:
            year_month = t.exit_date.strftime("%Y-%m")
            monthly_data[year_month].append(t)

    print()
    print("-" * 80)
    print("  [월별 수익률]")
    print("-" * 80)
    print(f"  {'년월':^7} | {'거래':^5} | {'승':^3} | {'패':^3} | {'승률%':^7} | {'월손익':>12} | {'평균%':>7} | {'누적손익':>14}")
    print("-" * 80)

    cumulative_pnl = 0
    for year_month in sorted(monthly_data.keys()):
        month_trades = monthly_data[year_month]
        wins = [t for t in month_trades if t.net_pnl > 0]
        losses = [t for t in month_trades if t.net_pnl <= 0]

        month_pnl = sum(t.net_pnl for t in month_trades)
        cumulative_pnl += month_pnl

        win_rate = (len(wins) / len(month_trades) * 100) if month_trades else 0
        avg_return = sum(t.return_rate for t in month_trades) / len(month_trades) if month_trades else 0

        print(
            f"  {year_month:^7} | {len(month_trades):^5} | {len(wins):^3} | {len(losses):^3} | "
            f"{win_rate:>6.1f}% | {month_pnl:>11,}원 | {avg_return:>6.2f}% | {cumulative_pnl:>13,}원"
        )

    print("-" * 80)
    print()
