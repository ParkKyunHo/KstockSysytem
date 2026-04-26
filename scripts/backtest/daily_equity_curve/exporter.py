# -*- coding: utf-8 -*-
"""
Daily Equity Curve - Excel Exporter

Excel 결과 출력
"""

from pathlib import Path
from typing import List, Dict
import pandas as pd

from .config import Trade, MonthlyStats, BacktestConfig


class ExcelExporter:
    """
    Excel 결과 출력

    - Sheet 1: 거래내역
    - Sheet 2: 월별수익
    - Sheet 3: 종목별통계
    - Sheet 4: 요약
    """

    def __init__(self, config: BacktestConfig):
        self.config = config

    def export(
        self,
        trades: List[Trade],
        monthly_stats: List[MonthlyStats],
        summary: Dict,
        stock_stats: pd.DataFrame,
        output_path: Path = None
    ) -> Path:
        """
        Excel 파일 출력

        Args:
            trades: 거래 기록 리스트
            monthly_stats: 월별 통계 리스트
            summary: 전체 요약
            stock_stats: 종목별 통계 DataFrame
            output_path: 출력 경로 (기본: config.result_excel_path)

        Returns:
            출력된 파일 경로
        """
        output_path = output_path or self.config.result_excel_path

        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
            # Sheet 1: 거래내역
            trades_df = self._trades_to_df(trades)
            trades_df.to_excel(writer, sheet_name="거래내역", index=False)

            # Sheet 2: 월별수익
            monthly_df = self._monthly_to_df(monthly_stats)
            monthly_df.to_excel(writer, sheet_name="월별수익", index=False)

            # Sheet 3: 종목별통계
            stock_stats.to_excel(writer, sheet_name="종목별통계", index=False)

            # Sheet 4: 요약
            summary_df = self._summary_to_df(summary)
            summary_df.to_excel(writer, sheet_name="요약", index=False)

        return output_path

    def _trades_to_df(self, trades: List[Trade]) -> pd.DataFrame:
        """거래 기록을 DataFrame으로 변환"""
        rows = []
        for t in trades:
            rows.append({
                "종목코드": t.stock_code,
                "종목명": t.stock_name,
                "진입일": t.entry_date,
                "진입가": t.entry_price,
                "진입수량": t.entry_quantity,
                "추가매수일": t.addon_date,
                "추가매수가": t.addon_price,
                "추가매수량": t.addon_quantity,
                "평균단가": t.avg_price,
                "총수량": t.total_quantity,
                "청산일": t.exit_date,
                "청산가": t.exit_price,
                "청산유형": t.exit_type.value if t.exit_type else "",
                "세전손익": t.gross_pnl,
                "비용": t.total_cost,
                "순손익": t.net_pnl,
                "수익률(%)": round(t.return_pct, 2),
                "보유일": t.holding_days,
                "R배수": round(t.r_multiple, 2),
                "ATR배수": t.current_multiplier
            })

        return pd.DataFrame(rows)

    def _monthly_to_df(self, monthly_stats: List[MonthlyStats]) -> pd.DataFrame:
        """월별 통계를 DataFrame으로 변환"""
        rows = []
        for m in monthly_stats:
            rows.append({
                "월": m.month,
                "거래수": m.trade_count,
                "승": m.win_count,
                "패": m.loss_count,
                "승률(%)": m.win_rate,
                "월손익": m.total_pnl,
                "평균손익": round(m.avg_pnl),
                "누적손익": m.cumulative_pnl,
                "MDD(%)": m.mdd
            })

        return pd.DataFrame(rows)

    def _summary_to_df(self, summary: Dict) -> pd.DataFrame:
        """요약을 DataFrame으로 변환"""
        rows = [
            {"항목": "총 거래수", "값": summary["total_trades"]},
            {"항목": "승리", "값": summary["win_count"]},
            {"항목": "패배", "값": summary["loss_count"]},
            {"항목": "승률(%)", "값": summary["win_rate"]},
            {"항목": "총 손익", "값": f"{summary['total_pnl']:,}원"},
            {"항목": "평균 손익", "값": f"{summary['avg_pnl']:,}원"},
            {"항목": "평균 수익률(%)", "값": summary["avg_return_pct"]},
            {"항목": "최대 이익", "값": f"{summary['max_win']:,}원"},
            {"항목": "최대 손실", "값": f"{summary['max_loss']:,}원"},
            {"항목": "평균 보유일", "값": summary["avg_holding_days"]},
            {"항목": "Profit Factor", "값": summary["profit_factor"]},
            {"항목": "MDD(%)", "값": summary["mdd"]},
        ]

        return pd.DataFrame(rows)

    def export_csv(
        self,
        trades: List[Trade],
        output_path: Path = None
    ) -> Path:
        """
        거래 내역 CSV 출력

        Args:
            trades: 거래 기록 리스트
            output_path: 출력 경로

        Returns:
            출력된 파일 경로
        """
        output_path = output_path or (self.config.output_dir / "trades.csv")
        trades_df = self._trades_to_df(trades)
        trades_df.to_csv(output_path, index=False, encoding="utf-8-sig")
        return output_path
