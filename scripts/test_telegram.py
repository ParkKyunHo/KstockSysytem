"""
텔레그램 봇 테스트 스크립트

메시지 전송이 정상적으로 동작하는지 확인합니다.
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_telegram_settings
from src.notification.telegram import TelegramBot
from src.notification.templates import (
    format_start_notification,
    format_balance_notification,
    format_help_message,
)


async def test_telegram():
    """텔레그램 메시지 전송 테스트"""
    print("=" * 50)
    print("텔레그램 봇 테스트")
    print("=" * 50)

    # 설정 확인
    settings = get_telegram_settings()
    print(f"\nBot Token: {settings.bot_token[:20]}...")
    print(f"Chat ID: {settings.chat_id}")

    # 봇 생성
    bot = TelegramBot()

    # 테스트 1: 간단한 메시지
    print("\n[테스트 1] 간단한 메시지 전송...")
    success = await bot.send_message(
        "K_stock_trading 봇 테스트 메시지입니다.\n\n"
        "이 메시지가 보이면 텔레그램 연동 성공!"
    )
    print(f"결과: {'성공' if success else '실패'}")

    if not success:
        print("\n[오류] 메시지 전송 실패. 봇 토큰과 Chat ID를 확인하세요.")
        return False

    # 테스트 2: 시작 알림 템플릿
    print("\n[테스트 2] 시작 알림 템플릿 전송...")
    success = await bot.send_message(format_start_notification(is_paper_trading=True))
    print(f"결과: {'성공' if success else '실패'}")

    # 테스트 3: 잔고 알림 템플릿
    print("\n[테스트 3] 잔고 알림 템플릿 전송...")
    success = await bot.send_message(
        format_balance_notification(
            deposit=100_000_000,
            available=100_000_000,
        )
    )
    print(f"결과: {'성공' if success else '실패'}")

    # 테스트 4: 버튼 메시지
    print("\n[테스트 4] 버튼 메시지 전송...")
    success = await bot.send_eod_choice()
    print(f"결과: {'성공' if success else '실패'}")

    print("\n" + "=" * 50)
    print("텔레그램 테스트 완료!")
    print("텔레그램 앱에서 메시지를 확인하세요.")
    print("=" * 50)

    return True


if __name__ == "__main__":
    success = asyncio.run(test_telegram())
    sys.exit(0 if success else 1)
