# -*- coding: utf-8 -*-
"""
3종목 선행 테스트 - 거래대금 1000억 이상 종목 3분봉 청산 로직 테스트
"""

import asyncio
import sys
import os
from pathlib import Path

# 프로젝트 루트로 작업 디렉토리 변경 (import 전에 실행)
project_root = Path(__file__).resolve().parent.parent.parent.parent
os.chdir(project_root)
sys.path.insert(0, str(project_root))

from datetime import datetime, date, timedelta
import pandas as pd

from src.api.client import KiwoomAPIClient
from src.api.endpoints.market import MarketAPI


async def find_high_volume_stocks(market_api, stocks, limit=50):
    """거래대금 1000억 이상 종목 찾기"""
    high_volume = []

    for i, stock in enumerate(stocks[:limit]):
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
                            'close': c.close_price,
                            'open': c.open_price,
                            'high': c.high_price,
                            'low': c.low_price,
                            'trading_value': tv
                        })
        except Exception as e:
            pass

        if (i + 1) % 10 == 0:
            print(f'[일봉 조회] {i+1}/{limit} 종목 완료...')

        await asyncio.sleep(0.15)

    # 거래대금 높은 순 정렬
    high_volume.sort(key=lambda x: x['trading_value'], reverse=True)
    return high_volume


async def get_3min_candles(market_api, stock_code):
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
        print(f'[에러] 3분봉 조회 실패: {e}')
        return None


def calculate_ema(df, column, period):
    """EMA 계산"""
    return df[column].ewm(span=period, adjust=False).mean()


def calculate_atr(df, period=10):
    """ATR 계산"""
    high = df['high']
    low = df['low']
    close = df['close']

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    return tr.ewm(span=period, adjust=False).mean()


def calculate_hlc3(df):
    """HLC3 계산"""
    return (df['high'] + df['low'] + df['close']) / 3


def simulate_3min_exit(minute_df, entry_price, entry_idx):
    """
    3분봉 청산 시뮬레이션
    - 고정 손절: -4%
    - ATR 트레일링: HLC3 - ATR10 × 6.0
    - Structure Warning 시 ATR 배수 4.5로 타이트닝
    """
    if minute_df is None or len(minute_df) < entry_idx + 10:
        return None

    # 지표 계산
    minute_df['ema9'] = calculate_ema(minute_df, 'close', 9)
    minute_df['atr10'] = calculate_atr(minute_df, 10)
    minute_df['hlc3'] = calculate_hlc3(minute_df)

    # 청산 시뮬레이션
    stop_price = entry_price * 0.96  # -4% 고정 손절
    trailing_stop = None
    highest_close = entry_price
    structure_warning_count = 0
    atr_mult = 6.0

    for i in range(entry_idx, len(minute_df)):
        row = minute_df.iloc[i]
        bar_low = row['low']
        bar_close = row['close']
        hlc3 = row['hlc3']
        ema9 = row['ema9']
        atr = row['atr10']

        # 1. 고정 손절 체크 (-4%)
        if bar_low <= stop_price:
            return {
                'exit_idx': i,
                'exit_price': int(stop_price),
                'exit_reason': 'HARD_STOP_4%',
                'exit_datetime': row['datetime'],
                'pnl_pct': -4.0
            }

        # 2. ATR 트레일링 스탑 계산
        if pd.notna(atr) and atr > 0:
            new_ts = hlc3 - atr * atr_mult
            if trailing_stop is None:
                trailing_stop = new_ts
            else:
                trailing_stop = max(trailing_stop, new_ts)  # 상향만 허용

        # 3. ATR 트레일링 스탑 체크
        if trailing_stop and bar_close <= trailing_stop:
            pnl_pct = ((bar_close - entry_price) / entry_price) * 100
            return {
                'exit_idx': i,
                'exit_price': int(bar_close),
                'exit_reason': f'ATR_TS_{atr_mult}',
                'exit_datetime': row['datetime'],
                'pnl_pct': round(pnl_pct, 2)
            }

        # 4. Structure Warning 체크
        if pd.notna(ema9) and hlc3 < ema9:
            structure_warning_count += 1
            if structure_warning_count >= 2:
                atr_mult = 4.5  # 타이트닝
        else:
            structure_warning_count = 0

        # 최고가 업데이트
        highest_close = max(highest_close, bar_close)

    # 최대 보유 (데이터 끝까지 보유)
    last_row = minute_df.iloc[-1]
    pnl_pct = ((last_row['close'] - entry_price) / entry_price) * 100
    return {
        'exit_idx': len(minute_df) - 1,
        'exit_price': int(last_row['close']),
        'exit_reason': 'DATA_END',
        'exit_datetime': last_row['datetime'],
        'pnl_pct': round(pnl_pct, 2)
    }


