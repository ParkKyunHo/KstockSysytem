"""
키움증권 WebSocket 클라이언트

실시간 조건검색 및 시세 데이터를 수신합니다.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Callable, Awaitable, Set
import asyncio
import json
import socket
from datetime import datetime, time as dtime

import websockets
from websockets.exceptions import ConnectionClosed

from src.api.auth import TokenManager, get_token_manager
from src.utils.config import get_config, AppConfig
from src.utils.logger import get_logger
from src.utils.exceptions import (
    WebSocketConnectionError,
    WebSocketDisconnectedError,
)


class WSMessageType(str, Enum):
    """WebSocket 메시지 타입"""
    LOGIN = "LOGIN"
    PING = "PING"
    CNSRLST = "CNSRLST"       # 조건식 목록
    CNSRREQ = "CNSRREQ"       # 조건검색 (1회 또는 실시간)
    CNSRCLR = "CNSRCLR"       # 실시간 조건검색 해제 (API 문서 기준)
    REAL = "REAL"             # 실시간 데이터
    REGSUB = "REGSUB"         # 실시간 시세 등록 (레거시 - 미지원)
    UNREGSUB = "UNREGSUB"     # 실시간 시세 해제 (레거시 - 미지원)
    REG = "REG"               # V6.2-M: 실시간 시세 등록 (신규)
    UNREG = "UNREG"           # V6.2-M: 실시간 시세 해제 (신규)


class RealDataType(str, Enum):
    """실시간 데이터 타입"""
    TICK = "S3_"              # 주식 체결가 (틱)
    QUOTE = "S4_"             # 주식 호가
    PROGRAM = "PG_"           # 프로그램 매매


@dataclass
class TickData:
    """실시간 체결 데이터 (틱)"""
    stock_code: str           # 종목코드
    stock_name: str           # 종목명
    time: str                 # 체결시간 (HHMMSS)
    price: int                # 현재가
    change: int               # 전일대비
    change_rate: float        # 등락률
    volume: int               # 체결량
    total_volume: int         # 누적거래량
    total_amount: int         # 누적거래대금

    @classmethod
    def from_ws_data(cls, data: dict) -> "TickData":
        """WebSocket 데이터에서 TickData 생성"""
        raw_code = data.get("9001", "")
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
        return cls(
            stock_code=stock_code,
            stock_name=data.get("9002", ""),
            time=data.get("20", ""),           # 체결시간
            price=abs(int(data.get("10", 0))), # 현재가 (부호 제거)
            change=int(data.get("11", 0)),     # 전일대비
            change_rate=float(data.get("12", 0)) / 100,  # 등락률
            volume=int(data.get("15", 0)),     # 체결량
            total_volume=int(data.get("13", 0)),  # 누적거래량
            total_amount=int(data.get("14", 0)),  # 누적거래대금
        )


@dataclass
class ConditionInfo:
    """조건식 정보"""
    seq: str
    name: str


@dataclass
class SignalEvent:
    """실시간 신호 이벤트"""
    stock_code: str
    stock_name: str
    signal_type: str  # "I" = 매수(편입), "D" = 매도(이탈) - API 문서 기준
    condition_seq: str
    timestamp: str

    @property
    def is_buy_signal(self) -> bool:
        """매수 신호 여부 (종목 편입)"""
        return self.signal_type == "I"

    @property
    def is_exit_signal(self) -> bool:
        """매도 신호 여부 (종목 이탈) - API 문서: D=매도"""
        return self.signal_type == "D"


# 콜백 타입 별칭
SignalCallback = Callable[[SignalEvent], Awaitable[None]]
TickCallback = Callable[[TickData], Awaitable[None]]
ConnectionCallback = Callable[[], Awaitable[None]]
ReconnectFailedCallback = Callable[[int], Awaitable[None]]  # 실패 횟수 전달


class KiwoomWebSocket:
    """
    키움증권 WebSocket 클라이언트

    기능:
    - 자동 재연결 (2단계: 빠른 재연결 + 느린 무한 재연결)
    - PING/PONG 처리
    - 조건검색 (단일/실시간)
    - 신호 콜백

    재연결 전략:
    - Phase 1 (빠른 재연결): 5회, 지수 백오프 (2초 → 3초 → 4.5초 ...)
    - Phase 2 (느린 재연결): 무한, 5분 간격 (장시간 서버 점검 대응)

    Usage:
        ws = KiwoomWebSocket()
        ws.on_signal = my_signal_handler
        await ws.connect()
        await ws.start_condition_search("000")
    """

    WEBSOCKET_PATH = "/api/dostk/websocket"

    # Phase 1: 빠른 재연결 (짧은 장애 대응)
    FAST_RECONNECT_ATTEMPTS = 5
    RECONNECT_BASE_DELAY = 2.0

    # Phase 2: 느린 재연결 (장시간 서버 점검 대응)
    SLOW_RECONNECT_INTERVAL = 300.0  # 5분

    # Application-Level Heartbeat (좀비 연결 감지)
    HEARTBEAT_INTERVAL = 60    # 60초마다 세션 유효성 검증
    HEARTBEAT_TIMEOUT = 30     # 응답 대기 30초 (장 시작 API 부하 대응)
    MAX_HEARTBEAT_FAILURES = 3 # 3회 연속 실패 시 강제 재연결

    # [2026-01-08] 클라이언트 Keepalive PING (서버 유휴 타임아웃 방지)
    CLIENT_PING_INTERVAL = 20  # 20초마다 클라이언트 PING 전송

    # [2026-01-08] 장 시작 시간대 Heartbeat 완화
    MARKET_OPENING_START = dtime(9, 0, 0)   # 장 시작
    MARKET_OPENING_END = dtime(9, 5, 0)     # 개장 과부하 종료
    MARKET_OPENING_EXTENDED = dtime(9, 30, 0)  # 확장 완화 구간

    def _is_market_opening_period(self) -> bool:
        """장 시작 5분간 (09:00~09:05) 여부 확인"""
        now = datetime.now().time()
        return self.MARKET_OPENING_START <= now < self.MARKET_OPENING_END

    def _get_heartbeat_threshold(self) -> int:
        """장 시작 시간대에는 더 관대한 임계치 적용"""
        now = datetime.now().time()
        if self.MARKET_OPENING_START <= now < self.MARKET_OPENING_EXTENDED:
            return 5  # 장 시작 30분간: 5회
        return self.MAX_HEARTBEAT_FAILURES  # 평상시: 3회

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        token_manager: Optional[TokenManager] = None,
    ):
        self._config = config or get_config()
        self._token_manager = token_manager or get_token_manager()
        self._logger = get_logger(__name__)

        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._connected = False
        self._keep_running = True

        self._receive_task: Optional[asyncio.Task] = None
        self._reconnect_attempts = 0

        # Heartbeat (좀비 연결 감지)
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._heartbeat_failures = 0

        # [2026-01-08] 클라이언트 Keepalive PING
        self._client_ping_task: Optional[asyncio.Task] = None

        # 콜백
        self.on_signal: Optional[SignalCallback] = None
        self.on_tick: Optional[TickCallback] = None
        self.on_connected: Optional[ConnectionCallback] = None
        self.on_disconnected: Optional[ConnectionCallback] = None
        self.on_reconnected: Optional[ConnectionCallback] = None  # 재연결 성공 시
        self.on_reconnect_failed: Optional[ReconnectFailedCallback] = None  # 재연결 실패 시

        # 활성 조건식 구독
        self._active_conditions: Set[str] = set()

        # 실시간 시세 구독 종목
        self._subscribed_stocks: Set[str] = set()
        # M-002 FIX: REG 요청 대기 중인 종목 (응답 검증용)
        self._pending_reg_stocks: Set[str] = set()

        # 조건식 목록 응답 대기용
        self._condition_list_event: asyncio.Event = asyncio.Event()
        self._condition_list_data: list = []

        # 조건검색 구독 응답 대기용 (Bug 5 수정)
        self._cnsrreq_event: asyncio.Event = asyncio.Event()
        self._cnsrreq_response: Optional[dict] = None
        self._cnsrreq_lock: asyncio.Lock = asyncio.Lock()  # Race Condition 방지
        self._expected_cnsrreq_seq: Optional[str] = None   # [P2] 기대 응답 seq

        # 재연결 Lock (동시 재연결 방지)
        self._reconnect_lock: asyncio.Lock = asyncio.Lock()
        self._is_reconnecting: bool = False

    @property
    def _ws_url(self) -> str:
        """WebSocket URL (모의/실전 자동 선택)"""
        base = self._config.settings.websocket_url
        return f"{base}{self.WEBSOCKET_PATH}"

    @property
    def is_connected(self) -> bool:
        """연결 상태"""
        return self._connected and self._websocket is not None

    def _setup_tcp_keepalive(self) -> None:
        """
        TCP Keepalive 설정 (AWS NAT Gateway 유휴 연결 타임아웃 방지)

        AWS NAT Gateway는 350초 유휴 연결을 끊으므로,
        60초마다 TCP keepalive 패킷을 보내 연결을 유지합니다.
        """
        if not self._websocket:
            return

        try:
            # websockets 라이브러리에서 transport 접근
            transport = getattr(self._websocket, 'transport', None)
            if transport is None:
                self._logger.debug("[TCP Keepalive] transport 없음 - 스킵")
                return

            # socket 객체 가져오기
            sock = transport.get_extra_info('socket')
            if sock is None:
                self._logger.debug("[TCP Keepalive] socket 없음 - 스킵")
                return

            # SO_KEEPALIVE 활성화
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            # Linux 환경 (AWS 서버)
            if hasattr(socket, 'TCP_KEEPIDLE'):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 60)   # 60초 유휴 후 시작
            if hasattr(socket, 'TCP_KEEPINTVL'):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)  # 10초 간격
            if hasattr(socket, 'TCP_KEEPCNT'):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 6)     # 6회 시도

            self._logger.info("[WebSocket] TCP Keepalive 설정 완료 (60초/10초/6회)")

        except Exception as e:
            # Keepalive 실패해도 연결은 유지
            self._logger.warning(f"[TCP Keepalive] 설정 실패 (무시): {e}")

    async def connect(self) -> bool:
        """
        WebSocket 연결 및 인증

        Returns:
            연결 성공 여부
        """
        # 이미 연결되어 있으면 재연결하지 않음
        if self._connected and self._websocket:
            self._logger.debug("WebSocket 이미 연결됨")
            return True

        try:
            token = await self._token_manager.get_token()

            self._logger.info("WebSocket 연결 시도", url=self._ws_url)
            # 키움 서버는 자체 PING 메시지를 사용하므로 websockets 라이브러리의
            # 자동 ping/pong을 비활성화 (충돌 방지)
            self._websocket = await websockets.connect(
                self._ws_url,
                ping_interval=None,  # 자동 ping 비활성화 - 키움 서버 자체 PING 사용
                ping_timeout=None,
            )

            # TCP Keepalive 설정 (AWS NAT Gateway 유휴 연결 타임아웃 방지)
            self._setup_tcp_keepalive()

            # LOGIN 전송
            login_msg = {
                "trnm": WSMessageType.LOGIN.value,
                "token": token,
            }
            await self._send(login_msg)

            # LOGIN 응답 대기
            response = await self._receive_one()

            if response.get("return_code") != 0:
                raise WebSocketConnectionError(
                    f"로그인 실패: {response.get('return_msg')}"
                )

            self._connected = True
            self._reconnect_attempts = 0
            self._logger.info("WebSocket 연결 및 인증 성공")

            # 수신 루프 시작
            self._keep_running = True
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Heartbeat 루프 시작 (좀비 연결 감지)
            self._heartbeat_failures = 0
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

            # [2026-01-08] 클라이언트 Keepalive PING 시작 (서버 유휴 타임아웃 방지)
            self._client_ping_task = asyncio.create_task(self._client_ping_loop())

            if self.on_connected:
                await self.on_connected()

            return True

        except Exception as e:
            self._logger.error("WebSocket 연결 실패", error=str(e))
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """WebSocket 연결 해제"""
        self._keep_running = False

        # Heartbeat 태스크 정리
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None

        # [2026-01-08] 클라이언트 PING 태스크 정리
        if self._client_ping_task:
            self._client_ping_task.cancel()
            try:
                await self._client_ping_task
            except asyncio.CancelledError:
                pass
            self._client_ping_task = None

        if self._receive_task:
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None

        if self._websocket:
            try:
                await self._websocket.close()
            except Exception as e:
                # 연결 종료 중 발생하는 에러는 무시해도 되지만 디버그 로깅
                self._logger.debug(f"WebSocket 종료 중 에러 (무시됨): {e}")
            self._websocket = None

        self._connected = False
        self._active_conditions.clear()
        self._logger.info("WebSocket 연결 해제")

    async def _send(self, message: dict) -> None:
        """메시지 전송"""
        if not self._websocket:
            raise WebSocketDisconnectedError("WebSocket 미연결")

        msg_str = json.dumps(message)
        await self._websocket.send(msg_str)
        self._logger.debug("WS 전송", message=message)

    async def _receive_one(self) -> dict:
        """단일 메시지 수신"""
        if not self._websocket:
            raise WebSocketDisconnectedError("WebSocket 미연결")

        raw = await self._websocket.recv()
        return json.loads(raw)

    async def _receive_loop(self) -> None:
        """메시지 수신 루프"""
        while self._keep_running and self._websocket:
            try:
                raw = await self._websocket.recv()
                response = json.loads(raw)

                msg_type = response.get("trnm")

                # [P0] PING 최우선 처리 - 로깅보다 먼저 즉시 응답 (지연 최소화)
                if msg_type == WSMessageType.PING.value:
                    await self._send(response)  # 즉시 에코
                    self._logger.info("[PING] 수신 → 응답 완료")
                    continue

                # PING 외 메시지만 로깅 (PING은 이미 continue로 빠져나감)
                self._logger.info("WS 메시지 수신", trnm=msg_type, keys=list(response.keys()), raw_preview=str(response)[:500])

                # LOGIN (연결 시 이미 처리됨)
                if msg_type == WSMessageType.LOGIN.value:
                    continue

                # 조건식 목록 응답 처리
                if msg_type == WSMessageType.CNSRLST.value:
                    self._logger.info("조건식 목록 수신", data=response)
                    self._condition_list_data = []
                    for item in response.get("data", []):
                        # API 응답 형식: [["seq", "name"], ...] 또는 [{"seq": ..., "name": ...}, ...]
                        if isinstance(item, list) and len(item) >= 2:
                            # 리스트 형식: ["0", "조건식이름"]
                            self._condition_list_data.append(ConditionInfo(
                                seq=str(item[0]),
                                name=str(item[1]),
                            ))
                        elif isinstance(item, dict):
                            # 딕셔너리 형식: {"seq": "0", "name": "조건식이름"}
                            self._condition_list_data.append(ConditionInfo(
                                seq=item.get("seq", ""),
                                name=item.get("name", ""),
                            ))
                    self._condition_list_event.set()
                    continue

                # 조건검색 응답 처리 (초기 종목 리스트 + 실시간 신호)
                # 응답: {'trnm': 'CNSRREQ', 'seq': '0', 'return_code': 0, 'data': [{'jmcode': 'A459550'}]}
                if msg_type == WSMessageType.CNSRREQ.value:
                    seq = str(response.get("seq", ""))  # str 강제 변환 (타입 안전성)
                    return_code = response.get("return_code", -1)
                    return_msg = response.get("return_msg", "")
                    data_list = response.get("data") or []  # None 처리

                    # return_code에 따른 로깅 분기
                    if return_code == 0:
                        self._logger.info(
                            f"[조건검색] 서버 응답 수신 (성공): seq={seq}, "
                            f"종목수={len(data_list)}"
                        )
                    else:
                        self._logger.error(
                            f"[조건검색] 서버 응답 수신 (실패): seq={seq}, "
                            f"return_code={return_code}, return_msg={return_msg}",
                            full_response=response
                        )

                    # [P2] 응답 seq 매칭 검증 후 이벤트 시그널
                    # - 기대한 seq와 일치할 때만 응답 저장
                    # - Race Condition 방지: 잘못된 응답이 덮어쓰지 않음
                    if self._expected_cnsrreq_seq is not None and seq == self._expected_cnsrreq_seq:
                        self._cnsrreq_response = response
                        self._cnsrreq_event.set()
                    elif self._expected_cnsrreq_seq is None:
                        # 기대값이 없으면 (레거시 호환) 그냥 저장
                        self._cnsrreq_response = response
                        self._cnsrreq_event.set()
                    else:
                        self._logger.warning(
                            f"[P2] 예상치 못한 CNSRREQ 응답 무시: "
                            f"expected={self._expected_cnsrreq_seq}, received={seq}"
                        )

                    # 초기 종목 리스트를 매수 신호로 처리 (return_code == 0일 때만)
                    if return_code == 0:
                        # [FIX] 응답 수신 시 바로 _active_conditions에 추가
                        # start_condition_search()가 타임아웃되어도 구독은 유지됨
                        self._active_conditions.add(seq)
                        self._logger.info(
                            f"[조건검색] 실시간 구독 활성화: seq={seq}, "
                            f"active_conditions={self._active_conditions}"
                        )
                        for item in data_list:
                            if isinstance(item, dict):
                                # jmcode 또는 stk_cd 필드 지원 (API 응답 형식 호환)
                                jmcode = item.get("jmcode") or item.get("stk_cd", "")
                                if jmcode:
                                    # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
                                    clean_code = jmcode[1:] if jmcode.startswith("A") else jmcode
                                    # 매수 신호 생성 (초기 편입 종목)
                                    signal = SignalEvent(
                                        stock_code=clean_code,
                                        stock_name="",  # 초기 리스트에는 종목명 없음
                                        signal_type="I",  # 편입 = 매수
                                        condition_seq=seq,
                                        timestamp="",
                                    )
                                    self._logger.info(
                                        "조건검색 초기 종목 편입",
                                        stock_code=signal.stock_code,
                                        condition_seq=seq,
                                    )
                                    if self.on_signal:
                                        try:
                                            await self.on_signal(signal)
                                        except Exception as e:
                                            self._logger.error("신호 콜백 에러", error=str(e))
                    continue

                # V6.2-M: REG 응답 처리 (실시간 시세 등록)
                # M-002 FIX: 응답 기반 상태 업데이트
                if msg_type == WSMessageType.REG.value:
                    return_code = response.get("return_code", -1)
                    return_msg = response.get("return_msg", "")
                    if return_code == 0:
                        # M-002 FIX: 성공 시 pending → subscribed 이동
                        pending_count = len(self._pending_reg_stocks)
                        self._subscribed_stocks.update(self._pending_reg_stocks)
                        self._pending_reg_stocks.clear()
                        self._logger.info(
                            f"[REG] 실시간 시세 등록 성공: {pending_count}개 종목 "
                            f"(총 구독: {len(self._subscribed_stocks)}개)"
                        )
                    else:
                        # M-002 FIX: 실패 시 pending 클리어 (재시도 가능하도록)
                        failed_count = len(self._pending_reg_stocks)
                        self._pending_reg_stocks.clear()
                        self._logger.error(
                            f"[REG] 실시간 시세 등록 실패: code={return_code}, msg={return_msg}, "
                            f"실패 종목 수={failed_count}",
                            full_response=response
                        )
                    continue

                # V6.2-M: UNREG 응답 처리 (실시간 시세 해제)
                if msg_type == WSMessageType.UNREG.value:
                    return_code = response.get("return_code", -1)
                    if return_code == 0:
                        self._logger.info("[UNREG] 실시간 시세 해제 성공")
                    else:
                        self._logger.warning(f"[UNREG] 실시간 시세 해제 실패: {response}")
                    continue

                # 실시간 신호 (최상위 trnm=REAL)
                if msg_type == WSMessageType.REAL.value:
                    await self._handle_real_data(response)
                    continue

                # 실시간 데이터 (data 배열 안에 trnm이 있는 경우 - 조건검색 신호)
                # API 응답: {"data": [{"trnm": "REAL", "type": "0A", "values": {...}}]}
                data_list = response.get("data", [])
                if data_list and isinstance(data_list, list):
                    for item in data_list:
                        if isinstance(item, dict):
                            item_trnm = item.get("trnm", "")
                            if item_trnm == "REAL":
                                await self._handle_real_item(item)
                    continue

                # 기타 메시지
                self._logger.debug("WS 수신", message=response)

            except ConnectionClosed:
                self._logger.warning("WebSocket 연결 끊김")
                self._connected = False
                self._active_conditions.clear()  # 조건검색 상태 초기화
                # 주의: _subscribed_stocks는 유지 (재연결 후 재구독용)

                # [FIX] WebSocket 완전 종료 (서버 세션 정리)
                if self._websocket:
                    try:
                        await self._websocket.close()
                    except Exception:
                        pass
                    self._websocket = None

                if self.on_disconnected:
                    await self.on_disconnected()

                # 재연결 시도
                if self._keep_running:
                    # [FIX] 서버 세션 정리 대기 (10초)
                    # - 키움 서버가 이전 세션을 완전히 정리한 후 새 연결로 인식
                    # - 즉시 재연결 시 동일 클라이언트로 인식되어 조건검색 무시됨
                    self._logger.info(
                        "[WebSocket] 서버 세션 정리 대기 (10초)... "
                        f"감시종목 {len(self._subscribed_stocks)}개 유지"
                    )
                    await asyncio.sleep(10)
                    await self._reconnect()
                break

            except json.JSONDecodeError as e:
                self._logger.error("JSON 파싱 에러", error=str(e))
                continue

            except Exception as e:
                self._logger.error("WebSocket 수신 에러", error=str(e))
                if not self._keep_running:
                    break

    async def _reconnect(self) -> None:
        """
        2단계 재연결 전략

        Phase 1: 빠른 재연결 (짧은 장애 대응)
        - 5회 시도, 지수 백오프 (2초 → 3초 → 4.5초 ...)
        - 짧은 네트워크 끊김에 빠르게 대응

        Phase 2: 느린 재연결 (장시간 서버 점검 대응)
        - 무한 반복, 5분 간격
        - 키움 서버 점검 (주말, 새벽) 후 자동 복구
        """
        # C-001 FIX: Lock 획득 후 즉시 플래그 설정 (Race Condition 방지)
        # 기존: Lock 밖에서 _is_reconnecting 체크 → 동시 재연결 가능
        # 수정: Lock 내에서만 _is_reconnecting 체크 및 설정
        async with self._reconnect_lock:
            if self._is_reconnecting:
                self._logger.info("[WebSocket] 재연결 이미 진행 중 - 스킵")
                return
            self._is_reconnecting = True  # Lock 내에서 즉시 설정

        try:
            await self._do_reconnect()
        except RuntimeError as e:
            # M-001 FIX: 토큰 갱신 실패 시 재연결 중단
            self._logger.error(f"[WebSocket] 재연결 중단: {e}")
            # 텔레그램 알림 (가능한 경우)
            if self._on_error:
                try:
                    await self._on_error(str(e))
                except Exception:
                    pass
            raise  # 예외 재전파하여 호출자에게 알림
        finally:
            self._is_reconnecting = False

    async def _do_reconnect(self) -> None:
        """실제 재연결 로직 (Lock 보호 하에서 실행)"""
        # [FIX] 재연결 시 토큰 강제 갱신 (키움 서버가 동일 토큰으로 조건검색 응답 거부)
        # M-001 FIX: 토큰 갱신 실패 시 재시도 + Exception 전파
        TOKEN_REFRESH_RETRIES = 3
        TOKEN_REFRESH_DELAY = 2.0  # 초

        for retry in range(TOKEN_REFRESH_RETRIES):
            try:
                self._logger.info(
                    f"[WebSocket] 재연결 전 토큰 강제 갱신... "
                    f"(시도 {retry + 1}/{TOKEN_REFRESH_RETRIES})"
                )
                await self._token_manager.invalidate_and_refresh()
                self._logger.info("[WebSocket] 토큰 갱신 완료")
                break  # 성공 시 루프 탈출
            except Exception as e:
                if retry < TOKEN_REFRESH_RETRIES - 1:
                    self._logger.warning(
                        f"[WebSocket] 토큰 갱신 실패 ({retry + 1}/{TOKEN_REFRESH_RETRIES}): {e} "
                        f"- {TOKEN_REFRESH_DELAY}초 후 재시도"
                    )
                    await asyncio.sleep(TOKEN_REFRESH_DELAY)
                else:
                    # M-001 FIX: 모든 재시도 실패 시 Exception 전파
                    self._logger.error(
                        f"[WebSocket] 토큰 갱신 최종 실패 ({TOKEN_REFRESH_RETRIES}회 시도): {e}"
                    )
                    raise RuntimeError(
                        f"토큰 갱신 실패로 WebSocket 재연결 불가: {e}"
                    ) from e

        # =============================================
        # Phase 1: 빠른 재연결 (5회)
        # =============================================
        while self._reconnect_attempts < self.FAST_RECONNECT_ATTEMPTS:
            self._reconnect_attempts += 1
            delay = self.RECONNECT_BASE_DELAY * (1.5 ** (self._reconnect_attempts - 1))

            self._logger.info(
                f"[Phase 1] 빠른 재연결 시도 {self._reconnect_attempts}/{self.FAST_RECONNECT_ATTEMPTS} "
                f"({delay:.1f}초 후)"
            )

            await asyncio.sleep(delay)

            if await self.connect():
                await self._on_reconnect_success()
                return

        # Phase 1 실패 알림
        self._logger.warning(
            f"빠른 재연결 실패 ({self.FAST_RECONNECT_ATTEMPTS}회) → 느린 재연결 모드 전환"
        )

        # =============================================
        # Phase 2: 느린 재연결 (무한, 5분 간격)
        # =============================================
        slow_attempt = 0
        while self._keep_running:
            slow_attempt += 1

            self._logger.info(
                f"[Phase 2] 느린 재연결 시도 #{slow_attempt} "
                f"({self.SLOW_RECONNECT_INTERVAL / 60:.0f}분 간격)"
            )

            await asyncio.sleep(self.SLOW_RECONNECT_INTERVAL)

            if not self._keep_running:
                break

            if await self.connect():
                self._logger.info(
                    f"느린 재연결 성공 (Phase 2, {slow_attempt}회 시도 후)"
                )
                await self._on_reconnect_success()
                return

        # _keep_running이 False가 되어 종료
        self._logger.info("재연결 루프 종료 (시스템 정지)")

    async def _on_reconnect_success(self) -> None:
        """재연결 성공 후 처리"""
        # 재연결 카운터 초기화
        self._reconnect_attempts = 0

        # [변경] 조건검색 재구독은 SubscriptionManager가 담당
        # _active_conditions는 start_condition_search() 성공 시 자동 업데이트됨

        # 실시간 시세 재구독
        if self._subscribed_stocks:
            stocks_to_resubscribe = list(self._subscribed_stocks)
            self._logger.info(
                f"[WebSocket] 실시간 시세 재구독: {len(stocks_to_resubscribe)}개 종목"
            )
            try:
                await self.subscribe_tick(stocks_to_resubscribe)
                self._logger.info(
                    f"[WebSocket] 시세 재구독 성공: {stocks_to_resubscribe[:5]}..."
                )
            except Exception as e:
                self._logger.error(f"시세 재구독 실패: {e}")

        # 재연결 성공 콜백 호출 (포지션 동기화 등)
        if self.on_reconnected:
            try:
                await self.on_reconnected()
            except Exception as e:
                self._logger.error(f"재연결 콜백 에러: {e}")

    async def _heartbeat_loop(self) -> None:
        """
        Application-Level Heartbeat (좀비 연결 감지)

        60초마다 CNSRLST(조건식 목록)를 요청하여 세션 유효성을 검증합니다.
        키움 서버가 세션을 비활성화해도 WebSocket 연결은 유지되는 "좀비 연결" 문제를 해결합니다.
        """
        self._logger.info("[Heartbeat] 세션 검증 루프 시작")

        while self._connected and self._keep_running:
            await asyncio.sleep(self.HEARTBEAT_INTERVAL)

            if not self._connected or not self._keep_running:
                break

            # [2026-01-08] 장 시작 5분간 heartbeat 스킵 (서버 과부하 대응)
            if self._is_market_opening_period():
                self._logger.debug("[Heartbeat] 장 시작 구간 - 스킵")
                continue

            try:
                # CNSRLST (조건식 목록) - 가벼운 요청으로 세션 검증
                self._condition_list_event.clear()
                await self._send({"trnm": WSMessageType.CNSRLST.value})

                await asyncio.wait_for(
                    self._condition_list_event.wait(),
                    timeout=self.HEARTBEAT_TIMEOUT
                )

                # 성공 - 세션 유효
                self._heartbeat_failures = 0
                self._logger.debug("[Heartbeat] 세션 유효 확인")

            except asyncio.CancelledError:
                # 태스크 취소 시 조용히 종료
                break

            except ConnectionClosed as e:
                # WebSocket 연결 종료 - 정상 종료
                self._logger.info(f"[Heartbeat] 연결 종료됨 (정상): {e.code}")
                break

            except asyncio.TimeoutError:
                self._heartbeat_failures += 1
                threshold = self._get_heartbeat_threshold()
                self._logger.warning(
                    f"[Heartbeat] 응답 없음 ({self._heartbeat_failures}/{threshold})"
                )

                if self._heartbeat_failures >= threshold:
                    self._logger.error("[Heartbeat] 좀비 연결 감지 - 강제 재연결")
                    await self._trigger_reconnect()
                    break

            except Exception as e:
                self._logger.error(f"[Heartbeat] 예상치 못한 에러: {e}")

        self._logger.info("[Heartbeat] 세션 검증 루프 종료")

    async def _client_ping_loop(self) -> None:
        """
        [2026-01-08] 클라이언트 Keepalive PING

        20초마다 서버에 PING을 전송하여 유휴 타임아웃을 방지합니다.
        키움 서버가 유휴 연결을 종료하는 것을 막기 위한 능동적 keepalive.
        """
        self._logger.info("[ClientPing] Keepalive 루프 시작 (20초 간격)")

        while self._connected and self._keep_running:
            await asyncio.sleep(self.CLIENT_PING_INTERVAL)

            if not self._connected or not self._keep_running:
                break

            try:
                # 클라이언트 측에서 PING 전송 (서버 응답 불필요)
                await self._send({"trnm": "PING"})
                self._logger.debug("[ClientPing] PING 전송")

            except ConnectionClosed:
                self._logger.info("[ClientPing] 연결 종료됨 - 루프 종료")
                break

            except Exception as e:
                self._logger.warning(f"[ClientPing] 전송 실패: {e}")

        self._logger.info("[ClientPing] Keepalive 루프 종료")

    async def _trigger_reconnect(self) -> None:
        """
        좀비 연결 감지 시 강제 재연결

        Heartbeat 실패 시 호출되어 WebSocket을 완전히 재연결합니다.
        """
        self._logger.info("[WebSocket] 강제 재연결 트리거")

        # [2026-01-07 FIX] 이미 재연결 중이면 스킵
        if self._is_reconnecting:
            self._logger.info("[WebSocket] 이미 재연결 진행 중 - 트리거 스킵")
            return

        # 1. heartbeat_task 먼저 취소 (태스크 누적 방지)
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
            self._logger.info("[WebSocket] heartbeat_task 취소 완료")

        # 2. receive_task 취소 (recv() 충돌 방지)
        if self._receive_task and not self._receive_task.done():
            self._receive_task.cancel()
            try:
                await self._receive_task
            except asyncio.CancelledError:
                pass
            self._receive_task = None
            self._logger.info("[WebSocket] receive_task 취소 완료")

        # 3. 현재 연결 강제 종료
        self._connected = False
        if self._websocket:
            try:
                await self._websocket.close()
            except Exception:
                pass
            self._websocket = None

        # 4. 상태 초기화
        self._active_conditions.clear()
        self._heartbeat_failures = 0

        # 5. disconnected 콜백 (SubscriptionManager 알림)
        if self.on_disconnected:
            try:
                await self.on_disconnected()
            except Exception as e:
                self._logger.error(f"[WebSocket] disconnected 콜백 에러: {e}")

        # 6. 재연결 시작
        if self._keep_running:
            self._logger.info("[WebSocket] 5초 후 재연결 시작...")
            await asyncio.sleep(5)  # 서버 세션 정리 대기
            await self._reconnect()

    async def _handle_real_item(self, item: dict) -> None:
        """
        실시간 데이터 항목 처리 (data 배열 안의 개별 항목)

        API 응답 구조:
        {"data": [{"trnm": "REAL", "type": "0A", "values": {...}}]}
        """
        item_type = item.get("type", "")
        values = item.get("values", {})

        self._logger.debug("실시간 항목 수신", item_type=item_type, values=values)

        # 조건검색 신호 (843 필드가 있으면 조건검색 신호 - 9001은 종목코드로 다른 메시지에도 존재)
        if "843" in values:
            await self._handle_condition_signal(values)
        # 실시간 체결가 (틱 데이터)
        elif item_type.startswith(RealDataType.TICK.value):
            await self._handle_tick_data(values)
        else:
            self._logger.debug("기타 실시간 데이터", item_type=item_type, values=values)

    async def _handle_real_data(self, response: dict) -> None:
        """실시간 데이터 처리 (최상위 trnm=REAL)

        V6.2-O: 틱 데이터 라우팅 버그 수정
        - 기존: data_type 필드 기반 (항상 빈 문자열이라 틱 데이터 미처리)
        - 수정: values 내 필드 존재 여부로 판단 (20=체결시간, 10=현재가)
        """
        data = response.get("data", [])

        for item in data:
            values = item.get("values", {})

            # V6.2-O: 조건검색 신호 우선 체크 (843 필드가 있으면 조건검색)
            if "843" in values:
                await self._handle_condition_signal(values)

            # V6.2-O: 틱 데이터 (20=체결시간, 10=현재가 존재 시)
            elif "20" in values and "10" in values:
                await self._handle_tick_data(values)

            # 기타 실시간 데이터
            else:
                self._logger.debug("기타 실시간 데이터", values=values)

    async def _handle_tick_data(self, values: dict) -> None:
        """실시간 체결가 (틱) 처리"""
        try:
            tick = TickData.from_ws_data(values)

            if self.on_tick:
                await self.on_tick(tick)

        except Exception as e:
            self._logger.error("틱 데이터 처리 에러", error=str(e))

    async def _handle_condition_signal(self, values: dict) -> None:
        """조건검색 신호 처리"""
        # API 문서 기준 필드:
        # - 9001: 종목코드
        # - 302 또는 9002: 종목명
        # - 843: 신호방향 (I=매수, D=매도)
        # - 20: 체결시간
        # - seq: 조건식 번호
        raw_code = values.get("9001", "")
        # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
        clean_stock_code = raw_code[1:] if raw_code.startswith("A") else raw_code
        signal = SignalEvent(
            stock_code=clean_stock_code,
            stock_name=values.get("302", values.get("9002", "")),  # 302 우선, 없으면 9002
            signal_type=values.get("843", values.get("type", "I")),  # 843 우선, 없으면 type
            condition_seq=values.get("841", values.get("seq", "")),  # 841 우선, 없으면 seq
            timestamp=values.get("20", values.get("time", "")),  # 20 우선, 없으면 time
        )

        self._logger.info(
            "조건검색 신호 수신",
            stock_code=signal.stock_code,
            stock_name=signal.stock_name,
            signal_type="매수" if signal.is_buy_signal else "매도",
            raw_values=values,  # 디버깅용 원본 데이터
        )

        if self.on_signal:
            try:
                await self.on_signal(signal)
            except Exception as e:
                self._logger.error("신호 콜백 에러", error=str(e))

    async def get_condition_list(self) -> list[ConditionInfo]:
        """
        조건식 목록 조회

        Returns:
            ConditionInfo 리스트
        """
        if not self.is_connected:
            raise WebSocketDisconnectedError("WebSocket 미연결")

        # 이벤트 초기화 후 요청 전송
        self._condition_list_event.clear()
        self._condition_list_data = []

        await self._send({"trnm": WSMessageType.CNSRLST.value})

        # 응답 대기 (최대 10초)
        try:
            await asyncio.wait_for(
                self._condition_list_event.wait(),
                timeout=10.0
            )
        except asyncio.TimeoutError:
            self._logger.warning("조건식 목록 응답 타임아웃")
            return []

        return self._condition_list_data

    async def start_condition_search(
        self,
        seq: str,
        exchange: str = "K",
        search_type: str = "1",
        timeout: float = 30.0,  # 2026-01-08: 20초→30초 장시작 서버부하 대응
    ) -> bool:
        """
        실시간 조건검색 시작

        Args:
            seq: 조건식 번호
            exchange: "K" KRX, "N" NXT
            search_type: "1" 실시간
            timeout: 응답 대기 타임아웃 (초, 기본 20초)

        Returns:
            성공 여부 (서버 응답 수신 시 True)
        """
        self._logger.info(f"[조건검색] 구독 요청 시작: seq={seq}, exchange={exchange}")

        if not self.is_connected:
            self._logger.error(f"[조건검색] 실패: WebSocket 미연결 (is_connected={self.is_connected})")
            raise WebSocketDisconnectedError("WebSocket 미연결")

        # [FIX] 구독 전 항상 해제 시도 (서버 캐시 문제 방지)
        # 키움 서버가 이전 세션의 구독 상태를 유지하면 재구독 시 응답하지 않음
        try:
            clear_msg = {
                "trnm": WSMessageType.CNSRCLR.value,
                "seq": seq,
            }
            await self._send(clear_msg)
            self._logger.info(f"[조건검색] 사전 해제 전송: seq={seq}")
            await asyncio.sleep(2.0)  # 서버 처리 대기 (좀비 연결 방지)
        except Exception as e:
            self._logger.debug(f"[조건검색] 사전 해제 실패 (무시): {e}")

        # Race Condition 방지: Lock으로 요청-응답 순서 보장
        async with self._cnsrreq_lock:
            # 응답 대기 이벤트 초기화
            self._cnsrreq_event.clear()
            self._cnsrreq_response = None
            self._expected_cnsrreq_seq = seq  # [P2] 기대 응답 seq 설정

            msg = {
                "trnm": WSMessageType.CNSRREQ.value,
                "seq": seq,
                "search_type": search_type,
                "stex_tp": exchange,
            }

            self._logger.info(f"[조건검색] CNSRREQ 메시지 전송: {msg}")
            await self._send(msg)

            # 서버 응답 대기
            try:
                await asyncio.wait_for(self._cnsrreq_event.wait(), timeout=timeout)

                # 응답 확인
                if self._cnsrreq_response:
                    return_code = self._cnsrreq_response.get("return_code", -1)
                    if return_code == 0:
                        self._active_conditions.add(seq)
                        initial_stocks = len(self._cnsrreq_response.get("data") or [])
                        self._logger.info(
                            f"[조건검색] 구독 성공: seq={seq}, 초기종목={initial_stocks}개"
                        )
                        return True
                    else:
                        return_msg = self._cnsrreq_response.get("return_msg", "")
                        self._logger.error(
                            f"[조건검색] 구독 거부: seq={seq}, code={return_code}, msg={return_msg}"
                        )
                        return False
                else:
                    self._logger.error(f"[조건검색] 응답 수신했으나 데이터 없음: seq={seq}")
                    return False

            except asyncio.TimeoutError:
                self._logger.error(
                    f"[조건검색] 응답 타임아웃 ({timeout}초): seq={seq}\n"
                    f"  WebSocket 상태: connected={self._connected}, "
                    f"active_conditions={self._active_conditions}\n"
                    f"  가능한 원인: 1) HTS 조건식 미전송 2) 서버 과부하 3) 네트워크 지연"
                )
                return False
            finally:
                # [P2] 기대 seq 초기화 (다음 요청 준비)
                self._expected_cnsrreq_seq = None

    async def stop_condition_search(self, seq: str) -> None:
        """
        실시간 조건검색 해제

        Args:
            seq: 조건식 번호
        """
        if not self.is_connected:
            return

        msg = {
            "trnm": WSMessageType.CNSRCLR.value,  # API 문서 기준: CNSRCLR
            "seq": seq,
        }

        await self._send(msg)
        self._active_conditions.discard(seq)
        self._logger.info(f"조건검색 해제: seq={seq}")

    async def poll_condition_search(
        self,
        seq: str,
        exchange: str = "K",
        timeout: float = 30.0,  # 2026-01-08: 20초→30초 장시작 서버부하 대응
    ) -> Optional[list[str]]:
        """
        일회성 조건검색 (폴링용)

        실시간 구독(search_type=1)과 달리 일회성(search_type=0)으로 조건검색을 수행하고
        현재 조건에 맞는 종목 리스트만 반환합니다. 실시간 신호는 발생하지 않습니다.

        Args:
            seq: 조건식 번호
            exchange: "K" KRX, "N" NXT
            timeout: 응답 대기 타임아웃 (초, 기본 20초)

        Returns:
            종목코드 리스트 (성공 시) 또는 None (실패/타임아웃 시)
        """
        self._logger.info(f"[조건검색-폴링] 요청: seq={seq}, exchange={exchange}")

        if not self.is_connected:
            self._logger.error(f"[조건검색-폴링] 실패: WebSocket 미연결")
            return None

        async with self._cnsrreq_lock:
            self._cnsrreq_event.clear()
            self._cnsrreq_response = None
            self._expected_cnsrreq_seq = seq

            msg = {
                "trnm": WSMessageType.CNSRREQ.value,
                "seq": seq,
                "search_type": "0",  # 일회성 (폴링)
                "stex_tp": exchange,
            }

            self._logger.info(f"[조건검색-폴링] CNSRREQ 전송: {msg}")
            await self._send(msg)

            try:
                await asyncio.wait_for(self._cnsrreq_event.wait(), timeout=timeout)

                if self._cnsrreq_response:
                    return_code = self._cnsrreq_response.get("return_code", -1)
                    if return_code == 0:
                        data_list = self._cnsrreq_response.get("data") or []
                        stock_codes = []

                        for item in data_list:
                            if isinstance(item, dict):
                                jmcode = item.get("jmcode") or item.get("stk_cd", "")
                                if jmcode:
                                    # 종목코드 정규화: 앞의 'A'만 제거 (NXT 코드 중간의 'A' 보존)
                                    clean_code = jmcode[1:] if jmcode.startswith("A") else jmcode
                                    stock_codes.append(clean_code)

                        self._logger.info(
                            f"[조건검색-폴링] 성공: seq={seq}, 종목수={len(stock_codes)}"
                        )
                        return stock_codes
                    else:
                        return_msg = self._cnsrreq_response.get("return_msg", "")
                        self._logger.error(
                            f"[조건검색-폴링] 실패: seq={seq}, code={return_code}, msg={return_msg}"
                        )
                        return None
                else:
                    self._logger.error(f"[조건검색-폴링] 응답 없음: seq={seq}")
                    return None

            except asyncio.TimeoutError:
                self._logger.error(
                    f"[조건검색-폴링] 타임아웃 ({timeout}초): seq={seq}"
                )
                return None
            finally:
                self._expected_cnsrreq_seq = None

    # =========================================
    # 실시간 시세 구독 (틱 데이터)
    # =========================================

    async def subscribe_tick(self, stock_codes: list[str]) -> None:
        """
        실시간 체결가 (틱) 구독 - V6.2-M REG 명령어 사용

        Args:
            stock_codes: 종목코드 목록 (최대 20개)
        """
        if not self.is_connected:
            raise WebSocketDisconnectedError("WebSocket 미연결")

        if not stock_codes:
            return

        # 최대 20개 제한
        codes_to_subscribe = stock_codes[:20]

        # V6.2-M: REG 명령어 사용 (앞의 A만 제거, NXT 코드 중간의 A 보존)
        codes_without_prefix = [
            code[1:] if code.startswith("A") else code
            for code in codes_to_subscribe
        ]

        msg = {
            "trnm": WSMessageType.REG.value,
            "grp_no": "1",
            "refresh": "1",
            "data": [{
                "item": codes_without_prefix,
                "type": ["0B"]  # 주식체결 (틱)
            }]
        }

        await self._send(msg)
        # M-002 FIX: 응답 전에는 pending으로 처리 (응답 후 subscribed로 이동)
        self._pending_reg_stocks.update(codes_to_subscribe)
        self._logger.info(f"[REG] 실시간 시세 등록 요청: {len(codes_to_subscribe)}개 종목 (pending)")

    async def unsubscribe_tick(self, stock_codes: list[str]) -> None:
        """
        실시간 체결가 구독 해제 - V6.2-M UNREG 명령어 사용

        Args:
            stock_codes: 종목코드 목록
        """
        if not self.is_connected:
            return

        if not stock_codes:
            return

        # V6.2-M: UNREG 명령어 사용 (앞의 A만 제거, NXT 코드 중간의 A 보존)
        codes_without_prefix = [
            code[1:] if code.startswith("A") else code
            for code in stock_codes
        ]

        msg = {
            "trnm": WSMessageType.UNREG.value,
            "grp_no": "1",
            "data": [{
                "item": codes_without_prefix,
                "type": ["0B"]
            }]
        }

        await self._send(msg)
        for code in stock_codes:
            self._subscribed_stocks.discard(code)
            # M-002 FIX: pending에서도 제거
            self._pending_reg_stocks.discard(code)
        self._logger.info(f"[UNREG] 실시간 시세 해제 요청: {len(stock_codes)}개 종목")

    async def unsubscribe_all_tick(self) -> None:
        """모든 실시간 체결가 구독 해제"""
        if self._subscribed_stocks:
            await self.unsubscribe_tick(list(self._subscribed_stocks))
            self._subscribed_stocks.clear()
        # M-002 FIX: pending도 클리어
        self._pending_reg_stocks.clear()

    @property
    def subscribed_stocks(self) -> Set[str]:
        """구독 중인 종목 목록"""
        return self._subscribed_stocks.copy()
