# -*- coding: utf-8 -*-
"""
V7 Purple 백테스트 - 일별 수익곡선 그래프
"""

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from pathlib import Path
from datetime import datetime

# 한글 폰트 설정
plt.rcParams['font.family'] = 'Malgun Gothic'
plt.rcParams['axes.unicode_minus'] = False

def create_equity_curve():
    # 설정
    INITIAL_CAPITAL = 10_000_000  # 원금 1000만원
    POSITION_SIZE_PCT = 0.15      # 매수 비중 15%
    POSITION_SIZE = INITIAL_CAPITAL * POSITION_SIZE_PCT  # 150만원

    # trades.csv 로드
    trades_path = Path("C:/K_stock_trading/data/backtest/v7_purple_3min/trades.csv")
    df = pd.read_csv(trades_path, encoding='utf-8')

    # exit_dt를 datetime으로 변환
    df['exit_dt'] = pd.to_datetime(df['exit_dt'])
    df['exit_date'] = df['exit_dt'].dt.date

    # 거래별 실제 손익 계산 (15% 포지션 기준)
    # net_return_pct는 100만원 기준이므로 150만원 기준으로 재계산
    df['actual_pnl'] = POSITION_SIZE * df['net_return_pct'] / 100

    # 일별 손익 집계
    daily_pnl = df.groupby('exit_date').agg({
        'actual_pnl': 'sum',
        'stock_code': 'count'  # 거래 건수
    }).rename(columns={'stock_code': 'trade_count'})

    daily_pnl.index = pd.to_datetime(daily_pnl.index)
    daily_pnl = daily_pnl.sort_index()

    # 누적 수익 계산
    daily_pnl['cumulative_pnl'] = daily_pnl['actual_pnl'].cumsum()
    daily_pnl['equity'] = INITIAL_CAPITAL + daily_pnl['cumulative_pnl']
    daily_pnl['return_pct'] = (daily_pnl['equity'] / INITIAL_CAPITAL - 1) * 100

    # 통계 계산
    total_days = len(daily_pnl)
    winning_days = (daily_pnl['actual_pnl'] > 0).sum()
    losing_days = (daily_pnl['actual_pnl'] < 0).sum()

    final_equity = daily_pnl['equity'].iloc[-1]
    total_return = (final_equity / INITIAL_CAPITAL - 1) * 100
    max_equity = daily_pnl['equity'].max()
    min_equity = daily_pnl['equity'].min()

    # MDD 계산
    rolling_max = daily_pnl['equity'].cummax()
    drawdown = (daily_pnl['equity'] - rolling_max) / rolling_max * 100
    max_drawdown = drawdown.min()

    # 그래프 생성
    fig, axes = plt.subplots(3, 1, figsize=(14, 12), gridspec_kw={'height_ratios': [3, 1, 1]})

    # 1. 자산 곡선
    ax1 = axes[0]
    ax1.fill_between(daily_pnl.index, INITIAL_CAPITAL, daily_pnl['equity'],
                     where=daily_pnl['equity'] >= INITIAL_CAPITAL,
                     color='green', alpha=0.3, label='수익')
    ax1.fill_between(daily_pnl.index, INITIAL_CAPITAL, daily_pnl['equity'],
                     where=daily_pnl['equity'] < INITIAL_CAPITAL,
                     color='red', alpha=0.3, label='손실')
    ax1.plot(daily_pnl.index, daily_pnl['equity'], 'b-', linewidth=1.5, label='자산')
    ax1.axhline(y=INITIAL_CAPITAL, color='gray', linestyle='--', linewidth=1, label='원금')

    ax1.set_title(f'V7 Purple 백테스트 - 일별 수익곡선\n(원금: {INITIAL_CAPITAL:,}원, 포지션: 15%)',
                  fontsize=14, fontweight='bold')
    ax1.set_ylabel('자산 (원)', fontsize=11)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/1e6:.1f}M'))
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)

    # 통계 텍스트
    stats_text = (
        f'최종 자산: {final_equity:,.0f}원\n'
        f'총 수익률: {total_return:+.2f}%\n'
        f'MDD: {max_drawdown:.2f}%\n'
        f'거래일: {total_days}일\n'
        f'수익일/손실일: {winning_days}/{losing_days}'
    )
    ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, fontsize=10,
             verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    # 2. 일별 손익
    ax2 = axes[1]
    colors = ['green' if x > 0 else 'red' for x in daily_pnl['actual_pnl']]
    ax2.bar(daily_pnl.index, daily_pnl['actual_pnl'], color=colors, alpha=0.7, width=0.8)
    ax2.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    ax2.set_ylabel('일별 손익 (원)', fontsize=11)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x/1e4:.0f}만'))
    ax2.grid(True, alpha=0.3)

    # 3. Drawdown
    ax3 = axes[2]
    ax3.fill_between(daily_pnl.index, 0, drawdown, color='red', alpha=0.4)
    ax3.plot(daily_pnl.index, drawdown, 'r-', linewidth=1)
    ax3.axhline(y=0, color='gray', linestyle='-', linewidth=0.5)
    ax3.set_ylabel('Drawdown (%)', fontsize=11)
    ax3.set_xlabel('날짜', fontsize=11)
    ax3.grid(True, alpha=0.3)

    # X축 날짜 포맷
    for ax in axes:
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
        ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)

    plt.tight_layout()

    # 저장
    output_path = Path("C:/K_stock_trading/data/backtest/v7_purple_3min/equity_curve.png")
    plt.savefig(output_path, dpi=150, bbox_inches='tight')
    print(f"그래프 저장: {output_path}")

    # 일별 데이터 CSV 저장
    daily_csv_path = Path("C:/K_stock_trading/data/backtest/v7_purple_3min/daily_equity.csv")
    daily_pnl.to_csv(daily_csv_path, encoding='utf-8-sig')
    print(f"일별 데이터 저장: {daily_csv_path}")

    # 요약 출력
    print("\n" + "="*50)
    print("V7 Purple 백테스트 수익곡선 분석")
    print("="*50)
    print(f"원금: {INITIAL_CAPITAL:,}원")
    print(f"포지션 크기: {POSITION_SIZE:,}원 (15%)")
    print(f"총 거래: {len(df)}건")
    print(f"거래일: {total_days}일")
    print("-"*50)
    print(f"최종 자산: {final_equity:,.0f}원")
    print(f"총 수익률: {total_return:+.2f}%")
    print(f"최대 자산: {max_equity:,.0f}원")
    print(f"최소 자산: {min_equity:,.0f}원")
    print(f"MDD: {max_drawdown:.2f}%")
    print("-"*50)
    print(f"수익일: {winning_days}일 ({winning_days/total_days*100:.1f}%)")
    print(f"손실일: {losing_days}일 ({losing_days/total_days*100:.1f}%)")
    print(f"평균 일별 손익: {daily_pnl['actual_pnl'].mean():,.0f}원")
    print(f"최대 일 수익: {daily_pnl['actual_pnl'].max():,.0f}원")
    print(f"최대 일 손실: {daily_pnl['actual_pnl'].min():,.0f}원")
    print("="*50)

    return daily_pnl


if __name__ == "__main__":
    create_equity_curve()
