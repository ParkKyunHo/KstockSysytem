[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$key = Join-Path $env:USERPROFILE ".ssh\k-stock-trading-key.pem"

ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 @"
cd /home/ubuntu/K_stock_trading/current && source venv/bin/activate && python3 << 'PYTHON_EOF'
import asyncio
import pandas as pd
from src.api.endpoints.market import MarketAPI
from src.api.client import KiwoomAPIClient
from src.utils.config import AppConfig

async def main():
    config = AppConfig()
    async with KiwoomAPIClient(config) as client:
        market = MarketAPI(client)
        candles = await market.get_minute_chart('059120', timeframe=3, count=100)
        data = [{'time': c.timestamp, 'open': c.open_price, 'high': c.high_price, 'low': c.low_price, 'close': c.close_price, 'volume': c.volume} for c in candles]
        df = pd.DataFrame(data).sort_values('time').reset_index(drop=True)
        df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        print(f'Total: {len(df)} candles')
        for i, row in df.iterrows():
            ts = str(row['time'])
            if '09:' in ts or '10:' in ts or '11:' in ts or '12:' in ts or '13:' in ts or '14:' in ts or '15:' in ts:
                o,h,l,c,v = int(row['open']),int(row['high']),int(row['low']),int(row['close']),int(row['volume'])
                e3,e20,e60,e200 = int(row['ema3']),int(row['ema20']),int(row['ema60']),int(row['ema200'])
                prev = df.iloc[i-1] if i>0 else row
                prev_c,prev_e3,prev_v = int(prev['close']),int(prev['ema3']),int(prev['volume'])
                print(f'Time: {ts}')
                print(f'  O={o:,} H={h:,} L={l:,} C={c:,} V={v:,}')
                print(f'  EMA3={e3:,} EMA20={e20:,} EMA60={e60:,} EMA200={e200:,}')
                zone_l = l <= e20
                zone_c = c >= e60
                crossup = prev_c < prev_e3 and c >= e3
                bullish = c > o
                vol_inc = v >= prev_v
                body_pct = (c-o)/o*100 if o>0 else 0
                print(f'  [Zone] L({l:,})<=EMA20({e20:,})? {zone_l}, C({c:,})>=EMA60({e60:,})? {zone_c} => {zone_l and zone_c}')
                print(f'  [Meaningful] CrossUp? {crossup}, Bullish? {bullish}, VolInc? {vol_inc} => {crossup and bullish and vol_inc}')
                print(f'  [BodySize] {body_pct:.2f}% >= 0.3%? {body_pct >= 0.3}')
                print(f'  [TrendFilter] C({c:,})>EMA200({e200:,})? {c > e200}')
                all_ok = (zone_l and zone_c) and (crossup and bullish and vol_inc) and (body_pct >= 0.3) and (c > e200)
                print(f'  => SNIPER_TRAP: {all_ok}')
                print()

asyncio.run(main())
PYTHON_EOF
"@
