"""
삼성전자 1주 매수/매도 테스트 스크립트

모의투자 환경에서 삼성전자 1주를 시장가로 매수한 후 매도합니다.
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_settings
from src.utils.logger import setup_logging
from src.api.auth import get_token_manager
from src.api.client import KiwoomAPIClient
from src.api.endpoints.order import OrderAPI, OrderType
from src.api.endpoints.account import AccountAPI
from src.notification.telegram import TelegramBot


SAMSUNG_CODE = "005930"  # 삼성전자
telegram: TelegramBot = None


async def test_token():
    """토큰 발급 테스트"""
    print("\n" + "=" * 50)
    print("[1] 토큰 발급")
    print("=" * 50)

    token_manager = get_token_manager()
    try:
        token = await token_manager.get_token()
        print(f"토큰 발급 성공: {token[:20]}...")
        return True
    except Exception as e:
        print(f"토큰 발급 실패: {e}")
        return False


async def show_balance(client: KiwoomAPIClient, label: str):
    """잔고 조회"""
    print(f"\n[{label}] 잔고 현황")
    print("-" * 30)

    try:
        account_api = AccountAPI(client)
        balance = await account_api.get_balance()
        print(f"예수금: {balance.deposit:,}원")
        print(f"주문가능: {balance.available_amount:,}원")
        return balance
    except Exception as e:
        print(f"잔고 조회 실패: {e}")
        return None


async def show_positions(client: KiwoomAPIClient, label: str):
    """보유종목 조회"""
    print(f"\n[{label}] 보유 종목")
    print("-" * 30)

    try:
        account_api = AccountAPI(client)
        summary = await account_api.get_positions()

        if not summary.positions:
            print("보유 종목 없음")
        else:
            for pos in summary.positions:
                print(f"  {pos.stock_name} ({pos.stock_code}): {pos.quantity}주")

        return summary
    except Exception as e:
        print(f"보유종목 조회 실패: {e}")
        return None


async def buy_samsung(client: KiwoomAPIClient):
    """삼성전자 1주 매수"""
    global telegram
    print("\n" + "=" * 50)
    print("[2] 삼성전자 1주 시장가 매수")
    print("=" * 50)

    order_api = OrderAPI(client)

    try:
        result = await order_api.buy(
            stock_code=SAMSUNG_CODE,
            quantity=1,
            order_type=OrderType.MARKET,
        )

        if result.success:
            print(f"매수 주문 성공!")
            print(f"  주문번호: {result.order_no}")
            print(f"  거래소: {result.exchange}")
            print(f"  메시지: {result.message}")

            # 텔레그램 알림
            if telegram:
                await telegram.send_message(
                    f"[매수 주문 완료]\n"
                    f"종목: 삼성전자 (005930)\n"
                    f"수량: 1주\n"
                    f"주문번호: {result.order_no}\n"
                    f"거래소: {result.exchange}"
                )
        else:
            print(f"매수 주문 실패: {result.message}")

        return result

    except Exception as e:
        print(f"매수 주문 에러: {e}")
        return None


async def sell_samsung(client: KiwoomAPIClient):
    """삼성전자 1주 매도"""
    global telegram
    print("\n" + "=" * 50)
    print("[4] 삼성전자 1주 시장가 매도")
    print("=" * 50)

    order_api = OrderAPI(client)

    try:
        result = await order_api.sell(
            stock_code=SAMSUNG_CODE,
            quantity=1,
            order_type=OrderType.MARKET,
        )

        if result.success:
            print(f"매도 주문 성공!")
            print(f"  주문번호: {result.order_no}")
            print(f"  거래소: {result.exchange}")
            print(f"  메시지: {result.message}")

            # 텔레그램 알림
            if telegram:
                await telegram.send_message(
                    f"[매도 주문 완료]\n"
                    f"종목: 삼성전자 (005930)\n"
                    f"수량: 1주\n"
                    f"주문번호: {result.order_no}\n"
                    f"거래소: {result.exchange}"
                )
        else:
            print(f"매도 주문 실패: {result.message}")

        return result

    except Exception as e:
        print(f"매도 주문 에러: {e}")
        return None


async def main():
    """메인 테스트 함수"""
    global telegram
    setup_logging()

    settings = get_settings()

    print("\n" + "=" * 50)
    print("삼성전자 1주 매수/매도 테스트")
    print("=" * 50)
    print(f"환경: {settings.environment}")
    print(f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}")

    # 텔레그램 봇 초기화
    telegram = TelegramBot()
    await telegram.send_message(
        f"[테스트 시작]\n"
        f"삼성전자 1주 매수/매도 테스트\n"
        f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}"
    )

    # 1. 토큰 발급
    if not await test_token():
        print("\n토큰 발급 실패로 테스트 중단")
        return False

    async with KiwoomAPIClient() as client:
        # 2. 초기 잔고 확인
        await show_balance(client, "초기")
        await show_positions(client, "초기")

        # 3. 삼성전자 1주 매수
        buy_result = await buy_samsung(client)
        if not buy_result or not buy_result.success:
            print("\n매수 실패로 테스트 중단")
            return False

        # 4. 체결 대기
        print("\n체결 대기 중... (3초)")
        await asyncio.sleep(3)

        # 5. 매수 후 보유종목 확인
        await show_positions(client, "매수 후")

        # 6. 삼성전자 1주 매도
        sell_result = await sell_samsung(client)
        if not sell_result or not sell_result.success:
            print("\n매도 실패")
            return False

        # 7. 체결 대기
        print("\n체결 대기 중... (3초)")
        await asyncio.sleep(3)

        # 8. 최종 잔고 확인
        await show_balance(client, "최종")
        await show_positions(client, "최종")

    print("\n" + "=" * 50)
    print("테스트 완료!")
    print("=" * 50)

    # 테스트 완료 알림
    await telegram.send_message("[테스트 완료] 삼성전자 1주 매수/매도 성공!")

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
