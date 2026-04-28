[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$key = Join-Path $env:USERPROFILE ".ssh\k-stock-trading-key.pem"

ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 @"
cd /home/ubuntu/K_stock_trading/current && source venv/bin/activate && python3 << 'EOF'
import asyncio
import pandas as pd
from src.api.endpoints.market import MarketAPI
from src.api.client import KiwoomAPIClient
from src.utils.config import AppConfig

TICKERS = [
    '022100', '059120', '007660', '452260', '459510', '090710',
    '352820', '000880', '272210', '006800', '277810', '454910',
    '353200', '097230', '319400', '348340',
]

async def analyze(client, ticker):
    market = MarketAPI(client)
    try:
        candles = await market.get_minute_chart(ticker, timeframe=3, count=100)
        if not candles:
            return None
        data = [{'time': c.timestamp, 'open': c.open_price, 'high': c.high_price, 'low': c.low_price, 'close': c.close_price, 'volume': c.volume} for c in candles]
        df = pd.DataFrame(data).sort_values('time').reset_index(drop=True)
        df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

        signals = []
        for i, row in df.iterrows():
            if i == 0:
                continue
            prev = df.iloc[i-1]
            o,h,l,c,v = row['open'],row['high'],row['low'],row['close'],row['volume']
            e3,e20,e60,e200 = row['ema3'],row['ema20'],row['ema60'],row['ema200']
            prev_c,prev_e3,prev_v = prev['close'],prev['ema3'],prev['volume']

            zone_l = l <= e20
            zone_c = c >= e60
            zone = zone_l and zone_c
            crossup = prev_c < prev_e3 and c >= e3
            bullish = c > o
            vol_inc = v >= prev_v
            meaningful = crossup and bullish and vol_inc
            body_pct = (c-o)/o*100 if o>0 else 0
            body_ok = body_pct >= 0.3
            trend = c > e200

            if zone and meaningful and body_ok and trend:
                signals.append((row['time'], c))

        return signals
    except Exception as e:
        return None

async def main():
    config = AppConfig()
    async with KiwoomAPIClient(config) as client:
        print('='*60)
        print('Pool SNIPER_TRAP Analysis')
        print('='*60)

        for ticker in TICKERS:
            signals = await analyze(client, ticker)
            if signals:
                print(f'{ticker}: {len(signals)} signals')
                for ts, px in signals:
                    print(f'  - {ts} @ {int(px):,}')
            else:
                print(f'{ticker}: No signal')
            await asyncio.sleep(0.3)

asyncio.run(main())
EOF
"@
