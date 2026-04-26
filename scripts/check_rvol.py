#!/usr/bin/env python3
"""Check RVOL for Watchlist stocks"""
import os
import sys
os.chdir('/home/ubuntu/K_stock_trading/current')
sys.path.insert(0, '/home/ubuntu/K_stock_trading/current')

import asyncio
from dotenv import load_dotenv
load_dotenv()

from src.api.kiwoom_api import KiwoomAPI

async def check_rvol():
    api = KiwoomAPI()
    await api.initialize()

    # 주요 종목들
    codes = [
        ("454910", "두산로보틱스"),
        ("277810", "레인보우로보틱스"),
        ("307950", "현대오토에버"),
        ("0015G0", "그린광학"),
        ("234030", "싸이닉솔루션"),
        ("000910", "유니온"),
        ("108490", "로보티즈"),
        ("464080", "에스오에스랩"),
    ]

    print("=" * 60)
    print(f"{'종목명':<15} {'RVOL':>8} {'금일거래량':>12} {'전일거래량':>12}")
    print("=" * 60)

    for code, name in codes:
        try:
            # 현재가 조회
            quote = await api._market_api.get_stock_quote(code)
            if not quote:
                print(f"{name:<15} {'N/A':>8}")
                continue

            today_vol = quote.volume if quote.volume else 0
            prev_vol = quote.prev_volume if hasattr(quote, 'prev_volume') and quote.prev_volume else 0

            if prev_vol > 0:
                rvol = (today_vol / prev_vol) * 100
                print(f"{name:<15} {rvol:>7.1f}% {today_vol:>12,} {prev_vol:>12,}")
            else:
                print(f"{name:<15} {'N/A':>8} {today_vol:>12,} {prev_vol:>12,}")

        except Exception as e:
            print(f"{name:<15} Error: {e}")

    print("=" * 60)
    print("RVOL >= 200% 이어야 Candidate 승격 가능")

    await api.close()

if __name__ == "__main__":
    asyncio.run(check_rvol())
