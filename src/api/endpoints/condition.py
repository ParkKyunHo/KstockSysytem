"""
조건검색 관련 API 엔드포인트

WebSocket 기반 실시간 조건검색을 제공합니다.
"""

from typing import List, Optional, Callable, Awaitable

from src.api.websocket import KiwoomWebSocket, ConditionInfo, SignalEvent, SignalCallback
from src.utils.logger import get_logger


class ConditionAPI:
    """
    조건검색 API

    WebSocket을 래핑하여 조건검색 기능을 제공합니다.

    기능:
    - 조건식 목록 조회
    - 다중 조건식 실시간 모니터링
    - 매수/매도 신호 분리 콜백

    Usage:
        condition_api = ConditionAPI()
        condition_api.set_buy_signal_handler(my_buy_handler)

        await condition_api.connect()
        await condition_api.start_monitoring(["0", "1"])
    """

    def __init__(self, websocket: Optional[KiwoomWebSocket] = None):
        self._ws = websocket or KiwoomWebSocket()
        self._logger = get_logger(__name__)

        # 사용자 콜백
        self._on_buy_signal: Optional[SignalCallback] = None
        self._on_exit_signal: Optional[SignalCallback] = None

        # 내부 신호 라우팅 설정
        self._ws.on_signal = self._handle_signal

    async def connect(self) -> bool:
        """WebSocket 연결"""
        return await self._ws.connect()

    async def disconnect(self) -> None:
        """WebSocket 연결 해제"""
        await self._ws.disconnect()

    @property
    def is_connected(self) -> bool:
        """연결 상태"""
        return self._ws.is_connected

    def set_buy_signal_handler(self, handler: SignalCallback) -> None:
        """
        매수 신호 핸들러 설정

        조건식에 종목이 편입될 때 호출됩니다.

        Args:
            handler: async def handler(signal: SignalEvent) -> None
        """
        self._on_buy_signal = handler

    def set_exit_signal_handler(self, handler: SignalCallback) -> None:
        """
        이탈 신호 핸들러 설정

        조건식에서 종목이 이탈할 때 호출됩니다.

        Args:
            handler: async def handler(signal: SignalEvent) -> None
        """
        self._on_exit_signal = handler

    def set_connection_handlers(
        self,
        on_connected: Optional[Callable[[], Awaitable[None]]] = None,
        on_disconnected: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """
        연결 상태 핸들러 설정

        Args:
            on_connected: 연결 성공 시 호출
            on_disconnected: 연결 끊김 시 호출
        """
        self._ws.on_connected = on_connected
        self._ws.on_disconnected = on_disconnected

    async def _handle_signal(self, signal: SignalEvent) -> None:
        """신호를 적절한 핸들러로 라우팅"""
        if signal.is_buy_signal and self._on_buy_signal:
            await self._on_buy_signal(signal)
        elif signal.is_exit_signal and self._on_exit_signal:
            await self._on_exit_signal(signal)

    async def get_conditions(self) -> List[ConditionInfo]:
        """
        조건식 목록 조회

        참고: 조건식은 HTS(영웅문4)에서 미리 생성해야 합니다.

        Returns:
            ConditionInfo 리스트
        """
        return await self._ws.get_condition_list()

    async def start_monitoring(
        self,
        condition_seqs: List[str],
        exchange: str = "K",
    ) -> None:
        """
        다중 조건식 모니터링 시작

        Args:
            condition_seqs: 조건식 번호 리스트
            exchange: "K" KRX, "N" NXT
        """
        for seq in condition_seqs:
            await self._ws.start_condition_search(seq, exchange)
            self._logger.info(f"조건식 모니터링 시작: {seq}")

    async def stop_monitoring(self, condition_seqs: Optional[List[str]] = None) -> None:
        """
        조건식 모니터링 중지

        Args:
            condition_seqs: 중지할 조건식 번호 (None이면 전체)
        """
        seqs = condition_seqs or list(self._ws._active_conditions)
        for seq in seqs:
            await self._ws.stop_condition_search(seq)
            self._logger.info(f"조건식 모니터링 중지: {seq}")

    async def start_all_from_config(self) -> None:
        """
        설정 파일의 모든 조건식 모니터링 시작

        CONDITION_SEQS 환경변수에서 조건식 번호를 읽습니다.
        """
        from src.utils.config import get_strategy_settings

        settings = get_strategy_settings()
        condition_seqs = settings.condition_seq_list

        if not condition_seqs or condition_seqs == ["0"]:
            self._logger.warning("설정된 조건식이 없습니다. CONDITION_SEQS 확인 필요")
            return

        await self.start_monitoring(condition_seqs)