async def test_3_stocks():
    """3종목 테스트"""
    print('=' * 60)
    print('  3종목 선행 테스트 - 3분봉 청산 로직')
    print('=' * 60)

    # past1000.csv 읽기
    csv_path = Path(__file__).parent.parent.parent.parent / 'past1000.csv'
    df = pd.read_csv(csv_path, encoding='cp949', dtype=str)

    etf_keywords = ['KODEX', 'TIGER', 'RISE', 'SOL', 'HANARO', 'PLUS', 'KBSTAR', 'ACE', 'ARIRANG', 'KOSEF', 'ETF', 'ETN']

    stocks = []
    for _, row in df.iterrows():
        code = str(row.iloc[0]).replace("'", '').strip()
        name = str(row.iloc[1]).strip() if len(row) > 1 else ''
        if len(code) == 6 and not any(kw in name for kw in etf_keywords):
            stocks.append({'code': code, 'name': name})

    print(f'총 {len(stocks)}개 종목 (ETF 제외)')

    # API 클라이언트 (async with 사용)
    client = KiwoomAPIClient()

    async with client:
        market_api = MarketAPI(client)

        # Step 1: 거래대금 1000억 이상 종목 찾기
        print('\n[Step 1] 거래대금 1000억 이상 종목 조회...')
        high_volume = await find_high_volume_stocks(market_api, stocks, limit=80)

        print(f'\n거래대금 1000억 이상: {len(high_volume)}건 발견')

        # 일자별 정렬 (최근순)
        high_volume.sort(key=lambda x: x['date'], reverse=True)

        print('\n=== 최근 거래대금 1000억 이상 (일자별) ===')
        for s in high_volume[:15]:
            tv_억 = round(s['trading_value'] / 100_000_000, 0)
            print(f"{s['date']} | {s['code']} {s['name']}: {tv_억:.0f}억 @ {s['close']:,}원")

        # Step 2: 상위 3종목 선정 (중복 제거)
        seen_codes = set()
        test_stocks = []
        for s in high_volume:
            if s['code'] not in seen_codes:
                seen_codes.add(s['code'])
                test_stocks.append(s)
                if len(test_stocks) >= 3:
                    break

        print(f'\n[Step 2] 테스트 대상 3종목:')
        for i, s in enumerate(test_stocks):
            tv_억 = round(s['trading_value'] / 100_000_000, 0)
            print(f"  {i+1}. {s['code']} {s['name']} ({s['date']}, {tv_억:.0f}억)")

        # Step 3: 각 종목별 3분봉 청산 테스트
        print('\n[Step 3] 3분봉 청산 로직 테스트...')
        results = []

        for stock in test_stocks:
            code = stock['code']
            name = stock['name']
            signal_date = stock['date']

            print(f'\n--- {code} {name} ---')

            # 3분봉 데이터 조회
            minute_df = await get_3min_candles(market_api, code)
            if minute_df is None or len(minute_df) < 50:
                print(f'  3분봉 데이터 부족: {len(minute_df) if minute_df is not None else 0}개')
                continue

            print(f'  3분봉 데이터: {len(minute_df)}개')
            print(f'  기간: {minute_df["datetime"].iloc[0]} ~ {minute_df["datetime"].iloc[-1]}')

            # 진입가 설정 (1000억봉 다음날 시가 가정)
            # 실제로는 다음날 시가를 사용해야 하지만, 여기서는 1000억봉 종가 기준으로 테스트
            entry_price = stock['close']
            entry_idx = 50  # 충분한 지표 계산 후 진입

            print(f'  진입가: {entry_price:,}원 (1000억봉 종가 기준)')

            # 청산 시뮬레이션
            exit_result = simulate_3min_exit(minute_df, entry_price, entry_idx)

            if exit_result:
                print(f'  청산가: {exit_result["exit_price"]:,}원')
                print(f'  청산사유: {exit_result["exit_reason"]}')
                print(f'  청산시각: {exit_result["exit_datetime"]}')
                print(f'  수익률: {exit_result["pnl_pct"]:+.2f}%')

                results.append({
                    'code': code,
                    'name': name,
                    'signal_date': signal_date,
                    'entry_price': entry_price,
                    **exit_result
                })

            await asyncio.sleep(1)  # API 제한

        # 결과 요약
        print('\n' + '=' * 60)
        print('  테스트 결과 요약')
        print('=' * 60)

        if results:
            total_pnl = sum(r['pnl_pct'] for r in results)
            wins = [r for r in results if r['pnl_pct'] > 0]
            losses = [r for r in results if r['pnl_pct'] <= 0]

            print(f'거래 수: {len(results)}')
            print(f'승/패: {len(wins)}/{len(losses)}')
            print(f'승률: {len(wins)/len(results)*100:.1f}%')
            print(f'총 수익률: {total_pnl:+.2f}%')
            print(f'평균 수익률: {total_pnl/len(results):+.2f}%')

            print('\n[상세]')
            for r in results:
                print(f"  {r['code']} {r['name']}: {r['pnl_pct']:+.2f}% ({r['exit_reason']})")
        else:
            print('테스트 결과 없음')

        print('\n테스트 완료')


if __name__ == '__main__':
    asyncio.run(test_3_stocks())
