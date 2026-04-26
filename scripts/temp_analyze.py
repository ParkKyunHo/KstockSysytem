#!/usr/bin/env python3
import asyncio
import pandas as pd
import sys
sys.path.insert(0, 'C:/K_stock_trading')

from src.api.endpoints.market import MarketAPI
from src.api.client import KiwoomAPIClient
from src.utils.config import AppConfig

async def main():
    config = AppConfig()

    async with KiwoomAPIClient(config) as client:
        market = MarketAPI(client)

        stock_code = '466100'
        stock_name = '클로봇'

        # 1. 일봉 데이터로 20일 평균 거래량 계산
        print(f'=== {stock_name}({stock_code}) 분석 ===')
        print()

        daily_candles = await market.get_daily_chart(stock_code, count=25)
        sorted_daily = sorted(daily_candles, key=lambda x: x.date)

        # 최근 일봉 출력
        print('최근 일봉:')
        for c in sorted_daily[-5:]:
            print(f'{str(c.date)[:10]}: C={c.close_price:,}원, V={c.volume:,}주, {c.change_rate:+.2f}%')

        # 20일 평균 계산 (1/19 제외)
        prev_20 = sorted_daily[-21:-1]
        avg_volume_20d = sum(c.volume for c in prev_20) / 20 if len(prev_20) >= 20 else sum(c.volume for c in prev_20) / len(prev_20)
        threshold_150 = avg_volume_20d * 1.5

        print(f'20일 평균 거래량: {avg_volume_20d:,}주')
        print(f'150% 기준선: {threshold_150:,.0f}주')
        print()

        # 3분봉으로 장중 누적 거래량 분석
        print('=== 1/19 장중 누적 거래량 분석 ===')
        try:
            min_candles = await market.get_minute_chart('056080', timeframe=3, count=200)

            # 1/19 데이터만 필터링 후 시간순 정렬
            candles_0119 = [c for c in min_candles if '2026-01-19' in str(c.timestamp)]
            sorted_candles = sorted(candles_0119, key=lambda x: x.timestamp)

            cumulative_volume = 0
            crossed_150 = False
            crossed_time = None

            print(f'시간       | 봉거래량   | 누적거래량    | 거래량비율 | 150% 도달')
            print('-' * 75)

            for c in sorted_candles:
                ts = str(c.timestamp)
                time_str = ts[11:16]  # HH:MM
                hour = int(ts[11:13])

                cumulative_volume += c.volume
                ratio = (cumulative_volume / avg_volume_20d) * 100

                # 09:00~14:00 사이만 출력 (30분 간격)
                minute = int(ts[14:16])
                if 9 <= hour <= 14 and minute in [0, 30]:
                    status = "✓" if ratio >= 150 else ""
                    print(f'{time_str}      | {c.volume:>10,} | {cumulative_volume:>13,} | {ratio:>9.1f}% | {status}')

                # 150% 처음 도달 시점 기록
                if not crossed_150 and ratio >= 150:
                    crossed_150 = True
                    crossed_time = time_str
                    print(f'>>> {time_str}: 150% 도달! (누적 {cumulative_volume:,}주, {ratio:.1f}%) <<<')

            print('-' * 75)
            print(f'최종 누적: {cumulative_volume:,}주 ({cumulative_volume/avg_volume_20d*100:.1f}%)')

            if crossed_time:
                print(f'\n*** 150% 도달 시각: {crossed_time} ***')
            else:
                print(f'\n*** 150% 미도달 ***')

        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f'Error: {e}')

        # 2. SNIPER_TRAP 조건 분석 (3분봉)
        print()
        print('=== SNIPER_TRAP 조건 분석 ===')
        try:
            min_candles = await market.get_minute_chart(stock_code, timeframe=3, count=200)

            # 1/19 데이터만 필터링
            candles_0119 = [c for c in min_candles if '2026-01-19' in str(c.timestamp)]
            sorted_candles = sorted(candles_0119, key=lambda x: x.timestamp)

            # DataFrame으로 변환
            candle_dicts = []
            for c in sorted_candles:
                candle_dicts.append({
                    'time': c.timestamp,
                    'open': c.open_price,
                    'high': c.high_price,
                    'low': c.low_price,
                    'close': c.close_price,
                    'volume': c.volume
                })

            df = pd.DataFrame(candle_dicts)
            df = df.sort_values('time').reset_index(drop=True)

            # EMA 계산
            df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
            df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
            df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
            df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

            print(f'분석 봉 수: {len(df)}개')
            print()

            sniper_signals = []

            for i in range(1, len(df)):
                row = df.iloc[i]
                prev = df.iloc[i-1]
                time_str = str(row['time'])
                hour = int(time_str[11:13])

                # 11시 이후만 분석
                if hour < 11:
                    continue

                o, h, l, c, v = int(row['open']), int(row['high']), int(row['low']), int(row['close']), int(row['volume'])
                e3, e20, e60, e200 = int(row['ema3']), int(row['ema20']), int(row['ema60']), int(row['ema200'])
                prev_c, prev_e3, prev_v = int(prev['close']), int(prev['ema3']), int(prev['volume'])

                # SNIPER_TRAP 조건 체크
                trend_ok = c > e200
                zone_l = l <= e20
                zone_c = c >= e60
                zone_ok = zone_l and zone_c
                crossup = prev_c < prev_e3 and c >= e3
                bullish = c > o
                vol_inc = v >= prev_v
                meaningful = crossup and bullish and vol_inc
                body_pct = (c - o) / o * 100 if o > 0 else 0
                body_ok = body_pct >= 0.3

                sniper_trap = trend_ok and zone_ok and meaningful and body_ok

                if sniper_trap:
                    sniper_signals.append({
                        'time': time_str[11:16],
                        'close': c,
                        'zone': zone_ok,
                        'meaningful': meaningful,
                        'body': f'{body_pct:.2f}%'
                    })
                    print(f'** SNIPER_TRAP: {time_str[11:16]} C={c:,}원 **')
                    print(f'   Zone: L({l:,})<=EMA20({e20:,})={zone_l}, C({c:,})>=EMA60({e60:,})={zone_c}')
                    print(f'   Meaningful: CrossUp={crossup}, Bullish={bullish}, VolInc={vol_inc}')
                    print(f'   BodySize: {body_pct:.2f}%')
                    print()

            if not sniper_signals:
                print('SNIPER_TRAP 신호 없음')
                print()
                # 왜 신호가 없는지 분석 (11시~15시 중 일부 봉 출력)
                print('=== 조건 미충족 상세 (11시~13시) ===')
                for i in range(1, len(df)):
                    row = df.iloc[i]
                    prev = df.iloc[i-1]
                    time_str = str(row['time'])
                    hour = int(time_str[11:13])
                    minute = int(time_str[14:16])

                    if hour < 11 or hour > 13:
                        continue
                    if minute not in [0, 30]:
                        continue

                    o, h, l, c, v = int(row['open']), int(row['high']), int(row['low']), int(row['close']), int(row['volume'])
                    e3, e20, e60, e200 = int(row['ema3']), int(row['ema20']), int(row['ema60']), int(row['ema200'])
                    prev_c, prev_e3 = int(prev['close']), int(prev['ema3'])

                    trend_ok = c > e200
                    zone_l = l <= e20
                    zone_c = c >= e60
                    zone_ok = zone_l and zone_c

                    print(f'{time_str[11:16]}: C={c:,} EMA20={e20:,} EMA60={e60:,} EMA200={e200:,}')
                    print(f'  Trend(C>E200): {trend_ok}, Zone(L<=E20): {zone_l}, Zone(C>=E60): {zone_c}')

        except Exception as e:
            import traceback
            traceback.print_exc()

        return

        # MinuteCandle dataclass를 딕셔너리로 변환
        candle_dicts = []
        for c in candles:
            candle_dicts.append({
                'time': c.timestamp,
                'open': c.open_price,
                'high': c.high_price,
                'low': c.low_price,
                'close': c.close_price,
                'volume': c.volume
            })

        print(f'Sample: {candle_dicts[0]}')

        df = pd.DataFrame(candle_dicts)
        print(f'Columns: {list(df.columns)}')

        df = df.sort_values('time').reset_index(drop=True)

        df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        print(f'\nTotal: {len(df)} candles')
        print()

        # 1/19 11시 이후 봉만 분석
        for i in range(len(df)):
            row = df.iloc[i]
            time_str = str(row.get('time', ''))
            # 2026-01-19 11시 이후만
            if '2026-01-19' in time_str and int(time_str[11:13]) >= 11:
                o = int(row['open'])
                h = int(row['high'])
                l = int(row['low'])
                c = int(row['close'])
                v = int(row['volume'])
                e3 = int(row['ema3'])
                e20 = int(row['ema20'])
                e60 = int(row['ema60'])
                e200 = int(row['ema200'])

                if i > 0:
                    prev = df.iloc[i-1]
                    prev_c = int(prev['close'])
                    prev_e3 = int(prev['ema3'])
                    prev_v = int(prev['volume'])
                else:
                    prev_c = prev_e3 = prev_v = 0

                print(f'Time: {time_str}')
                print(f'  O={o:,} H={h:,} L={l:,} C={c:,} V={v:,}')
                print(f'  EMA3={e3:,} EMA20={e20:,} EMA60={e60:,} EMA200={e200:,}')

                zone_l = l <= e20
                zone_c = c >= e60
                zone_ok = zone_l and zone_c

                crossup = prev_c < prev_e3 and c >= e3
                bullish = c > o
                vol_inc = v >= prev_v
                meaningful = crossup and bullish and vol_inc

                body_pct = (c - o) / o * 100 if o > 0 else 0
                body_ok = body_pct >= 0.3

                trend_ok = c > e200

                print(f'  [TrendFilter] C>EMA200? {trend_ok}')
                print(f'  [Zone] L({l:,})<=EMA20({e20:,})? {zone_l}, C({c:,})>=EMA60({e60:,})? {zone_c} => {zone_ok}')
                print(f'  [Meaningful] CrossUp? {crossup}, Bullish? {bullish}, VolInc? {vol_inc} => {meaningful}')
                print(f'  [BodySize] {body_pct:.2f}% >= 0.3%? {body_ok}')
                print(f'  => SNIPER_TRAP: {zone_ok and meaningful and body_ok and trend_ok}')
                print()

asyncio.run(main())
