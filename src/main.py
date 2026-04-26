"""
Ju-Do-Ju Sniper - 주도주 자동매매 시스템

키움증권 REST API를 활용한 국내 주식 자동매매 시스템입니다.

실행 방법:
    python -m src.main

주요 기능:
    - 천장 파괴 전략 (1분봉): 20분 고점 돌파 + 거래량 폭발
    - 스나이퍼 전략 (3분봉): 60선 우상향 + 개미털기 후 반등
    - 텔레그램 명령어: /start, /stop, /status, /balance, /positions
"""

import asyncio
import signal
import sys
from datetime import datetime
from typing import Optional

from src.api.client import KiwoomAPIClient
from src.api.websocket import KiwoomWebSocket
from src.core.trading_engine import TradingEngine, EngineConfig
from src.core.risk_manager import RiskConfig
from src.core.universe import UniverseConfig
from src.notification.telegram import TelegramBot
from src.notification.templates import format_help_message
from src.database.connection import init_database, close_database, get_db_manager
from src.utils.config import get_settings, get_config
from src.utils.logger import setup_logging, get_logger


class JuDoJuSniper:
    """
    Ju-Do-Ju Sniper 애플리케이션

    메인 애플리케이션 클래스로, 모든 컴포넌트를 초기화하고
    시스템을 실행합니다.

    Usage:
        app = JuDoJuSniper()
        await app.run()
    """

    def __init__(self):
        self._logger = get_logger(__name__)
        self._settings = get_settings()
        self._config = get_config()

        # 컴포넌트
        self._api_client: Optional[KiwoomAPIClient] = None
        self._websocket: Optional[KiwoomWebSocket] = None
        self._telegram: Optional[TelegramBot] = None
        self._engine: Optional[TradingEngine] = None

        # 실행 플래그
        self._running = False

    async def initialize(self) -> bool:
        """
        컴포넌트 초기화

        Returns:
            초기화 성공 여부
        """
        self._logger.info("시스템 초기화 중...")
        self._logger.info(f"환경: {self._settings.environment}")
        self._logger.info(f"모드: {'모의투자' if self._settings.is_paper_trading else '실전투자'}")

        try:
            # 0. 데이터베이스 초기화 (가장 먼저)
            db_initialized = await init_database()
            if db_initialized:
                db_manager = get_db_manager()
                db_type = "PostgreSQL (Supabase)" if db_manager.is_postgres else "SQLite"
                self._logger.info(f"데이터베이스 초기화 완료: {db_type}")
            else:
                self._logger.warning("데이터베이스 초기화 실패 - 거래 기록이 저장되지 않습니다")

            # 1. API 클라이언트 초기화
            self._api_client = KiwoomAPIClient()
            await self._api_client.__aenter__()
            self._logger.info("API 클라이언트 초기화 완료")

            # 2. WebSocket 초기화 (콜백은 TradingEngine에서 설정)
            self._websocket = KiwoomWebSocket()
            self._logger.info("WebSocket 클라이언트 초기화 완료")

            # 3. 텔레그램 봇 초기화
            self._telegram = TelegramBot()
            self._setup_telegram_handlers()
            self._logger.info("텔레그램 봇 초기화 완료")

            # 4. 거래 엔진 초기화
            engine_config = EngineConfig()
            # RiskConfig.from_settings()로 환경변수에서 모든 설정 로드
            risk_config = RiskConfig.from_settings()
            universe_config = UniverseConfig()

            self._engine = TradingEngine(
                api_client=self._api_client,
                telegram=self._telegram,
                websocket=self._websocket,  # WebSocket 연결
                config=engine_config,
                risk_config=risk_config,
                universe_config=universe_config,
            )
            self._logger.info("거래 엔진 초기화 완료")

            return True

        except Exception as e:
            self._logger.error(f"초기화 실패: {e}")
            return False

    def _setup_telegram_handlers(self) -> None:
        """텔레그램 명령어 핸들러 설정"""
        if self._telegram is None:
            return

        # /start - 거래 시작
        @self._telegram.command_handler("/start")
        async def cmd_start():
            if self._engine and not self._engine.is_running:
                await self._telegram.send_message("거래 시작 중...")
                # 백그라운드 태스크로 실행 (휴장일 대기 시 폴링 블로킹 방지)
                asyncio.create_task(self._engine.start())
            else:
                await self._telegram.send_message("이미 실행 중입니다.")

        # /stop - 거래 중지
        @self._telegram.command_handler("/stop")
        async def cmd_stop():
            if self._engine and self._engine.is_running:
                await self._telegram.send_message("거래 중지 중...")
                await self._engine.stop()
                await self._disconnect_websocket()
            else:
                await self._telegram.send_message("실행 중이 아닙니다.")

        # /status - 상태 조회
        @self._telegram.command_handler("/status")
        async def cmd_status():
            if self._engine:
                await self._telegram.send_message(self._engine.get_status_text())
            else:
                await self._telegram.send_message("엔진이 초기화되지 않았습니다.")

        # /balance - 잔고 조회 (보유종목 포함)
        @self._telegram.command_handler("/balance")
        async def cmd_balance():
            try:
                from src.api.endpoints.account import AccountAPI
                account_api = AccountAPI(self._api_client)
                balance = await account_api.get_balance()
                summary = await account_api.get_positions()

                lines = [
                    "[잔고 현황]",
                    f"예수금: {balance.deposit:,}원",
                    f"주문가능: {balance.available_amount:,}원",
                    f"D+2 예수금: {balance.d2_estimated_deposit:,}원",
                ]

                if summary.positions:
                    lines.append(f"\n[보유 종목] {len(summary.positions)}개")
                    for pos in summary.positions:
                        sign = "+" if pos.profit_loss >= 0 else ""
                        lines.append(
                            f"- {pos.stock_name}({pos.stock_code}): {pos.quantity}주 "
                            f"{sign}{pos.profit_loss_rate:.2f}%"
                        )
                    lines.append(f"\n총 평가금액: {summary.total_eval_amount:,}원")
                    sign = "+" if summary.total_profit_loss >= 0 else ""
                    lines.append(f"총 손익: {sign}{summary.total_profit_loss:,}원 ({sign}{summary.profit_loss_rate:.2f}%)")

                await self._telegram.send_message("\n".join(lines))
            except Exception as e:
                await self._telegram.send_message(f"잔고 조회 실패: {e}")

        # /positions - 보유종목 조회 (API 직접 호출)
        @self._telegram.command_handler("/positions")
        async def cmd_positions():
            try:
                from src.api.endpoints.account import AccountAPI
                account_api = AccountAPI(self._api_client)
                summary = await account_api.get_positions()

                if not summary.positions:
                    await self._telegram.send_message("[보유 종목]\n보유 종목이 없습니다.")
                    return

                lines = ["[API 보유 종목]"]
                for pos in summary.positions:
                    sign = "+" if pos.profit_loss >= 0 else ""
                    lines.append(
                        f"- {pos.stock_name}({pos.stock_code}): {pos.quantity}주 "
                        f"{sign}{pos.profit_loss_rate:.2f}% ({sign}{pos.profit_loss:,}원)"
                    )

                # 시스템 추적 포지션과 비교
                if self._engine:
                    tracked_codes = set(self._engine._position_manager.get_position_codes())
                    api_codes = {pos.stock_code for pos in summary.positions}

                    # 불일치 경고
                    not_tracked = api_codes - tracked_codes
                    ghost_positions = tracked_codes - api_codes

                    if not_tracked or ghost_positions:
                        lines.append("\n[동기화 경고]")
                        for code in not_tracked:
                            lines.append(f"  API에만 존재: {code}")
                        for code in ghost_positions:
                            lines.append(f"  시스템에만 존재: {code}")
                        lines.append("→ /start로 동기화 필요")

                await self._telegram.send_message("\n".join(lines))
            except Exception as e:
                await self._telegram.send_message(f"보유종목 조회 실패: {e}")

        # /pause - 매매 일시 중지
        @self._telegram.command_handler("/pause")
        async def cmd_pause():
            if self._engine:
                await self._engine.pause()

        # /resume - 매매 재개
        @self._telegram.command_handler("/resume")
        async def cmd_resume():
            if self._engine:
                await self._engine.resume()

        # /help - 도움말
        @self._telegram.command_handler("/help")
        async def cmd_help():
            await self._telegram.send_message(format_help_message())

        # /health - 시스템 헬스 체크
        @self._telegram.command_handler("/health")
        async def cmd_health():
            if self._engine and hasattr(self._engine, '_health_monitor') and self._engine._health_monitor:
                report = self._engine._health_monitor.get_health_report()
                await self._telegram.send_message(report)
            else:
                await self._telegram.send_message("헬스 모니터가 초기화되지 않았습니다.")

        # =========================================
        # 수동 매매 명령어
        # =========================================

        # /buy <종목코드> <금액|수량> - 수동 매수
        async def cmd_buy(chat_id: str, args: list):
            if len(args) < 2:
                await self._telegram.send_message(
                    "사용법: /buy <종목코드> <금액>\n"
                    "예: /buy 005930 500000 (50만원어치)\n"
                    "예: /buy 005930 10주 (10주)"
                )
                return
            if not self._engine:
                await self._telegram.send_message("엔진이 초기화되지 않았습니다.")
                return

            stock_code = args[0]
            amount_str = args[1]

            # 수량(주) 또는 금액 파싱
            try:
                if "주" in amount_str:
                    # 수량으로 입력된 경우 -> 금액으로 변환 필요
                    quantity = int(amount_str.replace("주", "").replace(",", ""))
                    # 현재가 조회
                    from src.api.endpoints.market import MarketAPI
                    market_api = MarketAPI(self._api_client)
                    current_price = await market_api.get_current_price(stock_code)
                    if not current_price:
                        await self._telegram.send_message("현재가 조회 실패")
                        return
                    amount = quantity * current_price
                elif amount_str == "전액":
                    from src.api.endpoints.account import AccountAPI
                    account_api = AccountAPI(self._api_client)
                    balance = await account_api.get_balance()
                    amount = balance.available_amount
                else:
                    amount = int(amount_str.replace(",", ""))
            except ValueError:
                await self._telegram.send_message("금액/수량 형식이 잘못되었습니다.")
                return

            success, message = await self._engine.execute_manual_buy(stock_code, amount)
            await self._telegram.send_message(message)

        self._telegram.register_command("buy", cmd_buy)

        # /sell <종목코드> <전량|비율|수량> - 수동 매도
        async def cmd_sell(chat_id: str, args: list):
            if len(args) < 2:
                await self._telegram.send_message(
                    "사용법: /sell <종목코드> <전량|비율|수량>\n"
                    "예: /sell 005930 전량\n"
                    "예: /sell 005930 50%\n"
                    "예: /sell 005930 30주"
                )
                return
            if not self._engine:
                await self._telegram.send_message("엔진이 초기화되지 않았습니다.")
                return

            stock_code = args[0]
            amount_str = args[1]

            # 포지션 조회
            position = self._engine._position_manager.get_position(stock_code)
            if not position:
                await self._telegram.send_message(f"{stock_code} 보유 포지션이 없습니다.")
                return

            # 수량 파싱
            try:
                if amount_str == "전량":
                    quantity = position.quantity
                elif "%" in amount_str:
                    percent = int(amount_str.replace("%", ""))
                    quantity = int(position.quantity * percent / 100)
                elif "주" in amount_str:
                    quantity = int(amount_str.replace("주", "").replace(",", ""))
                else:
                    quantity = int(amount_str.replace(",", ""))
            except ValueError:
                await self._telegram.send_message("수량 형식이 잘못되었습니다.")
                return

            if quantity < 1:
                await self._telegram.send_message("매도 수량은 1주 이상이어야 합니다.")
                return

            success, message = await self._engine.execute_manual_sell(stock_code, quantity)
            await self._telegram.send_message(message)

        self._telegram.register_command("sell", cmd_sell)

        # /substatus - 조건검색 구독 상태 확인
        async def cmd_substatus(text: str, args: list) -> None:
            if self._engine and self._engine._subscription_manager:
                status_text = self._engine._subscription_manager.get_status_text()
                await self._telegram.send_message(status_text)
            else:
                await self._telegram.send_message(
                    "조건검색 구독 상태: 대기 중\n"
                    "(장 시작 후 초기화됩니다)"
                )

        self._telegram.register_command("substatus", cmd_substatus)

        # /subscribe - 조건검색 수동 재구독 (WebSocket 재연결 포함)
        async def cmd_subscribe(text: str, args: list) -> None:
            """조건검색 수동 재구독 (WebSocket 재연결로 HTS 조건식 변경 반영)"""
            if not self._engine or not self._engine._subscription_manager:
                await self._telegram.send_message(
                    "시스템이 초기화되지 않았습니다.\n"
                    "/start로 시스템을 시작하세요."
                )
                return

            sm = self._engine._subscription_manager
            ws = self._websocket  # WebSocket 인스턴스

            subscriptions = sm.get_status()

            if not subscriptions:
                await self._telegram.send_message(
                    "등록된 조건검색이 없습니다.\n"
                    "/start로 시스템을 시작하세요."
                )
                return

            await self._telegram.send_message(
                f"조건검색 재구독 시작...\n"
                f"(WebSocket 재연결 포함, {len(subscriptions)}개 조건식)"
            )

            # 1. WebSocket 재연결 (HTS 조건식 변경 반영)
            try:
                await ws.disconnect()
                await asyncio.sleep(1.0)  # 서버 정리 대기
                await ws.connect()
                await asyncio.sleep(1.0)  # 연결 안정화 대기
            except Exception as e:
                await self._telegram.send_message(f"WebSocket 재연결 실패: {e}")
                return

            # 2. 조건식 목록 조회 (CNSRLST) - 필수!
            # 시작 시와 동일하게 CNSRLST를 먼저 호출해야 CNSRREQ 응답이 옴
            try:
                condition_list = await ws.get_condition_list()
                if condition_list:
                    await self._telegram.send_message(
                        f"조건식 목록 조회 성공: {len(condition_list)}개"
                    )
                else:
                    await self._telegram.send_message(
                        "조건식 목록 조회 실패 (타임아웃)\n"
                        "조건검색 구독이 실패할 수 있습니다."
                    )
            except Exception as e:
                await self._telegram.send_message(f"조건식 목록 조회 에러: {e}")

            # 3. 조건검색 재구독
            results = []
            for seq, info in subscriptions.items():
                info.retry_count = 0  # 재시도 카운트 초기화
                success = await sm._subscribe_with_retry(info)
                status = "성공" if success else "실패"
                results.append(f"  #{seq}: {status}")

            await self._telegram.send_message("\n".join(results))
            await self._telegram.send_message(sm.get_status_text())

        self._telegram.register_command("subscribe", cmd_subscribe)

        # /wsdiag - WebSocket 진단
        async def cmd_wsdiag(text: str, args: list) -> None:
            """WebSocket 연결 상태 진단"""
            lines = ["[WebSocket 진단]"]

            ws = self._websocket if hasattr(self, "_websocket") else None
            if ws:
                lines.append(f"연결: {'연결됨' if ws.is_connected else '미연결'}")
                lines.append(f"활성 조건식: {ws._active_conditions or '없음'}")
                lines.append(f"구독 종목: {len(ws._subscribed_stocks) if hasattr(ws, '_subscribed_stocks') else 0}개")
            else:
                lines.append("WebSocket: 미초기화")

            if self._engine and self._engine._subscription_manager:
                sm = self._engine._subscription_manager
                lines.append("")
                lines.append("[구독 상태]")
                for seq, info in sm.get_status().items():
                    purpose = sm._get_purpose_name(info.purpose)
                    lines.append(f"  #{seq} ({purpose}): {info.state.value}")
                    if info.last_error:
                        lines.append(f"    에러: {info.last_error}")
                    if info.last_signal_time:
                        elapsed = (datetime.now() - info.last_signal_time).total_seconds() / 60
                        lines.append(f"    마지막 신호: {int(elapsed)}분 전")

            await self._telegram.send_message("\n".join(lines))

        self._telegram.register_command("wsdiag", cmd_wsdiag)

        # =========================================
        # 동적 설정 변경 명령어
        # =========================================

        # /ratio [비중%] - 매수 비중 조회/변경
        async def cmd_ratio(text: str, args: list) -> None:
            if not self._engine:
                await self._telegram.send_message("엔진이 초기화되지 않았습니다.")
                return

            risk_settings = self._engine._risk_settings

            # 인자 없으면 현재 설정 조회
            if not args:
                current_ratio = risk_settings.buy_amount_ratio * 100
                await self._telegram.send_message(
                    f"현재 매수 비중: {current_ratio:.1f}%\n\n"
                    f"변경 방법: /ratio 5 (5%로 변경)\n"
                    f"범위: 1% ~ 20%"
                )
                return

            try:
                new_ratio_pct = float(args[0])
                new_ratio = new_ratio_pct / 100

                # 범위 검증 (1% ~ 20%)
                if not 0.01 <= new_ratio <= 0.20:
                    await self._telegram.send_message(
                        "비중은 1% ~ 20% 범위에서 설정 가능합니다."
                    )
                    return

                # 설정 변경
                old_ratio = risk_settings.buy_amount_ratio
                risk_settings.buy_amount_ratio = new_ratio

                await self._telegram.send_message(
                    f"매수 비중 변경 완료\n\n"
                    f"이전: {old_ratio * 100:.1f}%\n"
                    f"현재: {new_ratio * 100:.1f}%\n\n"
                    f"(기존 포지션에는 영향 없음)"
                )
                self._logger.info(
                    f"매수 비중 변경: {old_ratio * 100:.1f}% -> {new_ratio * 100:.1f}%"
                )

            except ValueError:
                await self._telegram.send_message(
                    "올바른 숫자를 입력하세요.\n예: /ratio 5"
                )

        self._telegram.register_command("ratio", cmd_ratio)

        # /ignore <종목코드> - 시스템 관리에서 종목 제외
        async def cmd_ignore(text: str, args: list) -> None:
            if not self._engine:
                await self._telegram.send_message("엔진이 초기화되지 않았습니다.")
                return

            if not args:
                # 현재 ignore 목록 조회
                ignore_list = self._engine.get_ignore_stocks()
                if not ignore_list:
                    await self._telegram.send_message(
                        "시스템 관리 제외 종목 없음\n\n"
                        "사용법: /ignore 005930"
                    )
                else:
                    codes_str = ", ".join(sorted(ignore_list))
                    await self._telegram.send_message(
                        f"시스템 관리 제외 종목:\n{codes_str}\n\n"
                        f"해제: /unignore 종목코드"
                    )
                return

            stock_code = args[0].strip()
            if len(stock_code) != 6 or not stock_code.isdigit():
                await self._telegram.send_message("올바른 종목코드를 입력하세요. (6자리)")
                return

            # ignore 목록에 추가
            self._engine.add_ignore_stock(stock_code)

            await self._telegram.send_message(
                f"{stock_code} 시스템 관리 제외됨\n\n"
                f"이 종목은 자동 청산 대상에서 제외됩니다.\n"
                f"해제: /unignore {stock_code}"
            )
            self._logger.info(f"종목 ignore 추가: {stock_code}")

        self._telegram.register_command("ignore", cmd_ignore)

        # /unignore <종목코드> - 시스템 관리 제외 해제
        async def cmd_unignore(text: str, args: list) -> None:
            if not self._engine:
                await self._telegram.send_message("엔진이 초기화되지 않았습니다.")
                return

            if not args:
                await self._telegram.send_message(
                    "사용법: /unignore 005930\n\n"
                    "제외 목록 확인: /ignore"
                )
                return

            stock_code = args[0].strip()
            ignore_list = self._engine.get_ignore_stocks()

            if stock_code not in ignore_list:
                await self._telegram.send_message(
                    f"{stock_code}는 제외 목록에 없습니다."
                )
                return

            self._engine.remove_ignore_stock(stock_code)

            await self._telegram.send_message(
                f"{stock_code} 시스템 관리 재개\n\n"
                f"이 종목은 다시 자동 청산 대상입니다."
            )
            self._logger.info(f"종목 ignore 해제: {stock_code}")

        self._telegram.register_command("unignore", cmd_unignore)

    async def _connect_websocket(self) -> bool:
        """WebSocket 연결 및 조건식 검색 시작"""
        if self._websocket is None:
            return False

        try:
            connected = await self._websocket.connect()
            if connected:
                self._logger.info("WebSocket 연결 성공")

                # 조건식 검색 시작 (.env의 CONDITION_SEQS 사용)
                condition_seqs = get_config().strategy.condition_seq_list
                if condition_seqs:
                    for seq in condition_seqs:
                        await self._websocket.start_condition_search(seq)
                        self._logger.info(f"조건식 {seq}번 실시간 검색 시작")
                else:
                    self._logger.warning("설정된 조건식이 없습니다 (CONDITION_SEQS)")

            return connected
        except Exception as e:
            self._logger.error(f"WebSocket 연결 실패: {e}")
            return False

    async def _disconnect_websocket(self) -> None:
        """WebSocket 연결 해제"""
        if self._websocket:
            # 활성 조건식 검색 중지
            condition_seqs = get_config().strategy.condition_seq_list
            if condition_seqs:
                for seq in condition_seqs:
                    await self._websocket.stop_condition_search(seq)
            await self._websocket.disconnect()

    async def run(self) -> None:
        """메인 실행 루프"""
        self._logger.info("Ju-Do-Ju Sniper 시작")

        # 초기화
        if not await self.initialize():
            self._logger.error("초기화 실패, 종료합니다.")
            return

        self._running = True

        try:
            # 시작 메시지
            await self._telegram.send_message(
                "[Ju-Do-Ju Sniper]\n"
                f"모드: {'모의투자' if self._settings.is_paper_trading else '실전투자'}\n"
                "시스템이 준비되었습니다.\n\n"
                "/start - 거래 시작\n"
                "/help - 명령어 도움말"
            )

            # 텔레그램 폴링 시작
            await self._telegram.start_polling()

            # 메인 루프 (무한 대기)
            while self._running:
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            self._logger.info("종료 신호 수신")
        except Exception as e:
            self._logger.error(f"실행 중 에러: {e}")
        finally:
            await self.shutdown()

    async def shutdown(self) -> None:
        """종료 처리"""
        self._logger.info("시스템 종료 중...")
        self._running = False

        # 엔진 중지
        if self._engine:
            await self._engine.stop()

        # WebSocket 해제
        await self._disconnect_websocket()

        # 텔레그램 폴링 중지
        if self._telegram:
            await self._telegram.stop_polling()

        # API 클라이언트 종료
        if self._api_client:
            await self._api_client.__aexit__(None, None, None)

        # 데이터베이스 연결 종료
        await close_database()

        self._logger.info("시스템 종료 완료")


async def main():
    """메인 함수"""
    # 로깅 설정
    setup_logging()
    logger = get_logger(__name__)

    # 앱 생성 및 실행
    app = JuDoJuSniper()

    # 종료 시그널 핸들러
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("종료 시그널 수신")
        app._running = False

    # Windows에서는 SIGINT만 지원
    if sys.platform != "win32":
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, signal_handler)
    else:
        signal.signal(signal.SIGINT, lambda s, f: signal_handler())

    # 실행
    await app.run()


if __name__ == "__main__":
    asyncio.run(main())
