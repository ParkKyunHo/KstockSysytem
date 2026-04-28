#!/usr/bin/env python3
"""Watchlist 종목 RVOL 체크 (간단 버전)"""
import os
import sys

# 경로 설정 먼저
os.chdir('/home/ubuntu/K_stock_trading/current')
sys.path.insert(0, '/home/ubuntu/K_stock_trading/current')

# 이후 import
import asyncio
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/K_stock_trading/current/.env')

from src.api.kiwoom_api import KiwoomAPI

async def check_rvol():
    api = KiwoomAPI()
    await api.initialize()

    # Watchlist 종목들 (로그에서 확인된 종목)
    codes = [
        ("0015G0", "그린광학"),
        ("0015S0", "페스카로"),
        ("000910", "유니온"),
        ("003310", "금호산업"),
        ("006140", "피씨엘"),
        ("006800", "미래에셋증권"),
        ("047810", "한국항공우주"),
        ("053450", "한세실업"),
        ("090710", "휴림로봇"),
        ("098460", "고영"),
        ("234030", "싸이닉솔루션"),
        ("240810", "원익IPS"),
        ("307950", "현대오토에버"),
        ("332570", "가온미디어"),
        ("454910", "두산로보틱스"),
        ("464080", "에스오에스랩"),
        ("474170", "텔레필드"),
    ]

    print("=" * 70)
    print(f"{'종목명':<15} {'RVOL':>10} {'금일':>12} {'전일':>12} {'상태':>8}")
    print("=" * 70)

    for code, name in codes:
        try:
            # 일봉 조회
            daily = await api._market_api.get_daily_chart(code, count=5)
            if not daily or len(daily) < 2:
                print(f"{name:<15} {'N/A':>10} - 데이터 부족")
                continue

            today_vol = daily[0].volume if daily[0].volume else 0
            prev_vol = daily[1].volume if daily[1].volume else 0

            if prev_vol > 0:
                rvol = (today_vol / prev_vol) * 100
                status = "OK" if rvol >= 200 else "FAIL"
                print(f"{name:<15} {rvol:>9.1f}% {today_vol:>12,} {prev_vol:>12,} {status:>8}")
            else:
                print(f"{name:<15} {'N/A':>10} {today_vol:>12,} {prev_vol:>12,} {'N/A':>8}")

        except Exception as e:
            print(f"{name:<15} Error: {str(e)[:30]}")

    print("=" * 70)
    print("RVOL >= 200% 이어야 Candidate 승격 가능")

    await api.close()

if __name__ == "__main__":
    asyncio.run(check_rvol())
