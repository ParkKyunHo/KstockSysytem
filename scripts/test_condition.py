"""
조건식 검색 테스트 스크립트

0번 조건식으로 실시간 검색을 테스트합니다.
종목 편입/이탈 시 텔레그램으로 알림을 보냅니다.
"""

import asyncio
import sys
from pathlib import Path

# 프로젝트 루트를 Python 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.config import get_settings
from src.utils.logger import setup_logging, get_logger
from src.api.auth import get_token_manager
from src.api.websocket import KiwoomWebSocket, SignalEvent
from src.notification.telegram import TelegramBot


CONDITION_SEQ = "0"  # 테스트할 조건식 번호
MONITOR_SECONDS = 60  # 모니터링 시간 (초)

telegram: TelegramBot = None
logger = None
signal_count = 0


async def on_signal(signal: SignalEvent):
    """조건식 신호 수신 콜백"""
    global signal_count
    signal_count += 1

    signal_type = "편입" if signal.is_buy_signal else "이탈"

    print(f"\n[{signal_type}] {signal.stock_name} ({signal.stock_code})")
    print(f"  조건식: {signal.condition_seq}번")
    print(f"  시간: {signal.timestamp}")

    # 텔레그램 알림
    if telegram:
        await telegram.send_message(
            f"[조건식 {signal_type}]\n"
            f"종목: {signal.stock_name} ({signal.stock_code})\n"
            f"조건식: {signal.condition_seq}번\n"
            f"시간: {signal.timestamp}"
        )


async def on_connected():
    """WebSocket 연결 성공 콜백"""
    print("WebSocket 연결됨")
    if telegram:
        await telegram.send_message("[조건식 테스트] WebSocket 연결 성공")


async def on_disconnected():
    """WebSocket 연결 해제 콜백"""
    print("WebSocket 연결 끊김")


async def main():
    """메인 테스트 함수"""
    global telegram, logger

    setup_logging()
    logger = get_logger(__name__)

    settings = get_settings()

    print("\n" + "=" * 50)
    print("조건식 검색 테스트")
    print("=" * 50)
    print(f"환경: {settings.environment}")
    print(f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}")
    print(f"조건식: {CONDITION_SEQ}번")
    print(f"모니터링: {MONITOR_SECONDS}초")
    print("=" * 50)

    # 텔레그램 봇 초기화
    telegram = TelegramBot()
    await telegram.send_message(
        f"[조건식 테스트 시작]\n"
        f"조건식: {CONDITION_SEQ}번\n"
        f"모니터링: {MONITOR_SECONDS}초\n"
        f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}"
    )

    # 1. 토큰 발급
    print("\n[1] 토큰 발급 중...")
    token_manager = get_token_manager()
    try:
        token = await token_manager.get_token()
        print(f"토큰 발급 성공: {token[:20]}...")
    except Exception as e:
        print(f"토큰 발급 실패: {e}")
        return False

    # 2. WebSocket 연결
    print("\n[2] WebSocket 연결 중...")
    ws = KiwoomWebSocket()
    ws.on_signal = on_signal
    ws.on_connected = on_connected
    ws.on_disconnected = on_disconnected

    try:
        connected = await ws.connect()
        if not connected:
            print("WebSocket 연결 실패")
            await telegram.send_message("[오류] WebSocket 연결 실패")
            return False
    except Exception as e:
        print(f"WebSocket 연결 에러: {e}")
        await telegram.send_message(f"[오류] WebSocket 연결 에러: {e}")
        return False

    # 3. 조건식 목록 조회
    print("\n[3] 조건식 목록 조회 중...")
    try:
        conditions = await ws.get_condition_list()
        print(f"등록된 조건식 ({len(conditions)}개):")
        for cond in conditions:
            print(f"  - {cond.seq}번: {cond.name}")

        if conditions:
            condition_list = "\n".join([f"  {c.seq}번: {c.name}" for c in conditions])
            await telegram.send_message(f"[조건식 목록]\n{condition_list}")
    except Exception as e:
        print(f"조건식 목록 조회 실패: {e}")
        # 계속 진행 (목록 조회 실패해도 검색은 가능할 수 있음)

    # 4. 실시간 조건검색 시작
    print(f"\n[4] 조건식 {CONDITION_SEQ}번 실시간 검색 시작...")
    try:
        await ws.start_condition_search(CONDITION_SEQ)
        print("조건검색 시작됨")
    except Exception as e:
        print(f"조건검색 시작 실패: {e}")
        await telegram.send_message(f"[오류] 조건검색 시작 실패: {e}")
        await ws.disconnect()
        return False

    # 5. 모니터링
    print(f"\n[5] {MONITOR_SECONDS}초간 모니터링 중...")
    print("    (종목 편입/이탈 시 알림)")

    try:
        for remaining in range(MONITOR_SECONDS, 0, -10):
            print(f"    남은 시간: {remaining}초 (신호 {signal_count}건)")
            await asyncio.sleep(min(10, remaining))
    except asyncio.CancelledError:
        print("\n모니터링 취소됨")

    # 6. 정리
    print("\n[6] 테스트 종료...")
    await ws.stop_condition_search(CONDITION_SEQ)
    await ws.disconnect()

    print("\n" + "=" * 50)
    print("테스트 완료!")
    print(f"수신한 신호: {signal_count}건")
    print("=" * 50)

    await telegram.send_message(
        f"[조건식 테스트 완료]\n"
        f"조건식: {CONDITION_SEQ}번\n"
        f"수신 신호: {signal_count}건"
    )

    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단됨")
        sys.exit(0)
