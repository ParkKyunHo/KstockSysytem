# -*- coding: utf-8 -*-
"""
December Pipeline - Exporter

CSV 및 Excel 내보내기 유틸리티
"""

from pathlib import Path
import pandas as pd


def export_to_excel(
    event_days_df: pd.DataFrame,
    event_summary_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    summary_df: pd.DataFrame,
    output_path: Path
):
    """전체 결과를 Excel 파일로 내보내기"""
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Stage A
        event_summary_df.to_excel(writer, sheet_name="이벤트요약", index=False)
        event_days_df.to_excel(writer, sheet_name="이벤트일자", index=False)

        # Stage B
        summary_df.to_excel(writer, sheet_name="거래요약", index=False)
        trades_df.to_excel(writer, sheet_name="거래내역", index=False)

    print(f"Excel 저장: {output_path}")


def print_final_summary(
    event_days_df: pd.DataFrame,
    event_summary_df: pd.DataFrame,
    trades_df: pd.DataFrame,
    summary_df: pd.DataFrame
):
    """최종 요약 출력"""
    print("\n" + "=" * 60)
    print("최종 요약")
    print("=" * 60)

    # Stage A
    print(f"\n[Stage A: 일봉 이벤트]")
    if not event_days_df.empty:
        print(f"  이벤트 종목 수: {event_summary_df['ticker'].nunique()}")
        print(f"  이벤트 건수: {len(event_days_df)}")
    else:
        print("  데이터 없음")

    # Stage B
    print(f"\n[Stage B: 3분봉 전략]")
    if not trades_df.empty:
        total = len(trades_df)
        wins = len(trades_df[trades_df["return"] > 0])
        winrate = (wins / total * 100) if total > 0 else 0

        avg_return = trades_df["return"].mean()
        total_return = trades_df["return"].sum()

        print(f"  거래 수: {total}")
        print(f"  승률: {winrate:.1f}%")
        print(f"  평균 수익률: {avg_return:.2f}%")
        print(f"  총 수익률: {total_return:.2f}%")

        # TOP 10 종목
        print(f"\n[TOP 10 종목 (총수익률 기준)]")
        if not summary_df.empty:
            top10 = summary_df.nlargest(10, "total_return")
            for _, row in top10.iterrows():
                print(f"  {row['ticker']} ({row['stock_name']}): "
                      f"{row['total_return']:+.2f}% "
                      f"({row['trades']}건, 승률 {row['winrate']:.1f}%)")
    else:
        print("  데이터 없음")

    print("=" * 60)
