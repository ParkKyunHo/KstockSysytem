"""
API 테스트 스크립트

모의투자 환경에서 토큰 발급 및 기본 API 호출을 테스트합니다.
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_config, get_settings
from src.utils.logger import setup_logging
from src.api.auth import get_token_manager


async def test_token():
    """토큰 발급 테스트"""
    print("\n" + "=" * 50)
    print("토큰 발급 테스트")
    print("=" * 50)

    config = get_config()
    settings = get_settings()

    print(f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}")
    print(f"API 호스트: {settings.api_host}")

    try:
        app_key, app_secret = config.get_active_credentials()
        print(f"App Key: {app_key[:10]}...")
        print(f"App Secret: {app_secret[:10]}...")
    except Exception as e:
        print(f"인증 정보 오류: {e}")
        return False

    print("\n토큰 발급 중...")
    token_manager = get_token_manager()

    try:
        token = await token_manager.get_token()
        print(f"토큰 발급 성공!")
        print(f"토큰: {token[:20]}...")
        print(f"남은 시간: {token_manager._token.remaining_seconds}초")
        return True

    except Exception as e:
        print(f"토큰 발급 실패: {e}")
        return False


async def test_balance():
    """잔고 조회 테스트"""
    print("\n" + "=" * 50)
    print("잔고 조회 테스트")
    print("=" * 50)

    from src.api.client import KiwoomAPIClient
    from src.api.endpoints.account import AccountAPI

    try:
        async with KiwoomAPIClient() as client:
            account_api = AccountAPI(client)
            balance = await account_api.get_balance()

            print(f"예수금: {balance.deposit:,}원")
            print(f"주문가능: {balance.available_amount:,}원")
            print(f"D+2 예수금: {balance.d2_estimated_deposit:,}원")
            return True

    except Exception as e:
        print(f"잔고 조회 실패: {e}")
        return False


async def test_positions():
    """보유종목 조회 테스트"""
    print("\n" + "=" * 50)
    print("보유종목 조회 테스트")
    print("=" * 50)

    from src.api.client import KiwoomAPIClient
    from src.api.endpoints.account import AccountAPI

    try:
        async with KiwoomAPIClient() as client:
            account_api = AccountAPI(client)
            summary = await account_api.get_positions()

            print(f"계좌명: {summary.account_name}")
            print(f"총평가: {summary.total_eval_amount:,}원")
            print(f"총손익: {summary.total_profit_loss:+,}원 ({summary.profit_loss_rate:+.2f}%)")
            print(f"\n보유 종목 ({len(summary.positions)}개):")

            for pos in summary.positions:
                print(f"  - {pos.stock_name} ({pos.stock_code}): "
                      f"{pos.quantity}주, {pos.profit_loss_rate:+.2f}%")

            return True

    except Exception as e:
        print(f"보유종목 조회 실패: {e}")
        return False


async def main():
    """메인 테스트 함수"""
    # 로깅 설정
    setup_logging()

    print("\n" + "=" * 50)
    print("키움증권 API 테스트")
    print("=" * 50)

    settings = get_settings()
    print(f"\n환경: {settings.environment}")
    print(f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}")

    # 테스트 실행
    results = []

    # 1. 토큰 발급
    results.append(("토큰 발급", await test_token()))

    # 2. 잔고 조회
    results.append(("잔고 조회", await test_balance()))

    # 3. 보유종목 조회
    results.append(("보유종목 조회", await test_positions()))

    # 결과 요약
    print("\n" + "=" * 50)
    print("테스트 결과")
    print("=" * 50)

    for name, success in results:
        status = "[OK] 성공" if success else "[FAIL] 실패"
        print(f"{name}: {status}")

    all_passed = all(r[1] for r in results)
    print(f"\n전체 결과: {'[OK] 모두 통과' if all_passed else '[FAIL] 일부 실패'}")

    return all_passed


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
