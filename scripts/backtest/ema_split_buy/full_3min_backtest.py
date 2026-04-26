# -*- coding: utf-8 -*-
"""
전체 3분봉 청산 로직 백테스트
- 거래대금 1000억 이상 종목 전체 대상
- 상세 진입/청산 기록
- 전문가 수준 분석 리포트
"""

import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트로 작업 디렉토리 변경
project_root = Path(__file__).resolve().parent.parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from datetime import datetime, date, timedelta
import pandas as pd
import numpy as np

from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI


class FullBacktestRunner:
    """전체 백테스트 실행기"""

    def __init__(self):
        self.trades = []
        self.all_signals = []
        self.stats = {}

    async def find_high_volume_stocks(self, market_api, stocks, limit=None):
        """거래대금 1000억 이상 종목 찾기"""
        high_volume = []
        check_count = limit or len(stocks)

        for i, stock in enumerate(stocks[:check_count]):
            code = stock['code']
            name = stock['name']

            try:
                candles = await market_api.get_daily_chart(stock_code=code, count=10)
                if candles:
                    for c in candles:
                        tv = c.trading_value if hasattr(c, 'trading_value') else c.volume * c.close_price
                        if tv >= 100_000_000_000:  # 1000억
                            candle_date = c.date if isinstance(c.date, date) else (
                                c.date.date() if hasattr(c.date, 'date') else datetime.strptime(str(c.date), '%Y%m%d').date()
                            )
                            high_volume.append({
                                'code': code,
                                'name': name,
                                'date': candle_date,
                                'open': c.open_price,
                                'high': c.high_price,
                                'low': c.low_price,
                                'close': c.close_price,
                                'volume': c.volume,
                                'trading_value': tv
                            })
            except Exception as e:
                pass

            if (i + 1) % 20 == 0:
                print(f'[일봉 조회] {i+1}/{check_count} 종목 완료...')

            await asyncio.sleep(0.12)

        return high_volume

    async def get_3min_candles(self, market_api, stock_code):
        """3분봉 데이터 조회"""
        try:
            candles = await market_api.get_minute_chart(
                stock_code=stock_code,
                timeframe=3,
                count=1000,
                use_pagination=True
            )
            if not candles:
                return None

            data = []
            for c in candles:
                data.append({
                    'datetime': c.timestamp,
                    'open': c.open_price,
                    'high': c.high_price,
                    'low': c.low_price,
                    'close': c.close_price,
                    'volume': c.volume
                })

            df = pd.DataFrame(data)
            df = df.sort_values('datetime').reset_index(drop=True)
            return df
        except Exception as e:
            return None

    def calculate_indicators(self, df):
        """3분봉 지표 계산"""
        df = df.copy()

        # EMA
        df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
        df['ema5'] = df['close'].ewm(span=5, adjust=False).mean()
        df['ema8'] = df['close'].ewm(span=8, adjust=False).mean()
        df['ema9'] = df['close'].ewm(span=9, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()

        # ATR
        high = df['high']
        low = df['low']
        close = df['close']
        tr1 = high - low
        tr2 = abs(high - close.shift(1))
        tr3 = abs(low - close.shift(1))
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr10'] = tr.ewm(span=10, adjust=False).mean()

        # HLC3
        df['hlc3'] = (df['high'] + df['low'] + df['close']) / 3

        return df

    def simulate_trade(self, minute_df, entry_price, entry_idx, stock_info):
        """
        3분봉 청산 시뮬레이션 (상세 기록)
        """
        if minute_df is None or len(minute_df) < entry_idx + 20:
            return None

        # 지표 계산
        minute_df = self.calculate_indicators(minute_df)

        # 청산 시뮬레이션
        stop_price = entry_price * 0.96  # -4% 고정 손절
        trailing_stop = None
        highest_close = entry_price
        highest_price = entry_price
        structure_warning_count = 0
        atr_mult = 6.0

        entry_datetime = minute_df.iloc[entry_idx]['datetime']

        # 트레이드 상세 기록
        trade_log = []

        for i in range(entry_idx, len(minute_df)):
            row = minute_df.iloc[i]
            bar_datetime = row['datetime']
            bar_open = row['open']
            bar_high = row['high']
            bar_low = row['low']
            bar_close = row['close']
            hlc3 = row['hlc3']
            ema9 = row['ema9']
            atr = row['atr10']

            # 최고가 업데이트
            highest_close = max(highest_close, bar_close)
            highest_price = max(highest_price, bar_high)

            # 1. 고정 손절 체크 (-4%)
            if bar_low <= stop_price:
                exit_price = int(stop_price)
                pnl_pct = -4.0
                return {
                    'stock_code': stock_info['code'],
                    'stock_name': stock_info['name'],
                    'signal_date': stock_info['date'],
                    'signal_trading_value': stock_info['trading_value'],
                    'entry_datetime': entry_datetime,
                    'entry_price': entry_price,
                    'exit_datetime': bar_datetime,
                    'exit_price': exit_price,
                    'exit_reason': 'HARD_STOP_4%',
                    'holding_bars': i - entry_idx,
                    'highest_price': highest_price,
                    'highest_close': highest_close,
                    'max_profit_pct': round(((highest_close - entry_price) / entry_price) * 100, 2),
                    'trailing_stop_final': trailing_stop,
                    'atr_mult_final': atr_mult,
                    'pnl_pct': pnl_pct,
                    'pnl_amount': int((exit_price - entry_price) * (1000000 / entry_price))
                }

            # 2. ATR 트레일링 스탑 계산
            if pd.notna(atr) and atr > 0:
                new_ts = hlc3 - atr * atr_mult
                if trailing_stop is None:
                    trailing_stop = new_ts
                else:
                    trailing_stop = max(trailing_stop, new_ts)

            # 3. ATR 트레일링 스탑 체크
            if trailing_stop and bar_close <= trailing_stop:
                exit_price = int(bar_close)
                pnl_pct = round(((bar_close - entry_price) / entry_price) * 100, 2)
                return {
                    'stock_code': stock_info['code'],
                    'stock_name': stock_info['name'],
                    'signal_date': stock_info['date'],
                    'signal_trading_value': stock_info['trading_value'],
                    'entry_datetime': entry_datetime,
                    'entry_price': entry_price,
                    'exit_datetime': bar_datetime,
                    'exit_price': exit_price,
                    'exit_reason': f'ATR_TS_{atr_mult}',
                    'holding_bars': i - entry_idx,
                    'highest_price': highest_price,
                    'highest_close': highest_close,
                    'max_profit_pct': round(((highest_close - entry_price) / entry_price) * 100, 2),
                    'trailing_stop_final': int(trailing_stop),
                    'atr_mult_final': atr_mult,
                    'pnl_pct': pnl_pct,
                    'pnl_amount': int((exit_price - entry_price) * (1000000 / entry_price))
                }

            # 4. Structure Warning 체크
            if pd.notna(ema9) and hlc3 < ema9:
                structure_warning_count += 1
                if structure_warning_count >= 2:
                    atr_mult = 4.5
            else:
                structure_warning_count = 0

        # 데이터 끝까지 보유
        last_row = minute_df.iloc[-1]
        exit_price = int(last_row['close'])
        pnl_pct = round(((exit_price - entry_price) / entry_price) * 100, 2)

        return {
            'stock_code': stock_info['code'],
            'stock_name': stock_info['name'],
            'signal_date': stock_info['date'],
            'signal_trading_value': stock_info['trading_value'],
            'entry_datetime': entry_datetime,
            'entry_price': entry_price,
            'exit_datetime': last_row['datetime'],
            'exit_price': exit_price,
            'exit_reason': 'DATA_END',
            'holding_bars': len(minute_df) - entry_idx,
            'highest_price': highest_price,
            'highest_close': highest_close,
            'max_profit_pct': round(((highest_close - entry_price) / entry_price) * 100, 2),
            'trailing_stop_final': int(trailing_stop) if trailing_stop else None,
            'atr_mult_final': atr_mult,
            'pnl_pct': pnl_pct,
            'pnl_amount': int((exit_price - entry_price) * (1000000 / entry_price))
        }

    def analyze_results(self):
        """전문가 수준 결과 분석"""
        if not self.trades:
            return {}

        df = pd.DataFrame(self.trades)

        # 기본 통계
        total_trades = len(df)
        wins = df[df['pnl_pct'] > 0]
        losses = df[df['pnl_pct'] <= 0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0

        # 수익률 통계
        total_pnl_pct = df['pnl_pct'].sum()
        avg_pnl_pct = df['pnl_pct'].mean()
        median_pnl_pct = df['pnl_pct'].median()
        std_pnl_pct = df['pnl_pct'].std()

        avg_win = wins['pnl_pct'].mean() if len(wins) > 0 else 0
        avg_loss = losses['pnl_pct'].mean() if len(losses) > 0 else 0

        max_win = df['pnl_pct'].max()
        max_loss = df['pnl_pct'].min()

        # Profit Factor
        gross_profit = wins['pnl_pct'].sum() if len(wins) > 0 else 0
        gross_loss = abs(losses['pnl_pct'].sum()) if len(losses) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        # 청산 유형별 분석
        exit_reasons = df['exit_reason'].value_counts().to_dict()

        # 청산 유형별 수익률
        exit_pnl = df.groupby('exit_reason')['pnl_pct'].agg(['mean', 'sum', 'count']).to_dict('index')

        # 보유 기간 분석
        avg_holding_bars = df['holding_bars'].mean()
        avg_holding_hours = avg_holding_bars * 3 / 60  # 3분봉 기준

        # Max Profit Given Back (최대 이익 반납률)
        df['profit_giveback'] = df['max_profit_pct'] - df['pnl_pct']
        avg_giveback = df['profit_giveback'].mean()

        # Risk-Reward Ratio
        risk_reward = abs(avg_win / avg_loss) if avg_loss != 0 else float('inf')

        # Expectancy (기대값)
        expectancy = (win_rate/100 * avg_win) + ((1 - win_rate/100) * avg_loss)

        return {
            'total_trades': total_trades,
            'win_count': win_count,
            'loss_count': loss_count,
            'win_rate': round(win_rate, 2),
            'total_pnl_pct': round(total_pnl_pct, 2),
            'avg_pnl_pct': round(avg_pnl_pct, 2),
            'median_pnl_pct': round(median_pnl_pct, 2),
            'std_pnl_pct': round(std_pnl_pct, 2),
            'avg_win_pct': round(avg_win, 2),
            'avg_loss_pct': round(avg_loss, 2),
            'max_win_pct': round(max_win, 2),
            'max_loss_pct': round(max_loss, 2),
            'profit_factor': round(profit_factor, 2),
            'risk_reward_ratio': round(risk_reward, 2),
            'expectancy': round(expectancy, 2),
            'avg_holding_bars': round(avg_holding_bars, 1),
            'avg_holding_hours': round(avg_holding_hours, 2),
            'avg_profit_giveback': round(avg_giveback, 2),
            'exit_reasons': exit_reasons,
            'exit_pnl': exit_pnl
        }

    def save_to_excel(self, output_path):
        """엑셀 저장"""
        if not self.trades:
            print("저장할 거래 데이터가 없습니다.")
            return

        df = pd.DataFrame(self.trades)

        # 컬럼 순서 정렬
        columns_order = [
            'stock_code', 'stock_name', 'signal_date', 'signal_trading_value',
            'entry_datetime', 'entry_price', 'exit_datetime', 'exit_price',
            'exit_reason', 'holding_bars', 'pnl_pct', 'pnl_amount',
            'highest_price', 'highest_close', 'max_profit_pct',
            'trailing_stop_final', 'atr_mult_final'
        ]
        df = df[columns_order]

        # 컬럼명 한글화
        df.columns = [
            '종목코드', '종목명', '신호일', '신호일거래대금',
            '진입시각', '진입가', '청산시각', '청산가',
            '청산사유', '보유봉수', '수익률%', '손익금액',
            '최고가', '최고종가', '최대수익률%',
            '최종TS', '최종ATR배수'
        ]

        # 신호일거래대금 억 단위로 변환
        df['신호일거래대금'] = (df['신호일거래대금'] / 100_000_000).round(0).astype(int)

        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            df.to_excel(writer, sheet_name='거래내역', index=False)

            # 분석 결과 시트
            stats = self.analyze_results()
            stats_df = pd.DataFrame([
                {'항목': '총 거래 수', '값': stats['total_trades']},
                {'항목': '승리', '값': stats['win_count']},
                {'항목': '패배', '값': stats['loss_count']},
                {'항목': '승률 (%)', '값': stats['win_rate']},
                {'항목': '', '값': ''},
                {'항목': '총 수익률 (%)', '값': stats['total_pnl_pct']},
                {'항목': '평균 수익률 (%)', '값': stats['avg_pnl_pct']},
                {'항목': '중앙값 수익률 (%)', '값': stats['median_pnl_pct']},
                {'항목': '표준편차 (%)', '값': stats['std_pnl_pct']},
                {'항목': '', '값': ''},
                {'항목': '평균 이익 (%)', '값': stats['avg_win_pct']},
                {'항목': '평균 손실 (%)', '값': stats['avg_loss_pct']},
                {'항목': '최대 이익 (%)', '값': stats['max_win_pct']},
                {'항목': '최대 손실 (%)', '값': stats['max_loss_pct']},
                {'항목': '', '값': ''},
                {'항목': 'Profit Factor', '값': stats['profit_factor']},
                {'항목': 'Risk/Reward Ratio', '값': stats['risk_reward_ratio']},
                {'항목': 'Expectancy (%)', '값': stats['expectancy']},
                {'항목': '', '값': ''},
                {'항목': '평균 보유 봉 수', '값': stats['avg_holding_bars']},
                {'항목': '평균 보유 시간 (시간)', '값': stats['avg_holding_hours']},
                {'항목': '평균 이익 반납률 (%)', '값': stats['avg_profit_giveback']},
            ])
            stats_df.to_excel(writer, sheet_name='분석결과', index=False)

            # 청산유형별 분석 시트
            exit_analysis = []
            for reason, data in stats['exit_pnl'].items():
                exit_analysis.append({
                    '청산유형': reason,
                    '건수': int(data['count']),
                    '평균수익률%': round(data['mean'], 2),
                    '총수익률%': round(data['sum'], 2)
                })
            exit_df = pd.DataFrame(exit_analysis)
            exit_df.to_excel(writer, sheet_name='청산유형분석', index=False)

        print(f'\n결과 저장 완료: {output_path}')


async def run_full_backtest():
    """전체 백테스트 실행"""
    print('=' * 70)
    print('  3분봉 청산 로직 전체 백테스트')
    print('  기간: 최근 7~8 거래일 | 조건: 거래대금 1000억 이상')
    print('=' * 70)

    # past1000.csv 읽기
    csv_path = project_root / 'past1000.csv'
    df = pd.read_csv(csv_path, encoding='cp949', dtype=str)

    etf_keywords = ['KODEX', 'TIGER', 'RISE', 'SOL', 'HANARO', 'PLUS', 'KBSTAR', 'ACE', 'ARIRANG', 'KOSEF', 'ETF', 'ETN']

    stocks = []
    for _, row in df.iterrows():
        code = str(row.iloc[0]).replace("'", '').strip()
        name = str(row.iloc[1]).strip() if len(row) > 1 else ''
        if len(code) == 6 and not any(kw in name for kw in etf_keywords):
            stocks.append({'code': code, 'name': name})

    print(f'총 {len(stocks)}개 종목 (ETF 제외)')

    runner = FullBacktestRunner()
    client = KiwoomAPIClient()

    async with client:
        market_api = MarketAPI(client)

        # Step 1: 거래대금 1000억 이상 종목 찾기
        print('\n[Step 1] 거래대금 1000억 이상 종목 조회...')
        high_volume = await runner.find_high_volume_stocks(market_api, stocks, limit=None)

        print(f'\n거래대금 1000억 이상: {len(high_volume)}건 발견')

        # 일자별, 거래대금 순 정렬
        high_volume.sort(key=lambda x: (x['date'], -x['trading_value']), reverse=True)

        # 중복 제거 (종목당 가장 최근 1000억봉만)
        seen_codes = set()
        unique_signals = []
        for s in high_volume:
            if s['code'] not in seen_codes:
                seen_codes.add(s['code'])
                unique_signals.append(s)

        print(f'중복 제거 후: {len(unique_signals)}개 종목')

        print('\n=== 최근 거래대금 1000억 이상 TOP 20 ===')
        for i, s in enumerate(unique_signals[:20]):
            tv_억 = round(s['trading_value'] / 100_000_000, 0)
            print(f"{i+1:2}. {s['date']} | {s['code']} {s['name']}: {tv_억:,.0f}억")

        # Step 2: 각 종목별 3분봉 테스트
        print(f'\n[Step 2] {len(unique_signals)}개 종목 3분봉 청산 테스트 시작...')

        for i, stock in enumerate(unique_signals):
            code = stock['code']
            name = stock['name']

            # 3분봉 데이터 조회
            minute_df = await runner.get_3min_candles(market_api, code)

            if minute_df is None or len(minute_df) < 100:
                continue

            # 진입 인덱스 설정 (지표 안정화 후)
            entry_idx = 50
            entry_price = stock['close']

            # 청산 시뮬레이션
            result = runner.simulate_trade(minute_df, entry_price, entry_idx, stock)

            if result:
                runner.trades.append(result)
                status = 'WIN' if result['pnl_pct'] > 0 else 'LOSS'
                print(f"  [{i+1}/{len(unique_signals)}] [{status}] {code} {name}: {result['pnl_pct']:+.2f}% ({result['exit_reason']})")

            await asyncio.sleep(0.5)

        # Step 3: 결과 분석
        print('\n' + '=' * 70)
        print('  백테스트 결과 분석')
        print('=' * 70)

        stats = runner.analyze_results()

        if stats:
            print(f'''
┌─────────────────────────────────────────────────────────────────────┐
│  기본 통계                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  총 거래 수: {stats['total_trades']:>5}건                                              │
│  승/패: {stats['win_count']}/{stats['loss_count']} (승률: {stats['win_rate']:.1f}%)                                       │
├─────────────────────────────────────────────────────────────────────┤
│  수익률 분석                                                        │
├─────────────────────────────────────────────────────────────────────┤
│  총 수익률: {stats['total_pnl_pct']:>+8.2f}%                                           │
│  평균 수익률: {stats['avg_pnl_pct']:>+7.2f}% (중앙값: {stats['median_pnl_pct']:>+6.2f}%)                       │
│  표준편차: {stats['std_pnl_pct']:>7.2f}%                                              │
│  평균 이익: {stats['avg_win_pct']:>+7.2f}% | 평균 손실: {stats['avg_loss_pct']:>+7.2f}%                     │
│  최대 이익: {stats['max_win_pct']:>+7.2f}% | 최대 손실: {stats['max_loss_pct']:>+7.2f}%                     │
├─────────────────────────────────────────────────────────────────────┤
│  리스크 지표                                                        │
├─────────────────────────────────────────────────────────────────────┤
│  Profit Factor: {stats['profit_factor']:>6.2f}                                          │
│  Risk/Reward Ratio: {stats['risk_reward_ratio']:>5.2f}                                       │
│  Expectancy: {stats['expectancy']:>+6.2f}%                                            │
├─────────────────────────────────────────────────────────────────────┤
│  보유 분석                                                          │
├─────────────────────────────────────────────────────────────────────┤
│  평균 보유: {stats['avg_holding_bars']:>6.1f}봉 ({stats['avg_holding_hours']:>5.1f}시간)                               │
│  평균 이익 반납률: {stats['avg_profit_giveback']:>5.2f}%                                      │
└─────────────────────────────────────────────────────────────────────┘
''')

            print('\n[청산 유형별 분석]')
            print('-' * 50)
            for reason, data in stats['exit_pnl'].items():
                print(f"  {reason:20}: {int(data['count']):>3}건 | 평균: {data['mean']:>+6.2f}% | 합계: {data['sum']:>+7.2f}%")

        # Step 4: 엑셀 저장
        output_path = project_root / 'full_3min_backtest_result.xlsx'
        runner.save_to_excel(output_path)

        print('\n' + '=' * 70)
        print('  백테스트 완료')
        print('=' * 70)


if __name__ == '__main__':
    asyncio.run(run_full_backtest())
