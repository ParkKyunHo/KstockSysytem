# Daily SNIPER_TRAP Analysis Script
# Usage: powershell -ExecutionPolicy Bypass -File "scripts/analyze_daily.ps1"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$key = Join-Path $env:USERPROFILE ".ssh\k-stock-trading-key.pem"
$today = Get-Date -Format "yyyy-MM-dd"

Write-Host "=== Daily SNIPER_TRAP Analysis ===" -ForegroundColor Cyan
Write-Host "Date: $today" -ForegroundColor Cyan
Write-Host ""

# Default tickers (can be updated based on actual pool)
$tickers = @('022100', '059120', '007660', '090710', '056080', '277810', '319400', '272210', '000880', '047050')
$tickerStr = $tickers -join ","

Write-Host "Analyzing tickers: $tickerStr" -ForegroundColor Gray
Write-Host ""

# Create Python script on server and execute
$pythonScript = @'
import asyncio
import pandas as pd
import sys
from datetime import datetime, time as dt_time
from collections import Counter
from src.api.endpoints.market import MarketAPI
from src.api.client import KiwoomAPIClient
from src.utils.config import AppConfig

TICKERS = sys.argv[1].split(',') if len(sys.argv) > 1 else ['022100']
SIGNAL_START = dt_time(9, 20)
SIGNAL_END = dt_time(15, 20)

async def analyze_ticker(client, ticker):
    market = MarketAPI(client)
    result = {
        'ticker': ticker,
        'signals': [],
        'fail_counts': Counter(),
        'analyzed': 0,
        'candle_count': 0
    }
    try:
        candles = await market.get_minute_chart(ticker, timeframe=3, count=400)
        if not candles:
            result['error'] = 'No candles'
            return result
        data = [{'time': c.timestamp, 'open': c.open_price, 'high': c.high_price, 'low': c.low_price, 'close': c.close_price, 'volume': c.volume} for c in candles]
        df = pd.DataFrame(data).sort_values('time').reset_index(drop=True)
        result['candle_count'] = len(df)
        df['ema3'] = df['close'].ewm(span=3, adjust=False).mean()
        df['ema20'] = df['close'].ewm(span=20, adjust=False).mean()
        df['ema60'] = df['close'].ewm(span=60, adjust=False).mean()
        df['ema200'] = df['close'].ewm(span=200, adjust=False).mean()
        analysis_start = min(200, len(df) - 10)
        for i in range(analysis_start, len(df)):
            if i < 5:
                continue
            row = df.iloc[i]
            prev = df.iloc[i-1]
            prev5 = df.iloc[i-5]
            try:
                ts = row['time']
                candle_time = datetime.strptime(str(ts), '%Y%m%d%H%M%S').time() if isinstance(ts, (str, int)) else None
            except:
                candle_time = None
            if candle_time and not (SIGNAL_START <= candle_time <= SIGNAL_END):
                continue
            result['analyzed'] += 1
            o, h, l, c, v = row['open'], row['high'], row['low'], row['close'], row['volume']
            e3, e20, e60, e200 = row['ema3'], row['ema20'], row['ema60'], row['ema200']
            prev_c, prev_e3, prev_v = prev['close'], prev['ema3'], prev['volume']
            prev5_e60 = prev5['ema60']
            trend_close = c > e200
            trend_ema60 = e60 > prev5_e60
            trend_filter = trend_close and trend_ema60
            zone_l = l <= e20
            zone_c = c >= e60
            zone = zone_l and zone_c
            crossup = prev_c < prev_e3 and c >= e3
            bullish = c > o
            vol_inc = v >= prev_v
            meaningful = crossup and bullish and vol_inc
            body_pct = (c - o) / o * 100 if o > 0 else 0
            body_ok = body_pct >= 0.3
            sniper_trap = trend_filter and zone and meaningful and body_ok
            if sniper_trap:
                result['signals'].append({'time': str(row['time']), 'price': int(c)})
            else:
                if not trend_filter:
                    if not trend_close:
                        result['fail_counts']['TrendFilter(C<E200)'] += 1
                    else:
                        result['fail_counts']['TrendFilter(E60down)'] += 1
                elif not zone:
                    if not zone_l:
                        result['fail_counts']['Zone(L>E20)'] += 1
                    else:
                        result['fail_counts']['Zone(C<E60)'] += 1
                elif not meaningful:
                    if not crossup:
                        result['fail_counts']['Meaningful(noCrossUp)'] += 1
                    elif not bullish:
                        result['fail_counts']['Meaningful(bearish)'] += 1
                    else:
                        result['fail_counts']['Meaningful(volDec)'] += 1
                else:
                    result['fail_counts']['BodySize(<0.3%)'] += 1
        return result
    except Exception as e:
        result['error'] = str(e)
        return result

async def main():
    config = AppConfig()
    async with KiwoomAPIClient(config) as client:
        print('='*70)
        print('SNIPER_TRAP Daily Analysis with Failure Statistics')
        print('='*70)
        all_signals = []
        total_fail_counts = Counter()
        for ticker in TICKERS:
            result = await analyze_ticker(client, ticker)
            if 'error' in result:
                print(f'{ticker}: ERROR - {result["error"]}')
                continue
            sig_count = len(result['signals'])
            analyzed = result['analyzed']
            print(f'\n{ticker}: {sig_count} signals / {analyzed} candles analyzed')
            if result['fail_counts']:
                fails = dict(result['fail_counts'])
                sorted_fails = sorted(fails.items(), key=lambda x: -x[1])
                fail_str = ', '.join([f'{k}={v}' for k, v in sorted_fails[:4]])
                print(f'  Failures: {fail_str}')
                for k, v in result['fail_counts'].items():
                    total_fail_counts[k] += v
            if result['signals']:
                for s in result['signals'][:5]:
                    print(f'  + {s["time"]} @ {s["price"]:,}')
                if len(result['signals']) > 5:
                    print(f'  ... and {len(result["signals"])-5} more')
                all_signals.extend([{'ticker': ticker, **s} for s in result['signals']])
            await asyncio.sleep(0.3)
        print('')
        print('='*70)
        print('SUMMARY')
        print('='*70)
        print(f'Tickers analyzed: {len(TICKERS)}')
        print(f'Tickers with signals: {len(set(s["ticker"] for s in all_signals))}')
        print(f'Total signals: {len(all_signals)}')
        print('')
        print('Failure breakdown (all tickers):')
        sorted_total = sorted(total_fail_counts.items(), key=lambda x: -x[1])
        for reason, count in sorted_total:
            pct = count / sum(total_fail_counts.values()) * 100 if total_fail_counts else 0
            print(f'  {reason}: {count} ({pct:.1f}%)')

asyncio.run(main())
'@

# Save script to server
$scriptPath = "/tmp/analyze_daily.py"
$pythonScript | ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 "cat > $scriptPath"

# Execute script
Write-Host "Running analysis..." -ForegroundColor Yellow
ssh -i $key -o StrictHostKeyChecking=no ubuntu@43.200.235.74 "cd /home/ubuntu/K_stock_trading/current && source venv/bin/activate && PYTHONPATH=/home/ubuntu/K_stock_trading/current python3 $scriptPath $tickerStr 2>&1 | grep -vE '\[debug|debug\s*\]|페이지.*조회'"

Write-Host ""
Write-Host "=== Analysis Complete ===" -ForegroundColor Green
