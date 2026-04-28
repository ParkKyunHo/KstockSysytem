"""
텔레그램 봇 모듈

메시지 발송 및 명령어 처리를 담당합니다.
"""

from typing import Optional, Callable, Awaitable, List, Dict, Any, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import asyncio

import httpx

from src.utils.config import get_telegram_settings, TelegramSettings
from src.utils.logger import get_logger


# 콜백 타입
CommandCallback = Callable[[str, List[str]], Awaitable[None]]

# P1: Circuit Breaker 설정
CIRCUIT_BREAKER_FAILURE_THRESHOLD = 5    # 연속 실패 임계값
CIRCUIT_BREAKER_TIMEOUT_SECONDS = 300    # Circuit 열림 상태 유지 시간 (5분)
CIRCUIT_BREAKER_LOG_FILE = Path("logs/circuit_breaker_events.log")


class TelegramBot:
    """
    텔레그램 봇

    기능:
    - 메시지 발송 (텍스트, 버튼)
    - 명령어 수신 및 처리 (폴링)
    - 인라인 키보드 지원

    Usage:
        bot = TelegramBot()
        bot.register_command("start", my_start_handler)
        await bot.send_message("Hello!")
        await bot.start_polling()
    """

    API_BASE = "https://api.telegram.org/bot"
    FAILED_ALERTS_FILE = Path("logs/failed_alerts.log")
    MAX_FAILED_ALERTS = 50  # 최대 저장 개수

    def __init__(self, settings: Optional[TelegramSettings] = None):
        self._settings = settings or get_telegram_settings()
        self._logger = get_logger(__name__)

        self._last_update_id = 0
        self._keep_polling = False
        self._poll_task: Optional[asyncio.Task] = None

        # 명령어 핸들러
        self._command_handlers: Dict[str, CommandCallback] = {}

        # 콜백 쿼리 핸들러 (버튼 클릭)
        self._callback_handlers: Dict[str, CommandCallback] = {}

        # V6.2-A: 알림 실패 시 백업 큐
        self._failed_alerts: List[Tuple[datetime, str]] = []

        # P1: Circuit Breaker 상태
        self._circuit_failures: int = 0
        self._circuit_open_until: Optional[datetime] = None
        self._circuit_breaker_opens_today: int = 0

        # 로그 디렉토리 생성
        self.FAILED_ALERTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    @property
    def _token(self) -> str:
        return self._settings.bot_token

    @property
    def _chat_id(self) -> str:
        return self._settings.chat_id

    def _api_url(self, method: str) -> str:
        return f"{self.API_BASE}{self._token}/{method}"

    # =========================================
    # P1: Circuit Breaker 메서드
    # =========================================

    def _is_circuit_open(self) -> bool:
        """
        Circuit Breaker 열림 상태 확인

        Returns:
            True: 열림 (요청 거부), False: 닫힘 (요청 허용)
        """
        if self._circuit_open_until is None:
            return False

        if datetime.now() >= self._circuit_open_until:
            # 타임아웃 경과 - Half-Open 상태로 전환 (다음 요청으로 테스트)
            self._circuit_open_until = None
            self._circuit_failures = 0
            self._logger.info("[Circuit Breaker] 타임아웃 경과 - 재시도 허용")
            self._write_circuit_breaker_event("RECOVERED - 타임아웃 경과, 재시도 허용")
            return False

        return True

    def _on_circuit_success(self) -> None:
        """전송 성공 시 Circuit Breaker 리셋"""
        if self._circuit_failures > 0:
            self._logger.info(
                f"[Circuit Breaker] 성공 - 실패 카운트 리셋 (이전: {self._circuit_failures})"
            )
        self._circuit_failures = 0
        self._circuit_open_until = None

    def _on_circuit_failure(self) -> None:
        """전송 실패 시 Circuit Breaker 업데이트"""
        self._circuit_failures += 1

        if self._circuit_failures >= CIRCUIT_BREAKER_FAILURE_THRESHOLD:
            self._circuit_open_until = datetime.now() + timedelta(
                seconds=CIRCUIT_BREAKER_TIMEOUT_SECONDS
            )
            self._circuit_breaker_opens_today += 1
            self._logger.error(
                f"[Circuit Breaker] 열림 - 연속 {self._circuit_failures}회 실패, "
                f"{CIRCUIT_BREAKER_TIMEOUT_SECONDS}초 동안 요청 거부"
            )
            self._write_circuit_breaker_event(
                f"OPEN - 연속 {self._circuit_failures}회 실패, "
                f"오늘 {self._circuit_breaker_opens_today}회째 열림"
            )
        else:
            self._logger.warning(
                f"[Circuit Breaker] 실패 {self._circuit_failures}/"
                f"{CIRCUIT_BREAKER_FAILURE_THRESHOLD}"
            )

    def get_circuit_breaker_status(self) -> dict:
        """Circuit Breaker 상태 조회"""
        is_open = self._is_circuit_open()
        remaining = 0
        if self._circuit_open_until:
            remaining = max(0, (self._circuit_open_until - datetime.now()).total_seconds())

        return {
            "is_open": is_open,
            "failures": self._circuit_failures,
            "threshold": CIRCUIT_BREAKER_FAILURE_THRESHOLD,
            "remaining_seconds": int(remaining),
        }

    def _write_circuit_breaker_event(self, event: str) -> None:
        """Circuit Breaker 이벤트를 로그 파일에 기록"""
        try:
            CIRCUIT_BREAKER_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CIRCUIT_BREAKER_LOG_FILE, "a", encoding="utf-8") as f:
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"{timestamp} | {event}\n")
        except Exception as e:
            self._logger.warning(f"Circuit Breaker 이벤트 로그 기록 실패: {e}")

    def get_stats(self) -> dict:
        """텔레그램 봇 통계 조회"""
        return {
            "circuit_breaker": self.get_circuit_breaker_status(),
            "circuit_breaker_opens_today": self._circuit_breaker_opens_today,
            "failed_alerts_count": len(self._failed_alerts),
        }

    # =========================================
    # 메시지 발송 메서드
    # =========================================

    async def send_message(
        self,
        text: str,
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """
        메시지 발송 (V6.2-A: 실패 시 백업 + 재시도 큐, P1: Circuit Breaker)

        Args:
            text: 메시지 내용
            chat_id: 채팅 ID (기본: 설정값)
            parse_mode: 파싱 모드 (None=plain text, "Markdown", "HTML")

        Returns:
            성공 여부
        """
        # P1: Circuit Breaker 체크
        if self._is_circuit_open():
            self._logger.warning("[Circuit Breaker] 열림 상태 - 메시지 백업만 수행")
            await self._backup_failed_alert(text)
            return False

        payload = {
            "chat_id": chat_id or self._chat_id,
            "text": text,
        }
        # V6.2-Q FIX: parse_mode 사용 금지 (CLAUDE.md 규칙 - 400 에러 발생)
        if parse_mode:
            self._logger.warning(
                f"parse_mode 사용 시도 무시됨: {parse_mode} (CLAUDE.md 규칙)"
            )
            # parse_mode를 payload에 추가하지 않음

        last_error = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        self._api_url("sendMessage"),
                        json=payload,
                        timeout=10.0,
                    )
                    response.raise_for_status()
                    self._on_circuit_success()
                    await self._retry_failed_alerts()
                    return True
            except Exception as e:
                last_error = e
                if attempt == 0:
                    self._logger.warning(f"텔레그램 발송 실패, 2초 후 재시도: {e}")
                    await asyncio.sleep(2)
                    continue
                break

        # Both attempts failed
        self._logger.error("텔레그램 메시지 발송 실패 (재시도 포함)", error=str(last_error))
        self._on_circuit_failure()
        await self._backup_failed_alert(text)
        return False

    async def _retry_failed_alerts(self) -> None:
        """
        V6.2-A: 실패한 알림 재전송 (성공적인 전송 후 호출)

        최대 3개까지만 재전송하여 연쇄 실패 방지
        """
        retry_count = 0
        max_retry = 3

        while self._failed_alerts and retry_count < max_retry:
            timestamp, message = self._failed_alerts.pop(0)
            retry_count += 1

            try:
                elapsed = (datetime.now() - timestamp).total_seconds() / 60
                delayed_text = f"[지연 {int(elapsed)}분] {message}"

                async with httpx.AsyncClient() as client:
                    await client.post(
                        self._api_url("sendMessage"),
                        json={
                            "chat_id": self._chat_id,
                            "text": delayed_text[:4000],  # 최대 길이 제한
                        },
                        timeout=10.0,
                    )
                self._logger.info(f"지연 알림 전송 성공 ({retry_count}/{len(self._failed_alerts) + retry_count})")

            except Exception as e:
                # 재전송도 실패하면 다시 큐에 넣지 않음 (무한 루프 방지)
                self._logger.warning(f"지연 알림 재전송 실패: {e}")
                break

    async def _backup_failed_alert(self, text: str) -> None:
        """
        V6.2-A: 실패한 알림 백업 (메모리 큐 + 파일)
        """
        now = datetime.now()

        # 1. 메모리 큐에 추가 (최대 개수 제한)
        self._failed_alerts.append((now, text))
        if len(self._failed_alerts) > self.MAX_FAILED_ALERTS:
            self._failed_alerts = self._failed_alerts[-self.MAX_FAILED_ALERTS:]

        # 2. 파일에 백업 (영구 기록)
        try:
            with open(self.FAILED_ALERTS_FILE, "a", encoding="utf-8") as f:
                timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")
                # 줄바꿈을 공백으로 치환하여 한 줄로 기록
                safe_text = text.replace("\n", " | ")[:500]
                f.write(f"{timestamp_str} | {safe_text}\n")
        except Exception as e:
            self._logger.warning(f"알림 백업 파일 저장 실패: {e}")

    async def send_with_buttons(
        self,
        text: str,
        buttons: List[List[Dict[str, str]]],
        chat_id: Optional[str] = None,
        parse_mode: Optional[str] = None,
    ) -> bool:
        """
        버튼 포함 메시지 발송

        Args:
            text: 메시지 내용
            buttons: 버튼 배열 [[{"text": "버튼1", "callback_data": "btn1"}]]
            chat_id: 채팅 ID
            parse_mode: 파싱 모드 (None=plain text)

        Returns:
            성공 여부
        """
        payload = {
            "chat_id": chat_id or self._chat_id,
            "text": text,
            "reply_markup": {
                "inline_keyboard": buttons,
            },
        }
        # V6.2-Q FIX: parse_mode 사용 금지 (CLAUDE.md 규칙 - 400 에러 발생)
        if parse_mode:
            self._logger.warning(
                f"parse_mode 사용 시도 무시됨: {parse_mode} (CLAUDE.md 규칙)"
            )
            # parse_mode를 payload에 추가하지 않음

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    self._api_url("sendMessage"),
                    json=payload,
                    timeout=10.0,
                )
                response.raise_for_status()
                return True

        except Exception as e:
            self._logger.error("텔레그램 버튼 메시지 발송 실패", error=str(e))
            return False

    async def send_eod_choice(self) -> bool:
        """장 종료 선택 버튼 발송"""
        text = """**장 종료 알림**

15:15입니다. 보유 종목 처리 방법을 선택해주세요."""

        buttons = [
            [
                {"text": "보유 유지", "callback_data": "eod_hold"},
                {"text": "전량 청산", "callback_data": "eod_liquidate"},
            ]
        ]

        return await self.send_with_buttons(text, buttons)

    def register_command(self, command: str, handler: CommandCallback) -> None:
        """
        명령어 핸들러 등록

        Args:
            command: 명령어 (예: "start", "stop")
            handler: async def handler(chat_id: str, args: List[str])
        """
        self._command_handlers[command.lower()] = handler

    def command_handler(self, command: str):
        """
        명령어 핸들러 데코레이터

        Usage:
            @bot.command_handler("/start")
            async def cmd_start():
                await bot.send_message("Started!")

        Args:
            command: 명령어 (예: "/start", "/stop")

        Returns:
            데코레이터 함수
        """
        def decorator(func: Callable[[], Awaitable[None]]):
            # 슬래시 제거
            cmd = command.lstrip("/").lower()

            # 래퍼 함수 (chat_id, args를 무시하고 원본 함수 호출)
            async def wrapper(chat_id: str, args: List[str]) -> None:
                await func()

            self._command_handlers[cmd] = wrapper
            return func

        return decorator

    def callback_handler(self, callback_data: str):
        """
        콜백 핸들러 데코레이터

        Usage:
            @bot.callback_handler("eod_hold")
            async def handle_hold():
                await bot.send_message("Holding positions")

        Args:
            callback_data: 콜백 데이터

        Returns:
            데코레이터 함수
        """
        def decorator(func: Callable[[], Awaitable[None]]):
            async def wrapper(chat_id: str, args: List[str]) -> None:
                await func()

            self._callback_handlers[callback_data] = wrapper
            return func

        return decorator

    def register_callback(self, callback_data: str, handler: CommandCallback) -> None:
        """
        콜백 쿼리 핸들러 등록

        Args:
            callback_data: 콜백 데이터 (버튼의 callback_data)
            handler: async def handler(chat_id: str, args: List[str])
        """
        self._callback_handlers[callback_data] = handler

    async def start_polling(self, interval: float = 1.0) -> None:
        """
        메시지 폴링 시작

        Args:
            interval: 폴링 간격 (초)
        """
        if self._poll_task is not None:
            return

        self._keep_polling = True
        self._poll_task = asyncio.create_task(self._poll_loop(interval))
        self._logger.info("텔레그램 폴링 시작")

    async def stop_polling(self) -> None:
        """메시지 폴링 중지"""
        self._keep_polling = False

        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
            self._poll_task = None

        self._logger.info("텔레그램 폴링 중지")

    async def _poll_loop(self, interval: float) -> None:
        """폴링 루프"""
        while self._keep_polling:
            try:
                await self._check_updates()
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("텔레그램 폴링 에러", error=str(e))
                await asyncio.sleep(interval)

    async def _check_updates(self) -> None:
        """업데이트 확인"""
        params = {
            "offset": self._last_update_id + 1,
            "timeout": 0,
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    self._api_url("getUpdates"),
                    params=params,
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

                if not data.get("ok"):
                    return

                for update in data.get("result", []):
                    await self._process_update(update)
                    self._last_update_id = update["update_id"]

        except Exception as e:
            self._logger.error("업데이트 확인 실패", error=str(e))

    async def _process_update(self, update: dict) -> None:
        """업데이트 처리"""
        # 일반 메시지 (명령어)
        if "message" in update:
            await self._process_message(update["message"])

        # 콜백 쿼리 (버튼 클릭)
        elif "callback_query" in update:
            await self._process_callback(update["callback_query"])

    async def _process_message(self, message: dict) -> None:
        """메시지 처리"""
        text = message.get("text", "")
        chat_id = str(message.get("chat", {}).get("id", ""))

        # 명령어 확인
        if not text.startswith("/"):
            return

        # 명령어 파싱
        parts = text[1:].split()
        if not parts:
            return

        command = parts[0].lower()
        args = parts[1:]

        # @봇이름 제거
        if "@" in command:
            command = command.split("@")[0]

        self._logger.info(f"명령어 수신: /{command}", args=args, chat_id=chat_id)

        # 핸들러 실행
        if command in self._command_handlers:
            try:
                await self._command_handlers[command](chat_id, args)
            except Exception as e:
                self._logger.error(f"명령어 처리 에러: /{command}", error=str(e))
                await self.send_message(f"명령어 처리 중 에러가 발생했습니다: {e}", chat_id)

        elif command == "help":
            await self.send_message(
                "K_stock_trading V7.1 — V71TelegramCommands에서 명령어를 처리합니다. "
                "V71TelegramCommands가 등록되지 않은 경우 이 fallback이 응답합니다.",
                chat_id,
            )

        else:
            await self.send_message(
                f"알 수 없는 명령어입니다: /{command}\n/help 로 명령어 목록을 확인하세요.",
                chat_id,
            )

    async def _process_callback(self, callback_query: dict) -> None:
        """콜백 쿼리 처리 (버튼 클릭)"""
        callback_data = callback_query.get("data", "")
        chat_id = str(callback_query.get("message", {}).get("chat", {}).get("id", ""))
        callback_id = callback_query.get("id")

        self._logger.info(f"콜백 수신: {callback_data}", chat_id=chat_id)

        # 콜백 응답 (버튼 로딩 제거)
        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    self._api_url("answerCallbackQuery"),
                    json={"callback_query_id": callback_id},
                    timeout=5.0,
                )
        except Exception as e:
            # 콜백 응답 실패는 치명적이지 않음 - 디버그 로깅만
            self._logger.debug(f"콜백 응답 실패 (무시됨): {e}")

        # 1. 정확한 매칭 핸들러 실행
        if callback_data in self._callback_handlers:
            try:
                await self._callback_handlers[callback_data](chat_id, [])
            except Exception as e:
                self._logger.error(f"콜백 처리 에러: {callback_data}", error=str(e))
            return

        # 2. 프리픽스 매칭 핸들러 실행 (예: "promote:005930")
        if ":" in callback_data:
            prefix, value = callback_data.split(":", 1)
            prefix_key = f"{prefix}:"
            if prefix_key in self._callback_handlers:
                try:
                    # args에 값 전달
                    await self._callback_handlers[prefix_key](chat_id, [value])
                except Exception as e:
                    self._logger.error(f"콜백 처리 에러: {callback_data}", error=str(e))
                return

        self._logger.warning(f"처리되지 않은 콜백: {callback_data}")

    def register_prefix_callback(self, prefix: str, handler: CommandCallback) -> None:
        """
        프리픽스 콜백 핸들러 등록

        Args:
            prefix: 콜백 프리픽스 (예: "promote")
            handler: async def handler(chat_id: str, args: List[str])
                     args[0]에 프리픽스 이후 값이 전달됨

        Usage:
            async def on_promote(chat_id, args):
                stock_code = args[0]  # "005930"
                ...
            bot.register_prefix_callback("promote", on_promote)
        """
        self._callback_handlers[f"{prefix}:"] = handler


# 싱글톤 인스턴스
_telegram_bot: Optional[TelegramBot] = None


def get_telegram_bot() -> TelegramBot:
    """싱글톤 TelegramBot 인스턴스 반환"""
    global _telegram_bot
    if _telegram_bot is None:
        _telegram_bot = TelegramBot()
    return _telegram_bot
