"""
WebSocket 관리 모듈

TradingEngine에서 추출된 WebSocket 연결/구독/이벤트 관리.
Phase 4-A: ~250줄 절감.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Callable, Awaitable, Set, List
import logging

from src.api.websocket import KiwoomWebSocket, TickData
from src.core.candle_builder import Tick
from src.core.subscription_manager import SubscriptionManager, SubscriptionPurpose


@dataclass
class WebSocketCallbacks:
    """WebSocketManager → TradingEngine 콜백"""

    on_tick: Callable[[Tick], Awaitable[None]]
    sync_positions: Callable[[], Awaitable[None]]
    initialize_trailing_stops: Callable[[], Awaitable[None]]
    get_universe_codes: Callable[[], Set[str]]
    get_all_position_codes: Callable[[], Set[str]]
    get_position_count: Callable[[], int]
    get_engine_state: Callable[[], str]
    set_engine_paused: Callable[[], None]


class WebSocketManager:
    """
    WebSocket 연결, 조건검색 구독, 이벤트 핸들링을 담당.

    TradingEngine의 WS 관련 7개 메서드를 캡슐화합니다.
    on_signal 콜백은 TradingEngine이 직접 등록합니다.
    """

    def __init__(
        self,
        websocket: Optional[KiwoomWebSocket],
        logger: logging.Logger,
        telegram,
        risk_settings,
        subscription_manager: Optional[SubscriptionManager],
        callbacks: WebSocketCallbacks,
    ):
        self._websocket = websocket
        self._logger = logger
        self._telegram = telegram
        self._risk_settings = risk_settings
        self._subscription_manager = subscription_manager
        self._callbacks = callbacks
        self._ticks_received: int = 0

    @property
    def ticks_received(self) -> int:
        return self._ticks_received

    # =========================================
    # 연결 및 구독
    # =========================================

    async def connect(self) -> None:
        """WebSocket 연결 및 조건검색 구독"""
        if not self._websocket:
            self._logger.warning("WebSocket 클라이언트가 설정되지 않음")
            return

        try:
            self._logger.info("[WS] WebSocket 연결 시도...")
            connected = await self._websocket.connect()
            self._logger.info(
                f"[WS] WebSocket 연결 결과: {connected}, "
                f"is_connected={self._websocket.is_connected}"
            )
            if not connected:
                self._logger.error("[WS] WebSocket 연결 실패")
                return

            # 유니버스 종목 + 보유 종목의 실시간 체결가 구독
            stock_codes = set(self._callbacks.get_universe_codes())
            stock_codes.update(self._callbacks.get_all_position_codes())

            # PRD v3.0: WebSocket REGSUB 에러로 REST 폴링 사용
            if stock_codes:
                self._logger.info(
                    f"시세 수신 대상: {len(stock_codes)}개 종목 (REST 폴링)"
                )

            # PRD v3.2.2: 거래 모드에 따른 조건검색 분기
            from src.utils.config import TradingMode

            trading_mode = self._risk_settings.trading_mode
            self._logger.info(
                f"[거래모드] {trading_mode.value} | "
                f"auto_universe={self._risk_settings.auto_universe_enabled}, "
                f"seq={self._risk_settings.auto_universe_condition_seq}"
            )

            if trading_mode == TradingMode.MANUAL_ONLY:
                atr_alert_seq = str(self._risk_settings.atr_alert_condition_seq)
                self._logger.info(
                    f"[거래모드] MANUAL_ONLY - Auto-Universe 비활성화, "
                    f"ATR 알림(seq={atr_alert_seq}) 활성화"
                )
                if await self._start_condition_search_with_validation(atr_alert_seq):
                    if self._subscription_manager:
                        self._subscription_manager.register_existing(
                            atr_alert_seq, SubscriptionPurpose.ATR_ALERT
                        )
            elif self._risk_settings.auto_universe_enabled:
                condition_seq = str(
                    self._risk_settings.auto_universe_condition_seq
                )
                atr_alert_seq = str(self._risk_settings.atr_alert_condition_seq)
                if condition_seq != atr_alert_seq:
                    if await self._start_condition_search_with_validation(
                        condition_seq
                    ):
                        if self._subscription_manager:
                            self._subscription_manager.register_existing(
                                condition_seq, SubscriptionPurpose.AUTO_UNIVERSE
                            )
                    if await self._start_condition_search_with_validation(
                        atr_alert_seq
                    ):
                        if self._subscription_manager:
                            self._subscription_manager.register_existing(
                                atr_alert_seq, SubscriptionPurpose.ATR_ALERT
                            )
                else:
                    if await self._start_condition_search_with_validation(
                        condition_seq
                    ):
                        if self._subscription_manager:
                            self._subscription_manager.register_existing(
                                condition_seq, SubscriptionPurpose.AUTO_UNIVERSE
                            )
            else:
                self._logger.warning(
                    "[V7.0] Auto-Universe 비활성화됨 - 조건검색 구독 건너뜀"
                )

        except Exception as e:
            self._logger.error(f"WebSocket 연결/구독 에러: {e}", exc_info=True)

    async def _start_condition_search_with_validation(
        self, condition_seq: str
    ) -> bool:
        """
        조건검색 구독 시작 (조건식 목록 조회 및 유효성 검증 포함)

        Bug 5 수정: HTS 조건검색식이 API에서 접근 가능한지 먼저 확인
        """
        self._logger.info(f"[V7.0] 조건검색 시작: seq={condition_seq}")

        try:
            self._logger.info("[V7.0] 조건식 목록 조회 중...")
            condition_list = await self._websocket.get_condition_list()

            if condition_list:
                condition_names = {c.seq: c.name for c in condition_list}
                self._logger.info(
                    f"[V7.0] API 접근 가능한 조건식: {len(condition_list)}개",
                    conditions=condition_names,
                )
            else:
                self._logger.warning(
                    "[V7.0] 조건식 목록 조회 결과 없음 (타임아웃 또는 빈 목록)"
                )

            target_exists = condition_list and any(
                c.seq == condition_seq for c in condition_list
            )
            if condition_list and not target_exists:
                available_seqs = [c.seq for c in condition_list]
                error_msg = (
                    f"[V7.0] 조건식 {condition_seq}번이 API에서 조회되지 않음. "
                    f"사용 가능한 조건식: {available_seqs}. "
                    "HTS에서 '서버 전송' 또는 '조건식 동기화'가 필요할 수 있습니다."
                )
                self._logger.error(error_msg)
                await self._send_telegram_alert(
                    f"Auto-Universe 조건검색 실패\n\n"
                    f"조건식 #{condition_seq}이 API에서 접근 불가.\n"
                    f"사용 가능: {available_seqs}\n\n"
                    f"HTS에서 조건식 서버 저장 확인 필요"
                )
                return False

            success = await self._websocket.start_condition_search(
                seq=condition_seq
            )

            if success:
                self._logger.info(
                    f"[V7.0] 조건검색 {condition_seq}번 활성화됨"
                )
                return True
            else:
                self._logger.error(
                    f"[V7.0] 조건검색 {condition_seq}번 구독 실패 "
                    "(서버 응답 없음 또는 거부)"
                )
                await self._send_telegram_alert(
                    f"Auto-Universe 조건검색 실패\n\n"
                    f"조건식 #{condition_seq} 구독 응답 없음.\n"
                    f"키움 서버에서 조건식을 인식하지 못했습니다.\n\n"
                    f"HTS에서 조건식 #{condition_seq} 확인 필요"
                )
                return False

        except Exception as e:
            self._logger.error(
                f"[V7.0] 조건검색 시작 에러: {e}", exc_info=True
            )
            await self._send_telegram_alert(
                f"Auto-Universe 조건검색 에러\n\n{str(e)}"
            )
            return False

    # =========================================
    # WebSocket 이벤트 핸들러
    # =========================================

    async def on_tick(self, tick_data: TickData) -> None:
        """WebSocket 실시간 체결가 수신 처리"""
        self._ticks_received += 1

        try:
            if tick_data.time:
                time_obj = datetime.strptime(tick_data.time, "%H%M%S").time()
                timestamp = datetime.combine(datetime.now().date(), time_obj)
            else:
                timestamp = datetime.now()
        except ValueError:
            timestamp = datetime.now()

        tick = Tick(
            stock_code=tick_data.stock_code,
            price=tick_data.price,
            volume=tick_data.volume,
            timestamp=timestamp,
        )

        await self._callbacks.on_tick(tick)

    async def on_connected(self) -> None:
        """WebSocket 연결 성공 콜백"""
        self._logger.info("WebSocket 연결됨 - 실시간 데이터 수신 시작")

        stock_codes = set(self._callbacks.get_universe_codes())
        stock_codes.update(self._callbacks.get_all_position_codes())

        # PRD v3.0: WebSocket REGSUB 에러로 REST 폴링 사용
        if stock_codes:
            self._logger.debug(
                f"재연결 후 시세 수신 대상: {len(stock_codes)}개 종목"
            )

    async def on_disconnected(self) -> None:
        """WebSocket 연결 해제 콜백"""
        if (
            hasattr(self._websocket, "_is_reconnecting")
            and self._websocket._is_reconnecting
        ):
            self._logger.debug("[WS] 재연결 진행 중 - 중복 알림 스킵")
            return

        self._logger.warning("WebSocket 연결 끊김 - 재연결 시도 중...")
        await self._telegram.send_message(
            "[경고] WebSocket 연결 끊김 - 자동 재연결 중"
        )

    async def on_reconnected(self) -> None:
        """WebSocket 재연결 성공 콜백"""
        self._logger.info("WebSocket 재연결 성공 - 복구 작업 시작")

        # 1. SubscriptionManager가 조건검색 재구독 처리
        if self._subscription_manager:
            try:
                await self._subscription_manager.on_websocket_reconnected()
            except Exception as e:
                self._logger.error(f"재연결 후 조건검색 재구독 실패: {e}")
                await self._telegram.send_message(
                    f"[경고] 조건검색 재구독 실패: {e}"
                )

        # 2. 포지션 동기화
        try:
            await self._callbacks.sync_positions()
            self._logger.info("재연결 후 포지션 동기화 완료")
        except Exception as e:
            self._logger.error(f"재연결 후 포지션 동기화 실패: {e}")
            await self._telegram.send_message(
                f"[경고] 포지션 동기화 실패: {e}"
            )

        # 3. 트레일링 스탑 재초기화
        try:
            await self._callbacks.initialize_trailing_stops()
            await self._telegram.send_message(
                f"[알림] 재연결 복구 완료\n"
                f"보유 종목: {self._callbacks.get_position_count()}개"
            )
        except Exception as e:
            self._logger.error(
                f"재연결 후 트레일링 스탑 초기화 실패: {e}"
            )

    async def on_reconnect_failed(self, attempts: int) -> None:
        """WebSocket 재연결 실패 콜백 (최대 시도 횟수 초과)"""
        self._logger.error(
            f"WebSocket 재연결 실패 - {attempts}회 시도 후 포기"
        )

        # 매매 일시 중지
        if self._callbacks.get_engine_state() == "RUNNING":
            self._callbacks.set_engine_paused()
            self._logger.warning("매매 자동 일시 중지됨")

        await self._telegram.send_message(
            f"[긴급] WebSocket 재연결 실패\n"
            f"시도 횟수: {attempts}회\n"
            f"매매 상태: 일시 중지됨\n\n"
            f"조치:\n"
            f"1. 네트워크 연결 확인\n"
            f"2. /stop 후 /start로 재시작\n"
            f"3. 보유 포지션 수동 확인 필요"
        )

    # =========================================
    # 내부 유틸리티
    # =========================================

    async def _send_telegram_alert(self, message: str) -> None:
        """텔레그램 알림 전송 (에러 무시)"""
        try:
            if self._telegram:
                await self._telegram.send_message(message)
        except Exception as e:
            self._logger.warning(f"텔레그램 알림 전송 실패: {e}")
