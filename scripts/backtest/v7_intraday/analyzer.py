# -*- coding: utf-8 -*-
"""
V7 Purple 3분봉 백테스트 - 결과 분석기

기본 통계, V7 신호 분석, 청산 분석, MFE/MAE 분석
"""

from datetime import datetime, time
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np

from .config import BacktestConfig, Trade, BacktestResult, V7Signal


class BacktestAnalyzer:
    """백테스트 결과 분석기"""

    def __init__(self, config: BacktestConfig, logger):
        self.config = config
        self.logger = logger

    # ============================================================
    # 기본 통계
    # ============================================================

    def calculate_basic_stats(self, trades: List[Trade]) -> Dict[str, Any]:
        """기본 통계 계산"""
        if not trades:
            return {"error": "No trades"}

        total = len(trades)
        wins = [t for t in trades if t.net_return_pct > 0]
        losses = [t for t in trades if t.net_return_pct <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total * 100 if total > 0 else 0

        # 수익률
        returns = [t.net_return_pct for t in trades]
        total_return = sum(returns)
        avg_return = np.mean(returns)
        avg_win = np.mean([t.net_return_pct for t in wins]) if wins else 0
        avg_loss = np.mean([t.net_return_pct for t in losses]) if losses else 0

        # Profit Factor
        gross_profit = sum(t.net_pnl for t in wins) if wins else 0
        gross_loss = abs(sum(t.net_pnl for t in losses)) if losses else 1
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # Expectancy
        expectancy = (win_rate / 100 * avg_win) + ((1 - win_rate / 100) * avg_loss)

        # Max Drawdown
        max_dd = self._calculate_max_drawdown(trades)

        # 연속 승/패
        max_wins, max_losses = self._calculate_consecutive(trades)

        return {
            "total_trades": total,
            "winning_trades": win_count,
            "losing_trades": loss_count,
            "win_rate": round(win_rate, 2),
            "total_return_pct": round(total_return, 2),
            "avg_return_pct": round(avg_return, 2),
            "avg_win_pct": round(avg_win, 2),
            "avg_loss_pct": round(avg_loss, 2),
            "profit_factor": round(profit_factor, 2),
            "expectancy": round(expectancy, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "max_consecutive_wins": max_wins,
            "max_consecutive_losses": max_losses,
            "total_gross_pnl": sum(t.gross_pnl for t in trades),
            "total_net_pnl": sum(t.net_pnl for t in trades),
            "total_cost": sum(t.total_cost for t in trades)
        }

    def _calculate_max_drawdown(self, trades: List[Trade]) -> float:
        """최대 낙폭 계산"""
        if not trades:
            return 0.0

        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0

        for trade in trades:
            cumulative += trade.net_return_pct
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd

        return max_dd

    def _calculate_consecutive(self, trades: List[Trade]) -> tuple:
        """연속 승/패 계산"""
        if not trades:
            return 0, 0

        max_wins = 0
        max_losses = 0
        current_wins = 0
        current_losses = 0

        for trade in trades:
            if trade.net_return_pct > 0:
                current_wins += 1
                current_losses = 0
                if current_wins > max_wins:
                    max_wins = current_wins
            else:
                current_losses += 1
                current_wins = 0
                if current_losses > max_losses:
                    max_losses = current_losses

        return max_wins, max_losses

    # ============================================================
    # 청산 유형별 분석
    # ============================================================

    def analyze_exit_types(self, trades: List[Trade]) -> Dict[str, Any]:
        """청산 유형별 분석"""
        if not trades:
            return {}

        exit_types = {}
        for trade in trades:
            exit_base = trade.exit_type.split("_")[0] if "_" in trade.exit_type else trade.exit_type

            # ATR_TS는 통합
            if exit_base == "ATR":
                exit_base = "ATR_TS"

            if exit_base not in exit_types:
                exit_types[exit_base] = {
                    "count": 0,
                    "returns": [],
                    "wins": 0
                }

            exit_types[exit_base]["count"] += 1
            exit_types[exit_base]["returns"].append(trade.net_return_pct)
            if trade.net_return_pct > 0:
                exit_types[exit_base]["wins"] += 1

        result = {}
        for exit_type, data in exit_types.items():
            result[exit_type] = {
                "count": data["count"],
                "pct": round(data["count"] / len(trades) * 100, 2),
                "avg_return": round(np.mean(data["returns"]), 2),
                "win_rate": round(data["wins"] / data["count"] * 100, 2) if data["count"] > 0 else 0
            }

        return result

    # ============================================================
    # 시간대별 분석
    # ============================================================

    def analyze_by_hour(self, trades: List[Trade]) -> Dict[str, Any]:
        """시간대별 성과 분석"""
        if not trades:
            return {}

        hourly = {}
        for trade in trades:
            entry_dt = trade.entry_dt
            if isinstance(entry_dt, str):
                entry_dt = pd.to_datetime(entry_dt)

            hour = entry_dt.hour

            if hour not in hourly:
                hourly[hour] = {
                    "count": 0,
                    "returns": [],
                    "wins": 0
                }

            hourly[hour]["count"] += 1
            hourly[hour]["returns"].append(trade.net_return_pct)
            if trade.net_return_pct > 0:
                hourly[hour]["wins"] += 1

        result = {}
        for hour, data in sorted(hourly.items()):
            result[f"{hour:02d}:00"] = {
                "count": data["count"],
                "avg_return": round(np.mean(data["returns"]), 2),
                "total_return": round(sum(data["returns"]), 2),
                "win_rate": round(data["wins"] / data["count"] * 100, 2) if data["count"] > 0 else 0
            }

        # 최고/최저 시간대
        best_hour = max(hourly.items(), key=lambda x: sum(x[1]["returns"])) if hourly else (0, {})
        worst_hour = min(hourly.items(), key=lambda x: sum(x[1]["returns"])) if hourly else (0, {})

        return {
            "hourly": result,
            "best_hour": best_hour[0],
            "worst_hour": worst_hour[0]
        }

    # ============================================================
    # V7 신호 분석
    # ============================================================

    def analyze_signals(self, trades: List[Trade]) -> Dict[str, Any]:
        """V7 신호 특성 분석"""
        if not trades:
            return {}

        # Score 분포
        scores = [t.signal_score for t in trades]
        rise_pcts = [t.signal_rise_pct for t in trades]
        conv_pcts = [t.signal_convergence_pct for t in trades]

        # Score vs 수익률 상관관계
        returns = [t.net_return_pct for t in trades]
        score_corr = np.corrcoef(scores, returns)[0, 1] if len(scores) > 1 else 0

        # Score 구간별 성과
        score_buckets = self._analyze_by_bucket(
            trades,
            lambda t: t.signal_score,
            [0, 0.3, 0.6, 1.0, float('inf')],
            ["<0.3", "0.3-0.6", "0.6-1.0", ">1.0"]
        )

        # Rise 구간별 성과
        rise_buckets = self._analyze_by_bucket(
            trades,
            lambda t: t.signal_rise_pct,
            [4, 5, 6, 8, float('inf')],
            ["4-5%", "5-6%", "6-8%", ">8%"]
        )

        # Convergence 구간별 성과
        conv_buckets = self._analyze_by_bucket(
            trades,
            lambda t: t.signal_convergence_pct,
            [0, 3, 5, 7, float('inf')],
            ["<3%", "3-5%", "5-7%", ">7%"]
        )

        return {
            "score_stats": {
                "mean": round(np.mean(scores), 3),
                "median": round(np.median(scores), 3),
                "std": round(np.std(scores), 3),
                "min": round(min(scores), 3),
                "max": round(max(scores), 3)
            },
            "score_return_correlation": round(score_corr, 3),
            "by_score": score_buckets,
            "by_rise": rise_buckets,
            "by_convergence": conv_buckets,
            "rise_stats": {
                "mean": round(np.mean(rise_pcts), 2),
                "std": round(np.std(rise_pcts), 2)
            },
            "convergence_stats": {
                "mean": round(np.mean(conv_pcts), 2),
                "std": round(np.std(conv_pcts), 2)
            }
        }

    def _analyze_by_bucket(
        self,
        trades: List[Trade],
        key_fn,
        thresholds: List[float],
        labels: List[str]
    ) -> Dict[str, Dict]:
        """구간별 분석"""
        buckets = {label: {"count": 0, "returns": [], "wins": 0} for label in labels}

        for trade in trades:
            value = key_fn(trade)
            for i, threshold in enumerate(thresholds[:-1]):
                if thresholds[i] <= value < thresholds[i + 1]:
                    label = labels[i]
                    buckets[label]["count"] += 1
                    buckets[label]["returns"].append(trade.net_return_pct)
                    if trade.net_return_pct > 0:
                        buckets[label]["wins"] += 1
                    break

        result = {}
        for label, data in buckets.items():
            if data["count"] > 0:
                result[label] = {
                    "count": data["count"],
                    "avg_return": round(np.mean(data["returns"]), 2),
                    "win_rate": round(data["wins"] / data["count"] * 100, 2)
                }

        return result

    # ============================================================
    # MFE/MAE 분석
    # ============================================================

    def analyze_mfe_mae(self, trades: List[Trade]) -> Dict[str, Any]:
        """MFE/MAE 분석"""
        if not trades:
            return {}

        mfes = [t.mfe_pct for t in trades]
        maes = [t.mae_pct for t in trades]

        # 승리 거래 vs 패배 거래
        wins = [t for t in trades if t.net_return_pct > 0]
        losses = [t for t in trades if t.net_return_pct <= 0]

        win_mfes = [t.mfe_pct for t in wins] if wins else [0]
        win_maes = [t.mae_pct for t in wins] if wins else [0]
        loss_mfes = [t.mfe_pct for t in losses] if losses else [0]
        loss_maes = [t.mae_pct for t in losses] if losses else [0]

        return {
            "overall": {
                "avg_mfe": round(np.mean(mfes), 2),
                "avg_mae": round(np.mean(maes), 2),
                "max_mfe": round(max(mfes), 2),
                "max_mae": round(min(maes), 2)  # 가장 낮은 (최악)
            },
            "winners": {
                "avg_mfe": round(np.mean(win_mfes), 2),
                "avg_mae": round(np.mean(win_maes), 2)
            },
            "losers": {
                "avg_mfe": round(np.mean(loss_mfes), 2),
                "avg_mae": round(np.mean(loss_maes), 2)
            },
            "efficiency": {
                "mfe_capture": round(np.mean([t.net_return_pct / t.mfe_pct * 100 if t.mfe_pct > 0 else 0 for t in wins]), 2) if wins else 0,
                "comment": "MFE 대비 실현 수익 비율 (%)"
            }
        }

    # ============================================================
    # R-Multiple 분석
    # ============================================================

    def analyze_r_multiples(self, trades: List[Trade]) -> Dict[str, Any]:
        """R-Multiple 분석"""
        if not trades:
            return {}

        r_multiples = [t.r_multiple for t in trades]

        # R 구간별 분포
        buckets = {
            "R<-1": 0,
            "-1<=R<0": 0,
            "0<=R<1": 0,
            "1<=R<2": 0,
            "2<=R<3": 0,
            "R>=3": 0
        }

        for r in r_multiples:
            if r < -1:
                buckets["R<-1"] += 1
            elif r < 0:
                buckets["-1<=R<0"] += 1
            elif r < 1:
                buckets["0<=R<1"] += 1
            elif r < 2:
                buckets["1<=R<2"] += 1
            elif r < 3:
                buckets["2<=R<3"] += 1
            else:
                buckets["R>=3"] += 1

        return {
            "stats": {
                "mean": round(np.mean(r_multiples), 2),
                "median": round(np.median(r_multiples), 2),
                "std": round(np.std(r_multiples), 2),
                "min": round(min(r_multiples), 2),
                "max": round(max(r_multiples), 2)
            },
            "distribution": buckets,
            "positive_r_rate": round(len([r for r in r_multiples if r > 0]) / len(r_multiples) * 100, 2)
        }

    # ============================================================
    # 종목별 분석
    # ============================================================

    def analyze_by_stock(self, trades: List[Trade]) -> pd.DataFrame:
        """종목별 성과 분석"""
        if not trades:
            return pd.DataFrame()

        stock_data = {}
        for trade in trades:
            code = trade.stock_code
            if code not in stock_data:
                stock_data[code] = {
                    "stock_name": trade.stock_name,
                    "trades": 0,
                    "wins": 0,
                    "returns": [],
                    "pnl": 0
                }

            stock_data[code]["trades"] += 1
            stock_data[code]["returns"].append(trade.net_return_pct)
            stock_data[code]["pnl"] += trade.net_pnl
            if trade.net_return_pct > 0:
                stock_data[code]["wins"] += 1

        records = []
        for code, data in stock_data.items():
            records.append({
                "stock_code": code,
                "stock_name": data["stock_name"],
                "trades": data["trades"],
                "win_rate": round(data["wins"] / data["trades"] * 100, 2),
                "avg_return": round(np.mean(data["returns"]), 2),
                "total_return": round(sum(data["returns"]), 2),
                "total_pnl": data["pnl"]
            })

        df = pd.DataFrame(records)
        df.sort_values("total_return", ascending=False, inplace=True)
        return df

    # ============================================================
    # 전체 분석 보고서
    # ============================================================

    def generate_full_report(self, trades: List[Trade]) -> Dict[str, Any]:
        """전체 분석 보고서 생성"""
        return {
            "basic_stats": self.calculate_basic_stats(trades),
            "exit_analysis": self.analyze_exit_types(trades),
            "hourly_analysis": self.analyze_by_hour(trades),
            "signal_analysis": self.analyze_signals(trades),
            "mfe_mae_analysis": self.analyze_mfe_mae(trades),
            "r_multiple_analysis": self.analyze_r_multiples(trades)
        }

    # ============================================================
    # 결과 저장
    # ============================================================

    def save_trades(self, trades: List[Trade]):
        """거래 결과 CSV 저장"""
        if not trades:
            return

        records = []
        for t in trades:
            records.append({
                "stock_code": t.stock_code,
                "stock_name": t.stock_name,
                "event_date": t.event_date,
                "entry_dt": t.entry_dt,
                "entry_price": t.entry_price,
                "exit_dt": t.exit_dt,
                "exit_price": t.exit_price,
                "exit_type": t.exit_type,
                "gross_return_pct": t.gross_return_pct,
                "net_return_pct": t.net_return_pct,
                "r_multiple": t.r_multiple,
                "mfe_pct": t.mfe_pct,
                "mae_pct": t.mae_pct,
                "holding_bars": t.holding_bars,
                "holding_days": t.holding_days,
                "investment": t.investment,
                "gross_pnl": t.gross_pnl,
                "total_cost": t.total_cost,
                "net_pnl": t.net_pnl,
                "signal_score": t.signal_score,
                "signal_rise_pct": t.signal_rise_pct,
                "signal_convergence_pct": t.signal_convergence_pct,
                "signal_time": t.signal_time
            })

        df = pd.DataFrame(records)
        df.to_csv(self.config.trades_path, index=False, encoding="utf-8-sig")
        self.logger.info(f"거래 결과 저장: {self.config.trades_path}")

    def save_summary(self, report: Dict[str, Any]):
        """요약 보고서 저장"""
        import json

        summary_path = self.config.summary_path
        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False, default=str)

        self.logger.info(f"요약 보고서 저장: {summary_path}")

    def save_stock_analysis(self, trades: List[Trade]):
        """종목별 분석 저장"""
        df = self.analyze_by_stock(trades)
        if len(df) > 0:
            path = self.config.output_dir / "stock_analysis.csv"
            df.to_csv(path, index=False, encoding="utf-8-sig")
            self.logger.info(f"종목별 분석 저장: {path}")
