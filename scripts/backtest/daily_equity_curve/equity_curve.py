# -*- coding: utf-8 -*-
"""
Daily Equity Curve - Equity Curve Calculator

월별 수익곡선 계산
"""

from collections import defaultdict
from datetime import date
from typing import List, Dict
import pandas as pd

from .config import Trade, MonthlyStats


class EquityCurve:
    """
    월별 수익곡선 계산

    - 청산일 기준 월별 집계
    - 누적 수익 계산
    - MDD (Maximum Drawdown) 계산
    """

    def __init__(self):
        pass

    def calculate_monthly_stats(self, trades: List[Trade]) -> List[MonthlyStats]:
        """
        월별 통계 계산

        Args:
            trades: 거래 기록 리스트

        Returns:
            월별 통계 리스트
        """
        monthly_data = defaultdict(lambda: {
            "trades": [],
            "total_pnl": 0,
            "win_count": 0,
            "loss_count": 0
        })

        # 월별 집계
        for trade in trades:
            if trade.exit_date is None:
                continue

            exit_month = trade.exit_date.strftime("%Y-%m")
            monthly_data[exit_month]["trades"].append(trade)
            monthly_data[exit_month]["total_pnl"] += trade.net_pnl

            if trade.net_pnl > 0:
                monthly_data[exit_month]["win_count"] += 1
            else:
                monthly_data[exit_month]["loss_count"] += 1

        # 누적 수익 계산
        cumulative = 0
        peak = 0
        monthly_stats = []

        for month in sorted(monthly_data.keys()):
            data = monthly_data[month]
            trade_count = len(data["trades"])
            cumulative += data["total_pnl"]

            # 승률
            win_rate = 0.0
            if trade_count > 0:
                win_rate = (data["win_count"] / trade_count) * 100

            # MDD 계산
            if cumulative > peak:
                peak = cumulative

            if peak > 0:
                mdd = ((peak - cumulative) / peak) * 100
            else:
                mdd = 0.0

            stats = MonthlyStats(
                month=month,
                trade_count=trade_count,
                win_count=data["win_count"],
                loss_count=data["loss_count"],
                total_pnl=data["total_pnl"],
                cumulative_pnl=cumulative,
                win_rate=round(win_rate, 1),
                mdd=round(mdd, 1)
            )
            monthly_stats.append(stats)

        return monthly_stats

    def calculate_summary(self, trades: List[Trade]) -> Dict:
        """
        전체 요약 통계 계산

        Args:
            trades: 거래 기록 리스트

        Returns:
            요약 통계 딕셔너리
        """
        if not trades:
            return {
                "total_trades": 0,
                "win_count": 0,
                "loss_count": 0,
                "win_rate": 0.0,
                "total_pnl": 0,
                "avg_pnl": 0,
                "avg_return_pct": 0.0,
                "max_win": 0,
                "max_loss": 0,
                "avg_holding_days": 0,
                "profit_factor": 0.0,
                "mdd": 0.0
            }

        total_trades = len(trades)
        win_trades = [t for t in trades if t.net_pnl > 0]
        loss_trades = [t for t in trades if t.net_pnl <= 0]

        win_count = len(win_trades)
        loss_count = len(loss_trades)

        total_pnl = sum(t.net_pnl for t in trades)
        avg_pnl = total_pnl / total_trades

        avg_return_pct = sum(t.return_pct for t in trades) / total_trades

        max_win = max((t.net_pnl for t in trades), default=0)
        max_loss = min((t.net_pnl for t in trades), default=0)

        avg_holding_days = sum(t.holding_days for t in trades) / total_trades

        # Profit Factor
        total_profit = sum(t.net_pnl for t in win_trades)
        total_loss = abs(sum(t.net_pnl for t in loss_trades))
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')

        # MDD 계산 (거래별 누적)
        cumulative = 0
        peak = 0
        max_dd = 0

        for trade in sorted(trades, key=lambda t: t.exit_date or t.entry_date):
            cumulative += trade.net_pnl
            if cumulative > peak:
                peak = cumulative
            if peak > 0:
                dd = (peak - cumulative) / peak
                max_dd = max(max_dd, dd)

        return {
            "total_trades": total_trades,
            "win_count": win_count,
            "loss_count": loss_count,
            "win_rate": round((win_count / total_trades) * 100, 1),
            "total_pnl": total_pnl,
            "avg_pnl": round(avg_pnl),
            "avg_return_pct": round(avg_return_pct, 2),
            "max_win": max_win,
            "max_loss": max_loss,
            "avg_holding_days": round(avg_holding_days, 1),
            "profit_factor": round(profit_factor, 2),
            "mdd": round(max_dd * 100, 1)
        }

    def calculate_by_stock(self, trades: List[Trade]) -> pd.DataFrame:
        """
        종목별 통계

        Args:
            trades: 거래 기록 리스트

        Returns:
            종목별 통계 DataFrame
        """
        stock_data = defaultdict(lambda: {
            "stock_name": "",
            "trades": 0,
            "wins": 0,
            "total_pnl": 0,
            "returns": []
        })

        for trade in trades:
            code = trade.stock_code
            stock_data[code]["stock_name"] = trade.stock_name
            stock_data[code]["trades"] += 1
            stock_data[code]["total_pnl"] += trade.net_pnl
            stock_data[code]["returns"].append(trade.return_pct)

            if trade.net_pnl > 0:
                stock_data[code]["wins"] += 1

        rows = []
        for code, data in stock_data.items():
            win_rate = (data["wins"] / data["trades"] * 100) if data["trades"] > 0 else 0
            avg_return = sum(data["returns"]) / len(data["returns"]) if data["returns"] else 0

            rows.append({
                "종목코드": code,
                "종목명": data["stock_name"],
                "거래수": data["trades"],
                "승": data["wins"],
                "패": data["trades"] - data["wins"],
                "승률": round(win_rate, 1),
                "총손익": data["total_pnl"],
                "평균수익률": round(avg_return, 2)
            })

        df = pd.DataFrame(rows)
        df.sort_values("총손익", ascending=False, inplace=True)
        return df
