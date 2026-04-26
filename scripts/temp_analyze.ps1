[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$LIGHTSAIL_KEY = "$env:USERPROFILE\.ssh\k-stock-trading-key.pem"

$pythonScript = @"
import asyncio
import pandas as pd
from src.api.client import KiwoomClient
from src.utils.config import Settings

async def main():
    config = Settings()
    client = KiwoomClient(config)

    candles = await client.get_minute_chart('277810', timeframe=3, count=100)

    if not candles:
        print('No data')
        return

    df = pd.DataFrame(candles)
    df['close'] = pd.to_numeric(df['close'], errors='coerce')
    df['open'] = pd.to_numeric(df['open'], errors='coerce')
    df['high'] = pd.to_numeric(df['high'], errors='coerce')
    df['low'] = pd.to_numeric(df['low'], errors='coerce')
    df['volume'] = pd.to_numeric(df['volume'], errors='coerce')

    df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
    df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
    df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
    df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()

    print(f'Total: {len(df)} candles')
    for i, row in df.iterrows():
        time_str = str(row.get('time', ''))
        if '1324' in time_str or '1327' in time_str or '1330' in time_str or '1333' in time_str or '1336' in time_str:
            print(f'Time: {time_str}')
            print(f'  O={int(row[\"open\"]):,} H={int(row[\"high\"]):,} L={int(row[\"low\"]):,} C={int(row[\"close\"]):,} V={int(row[\"volume\"]):,}')
            print(f'  EMA3={int(row[\"ema3\"]):,} EMA20={int(row[\"ema20\"]):,} EMA60={int(row[\"ema60\"]):,} EMA200={int(row[\"ema200\"]):,}')
            print()

asyncio.run(main())
"@

ssh -i $LIGHTSAIL_KEY -o StrictHostKeyChecking=no ubuntu@43.200.235.74 "cd /home/ubuntu/K_stock_trading/current && python3 -c '$pythonScript'"
