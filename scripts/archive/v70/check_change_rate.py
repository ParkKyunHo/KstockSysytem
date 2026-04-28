#!/usr/bin/env python3
"""Watchlist 종목 등락률 체크"""
import os
import sys

# 경로 설정 먼저
os.chdir('/home/ubuntu/K_stock_trading/current')
sys.path.insert(0, '/home/ubuntu/K_stock_trading/current')

# 이후 import
import asyncio
from dotenv import load_dotenv
load_dotenv('/home/ubuntu/K_stock_trading/current/.env')

from src.api.endpoints.market import MarketAPI
from src.api.auth.token_manager import TokenManager

async def check_change_rate():
    token_manager = TokenManager()
    api = MarketAPI(token_manager)

    # Watchlist 종목들 (로그에서 확인된 종목)
    codes = [
        ("0015G0", "그린광학"),
        ("0015S0", "페스카로"),
        ("003310", "금호산업"),
        ("006800", "미래에셋증권"),
        ("047810", "한국항공우주"),
        ("053450", "한세실업"),
        ("080220", "제주반도체"),
        ("090710", "휴림로봇"),
        ("098460", "고영"),
        ("240810", "원익IPS"),
        ("307950", "현대오토에버"),
        ("332570", "가온미디어"),
        ("451760", "삼일씨엔에스"),
        ("474170", "텔레필드"),
        ("298830", "슈어소프트테크"),
    ]

    print("=" * 85)
    print(f"{'종목명':<12} {'현재가':>10} {'전일대비':>10} {'등락률(계산)':>12} {'API등락률':>12}")
    print("=" * 85)

    for code, name in codes:
        try:
            # 일봉 조회
            daily = await api.get_daily_chart(code, count=5)
            if not daily or len(daily) < 1:
                print(f"{name:<12} {'N/A':>10} - 데이터 부족")
                continue

            today = daily[0]
            cur_prc = today.close_price
            change_rate = today.change_rate if hasattr(today, 'change_rate') else 0

            # 전일 종가 계산 (현재가 - 변동액 역산)
            if len(daily) >= 2:
                prev_close = daily[1].close_price
                calc_rate = ((cur_prc - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            else:
                prev_close = 0
                calc_rate = 0

            print(f"{name:<12} {cur_prc:>10,} {cur_prc - prev_close:>+10,} {calc_rate:>+11.2f}% {change_rate:>+11.2f}%")

        except Exception as e:
            print(f"{name:<12} Error: {str(e)[:40]}")

    print("=" * 85)
    print("등락률(계산) = (현재가 - 전일종가) / 전일종가 * 100")
    print("API등락률 = DailyCandle.change_rate (pred_pre 기반 계산)")

if __name__ == "__main__":
    asyncio.run(check_change_rate())
