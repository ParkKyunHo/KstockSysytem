"""
조건검색 간단 테스트 스크립트

WebSocket 연결 -> 조건검색 구독 -> 초기 종목 출력 -> 실시간 신호 대기
텔레그램 알림 없이 터미널 출력만
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


CONDITION_SEQ = "0"  # 테스트할 조건식 번호
MONITOR_SECONDS = 30  # 모니터링 시간 (초)

signal_count = 0


async def on_signal(signal: SignalEvent):
    """조건식 신호 수신 콜백"""
    global signal_count
    signal_count += 1

    signal_type = "편입" if signal.is_buy_signal else "이탈"
    print(f"    [{signal_type}] {signal.stock_name} ({signal.stock_code}) {signal.timestamp}")


async def main():
    """메인 테스트 함수"""
    global signal_count

    setup_logging()
    logger = get_logger(__name__)

    settings = get_settings()

    print("\n" + "=" * 50)
    print("조건검색 테스트 (Simple)")
    print("=" * 50)
    print(f"환경: {settings.environment}")
    print(f"모드: {'모의투자' if settings.is_paper_trading else '실전투자'}")
    print(f"조건식: {CONDITION_SEQ}번")
    print(f"모니터링: {MONITOR_SECONDS}초")
    print("=" * 50)

    # 1. 토큰 발급
    print("\n[1] 토큰 발급 중...")
    token_manager = get_token_manager()
    try:
        token = await token_manager.get_token()
        print(f"    토큰 발급 성공: {token[:20]}...")
    except Exception as e:
        print(f"    토큰 발급 실패: {e}")
        return False

    # 2. WebSocket 연결
    print("\n[2] WebSocket 연결 중...")
    ws = KiwoomWebSocket()
    ws.on_signal = on_signal

    try:
        connected = await ws.connect()
        if not connected:
            print("    WebSocket 연결 실패")
            return False
        print("    WebSocket 연결 성공")
    except Exception as e:
        print(f"    WebSocket 연결 에러: {e}")
        return False

    # 3. 조건식 목록 조회
    print("\n[3] 조건식 목록 조회 중...")
    try:
        conditions = await ws.get_condition_list()
        print(f"    등록된 조건식 ({len(conditions)}개):")
        for cond in conditions:
            marker = " <-- 테스트 대상" if cond.seq == CONDITION_SEQ else ""
            print(f"      - {cond.seq}번: {cond.name}{marker}")
    except Exception as e:
        print(f"    조건식 목록 조회 실패: {e}")
        # 계속 진행

    # 4. 조건검색 구독
    print(f"\n[4] 조건식 {CONDITION_SEQ}번 구독 중...")
    try:
        success = await ws.start_condition_search(CONDITION_SEQ)
        if not success:
            print("    구독 실패 (타임아웃 또는 거부)")
            await ws.disconnect()
            return False

        print("    구독 성공!")

        # 초기 매칭 종목 출력 (내부 변수 접근)
        initial_stocks = ws._cnsrreq_response.get("data", []) if ws._cnsrreq_response else []
        print(f"\n    [초기 매칭 종목] {len(initial_stocks)}개")
        print("    " + "-" * 40)

        if initial_stocks:
            for i, stock in enumerate(initial_stocks, 1):
                jmcode = stock.get("jmcode", "")
                # A 접두어 제거하여 표시
                code = jmcode[1:] if jmcode.startswith("A") else jmcode
                print(f"    {i:3d}. {code}")
        else:
            print("    (매칭 종목 없음)")

        print("    " + "-" * 40)

    except Exception as e:
        print(f"    구독 에러: {e}")
        await ws.disconnect()
        return False

    # 5. 실시간 신호 대기
    print(f"\n[5] {MONITOR_SECONDS}초간 실시간 신호 대기...")
    print("    (Ctrl+C로 조기 종료)")

    try:
        for remaining in range(MONITOR_SECONDS, 0, -5):
            print(f"    남은 시간: {remaining}초 (신호 {signal_count}건)")
            await asyncio.sleep(min(5, remaining))
    except asyncio.CancelledError:
        print("\n    모니터링 취소됨")

    # 6. 정리
    print("\n[6] 테스트 종료...")
    await ws.stop_condition_search(CONDITION_SEQ)
    await ws.disconnect()

    print("\n" + "=" * 50)
    print("테스트 완료!")
    print(f"수신한 신호: {signal_count}건")
    print("=" * 50)

    return True


if __name__ == "__main__":
    try:
        success = asyncio.run(main())
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\n사용자에 의해 중단됨")
        sys.exit(0)
