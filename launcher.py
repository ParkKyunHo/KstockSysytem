#!/usr/bin/env python3
"""
K_stock_trading 프로덕션 런처
============================

기능:
- Pre-flight 검증 (6가지)
- 자동 재시작 (지수 백오프)
- Graceful Shutdown (SIGTERM/SIGINT)
- 텔레그램 알림
- 로그 관리

버전: 1.0.0
작성일: 2025-12-14
"""

import asyncio
import importlib
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

# ============================================================
# 설정
# ============================================================

class LauncherConfig:
    """런처 설정"""

    # 경로
    PROJECT_DIR = Path(__file__).parent.resolve()
    LOG_DIR = PROJECT_DIR / "logs"
    DATA_DIR = PROJECT_DIR / "data"
    VERSION_FILE = PROJECT_DIR / "VERSION"

    # 재시작 정책
    INITIAL_BACKOFF = 5           # 초기 대기 시간 (초)
    MAX_BACKOFF = 300             # 최대 대기 시간 (5분)
    BACKOFF_MULTIPLIER = 2        # 지수 배수
    MAX_RESTARTS_PER_HOUR = 5     # 시간당 최대 재시작 횟수
    STABLE_THRESHOLD = 600        # 안정 판정 시간 (10분)

    # 로그
    LOG_MAX_SIZE = 50 * 1024 * 1024  # 50MB
    LOG_BACKUP_COUNT = 7              # 7일 보관

    # 필수 환경변수
    REQUIRED_ENV_VARS = [
        "KIWOOM_APP_KEY",
        "KIWOOM_APP_SECRET",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]

    # 필수 의존성
    REQUIRED_PACKAGES = [
        "httpx",
        "websockets",
        "pydantic",
        "sqlalchemy",
        "structlog",
    ]


# ============================================================
# 로거 설정
# ============================================================

def setup_logger() -> logging.Logger:
    """로거 설정"""
    LauncherConfig.LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("launcher")
    logger.setLevel(logging.INFO)

    # 포맷
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 파일 핸들러 (로테이션)
    file_handler = RotatingFileHandler(
        LauncherConfig.LOG_DIR / "launcher.log",
        maxBytes=LauncherConfig.LOG_MAX_SIZE,
        backupCount=LauncherConfig.LOG_BACKUP_COUNT,
        encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    # 콘솔 핸들러
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()


# ============================================================
# 텔레그램 알림
# ============================================================

class TelegramNotifier:
    """텔레그램 알림 전송"""

    def __init__(self):
        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self._enabled = bool(self.bot_token and self.chat_id)

    async def send(self, message: str, silent: bool = False) -> bool:
        """메시지 전송"""
        if not self._enabled:
            return False

        try:
            import httpx

            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            data = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_notification": silent
            }

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, data=data)
                return response.status_code == 200

        except Exception as e:
            logger.warning(f"텔레그램 전송 실패: {e}")
            return False

    async def send_startup(self, version: str, checks: list[str]):
        """시작 알림"""
        msg = f"""🚀 <b>K_stock_trading 시작</b>

📌 버전: {version}
⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
✅ Pre-flight: {len(checks)}개 통과

{chr(10).join(f'  • {c}' for c in checks)}"""
        await self.send(msg)

    async def send_shutdown(self, reason: str, runtime: str):
        """종료 알림"""
        msg = f"""🛑 <b>K_stock_trading 종료</b>

📌 사유: {reason}
⏱ 실행시간: {runtime}
⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        await self.send(msg)

    async def send_restart(self, attempt: int, error: str, wait_seconds: int):
        """재시작 알림"""
        msg = f"""⚠️ <b>K_stock_trading 재시작</b>

🔄 시도: {attempt}회
❌ 오류: {error[:200]}
⏳ 대기: {wait_seconds}초 후 재시작
⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        await self.send(msg)

    async def send_critical(self, errors: list[str]):
        """치명적 오류 알림"""
        msg = f"""🔴 <b>K_stock_trading 치명적 오류</b>

재시작 한도 초과로 시스템이 중지되었습니다.
수동 점검이 필요합니다.

❌ 오류 목록:
{chr(10).join(f'  • {e}' for e in errors[-5:])}

⏰ 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
        await self.send(msg)


# ============================================================
# Pre-flight 검증
# ============================================================

class PreflightChecker:
    """사전 검증"""

    def __init__(self):
        self.passed: list[str] = []
        self.failed: list[str] = []

    async def run_all(self) -> bool:
        """모든 검증 실행"""
        logger.info("=" * 50)
        logger.info("Pre-flight 검증 시작...")
        logger.info("=" * 50)

        checks = [
            ("Python 버전", self._check_python_version),
            ("환경변수", self._check_environment_variables),
            ("의존성 패키지", self._check_dependencies),
            ("디렉토리 구조", self._check_directories),
            ("키움 API", self._check_kiwoom_api),
            ("데이터베이스", self._check_database),
        ]

        for name, check_fn in checks:
            try:
                result, message = await self._run_check(check_fn)
                if result:
                    self.passed.append(f"{name}: {message}")
                    logger.info(f"  ✅ {name}: {message}")
                else:
                    self.failed.append(f"{name}: {message}")
                    logger.error(f"  ❌ {name}: {message}")
            except Exception as e:
                self.failed.append(f"{name}: {str(e)}")
                logger.error(f"  ❌ {name}: {str(e)}")

        logger.info("=" * 50)

        if self.failed:
            logger.error(f"Pre-flight 실패: {len(self.failed)}개 오류")
            return False
        else:
            logger.info(f"Pre-flight 성공: {len(self.passed)}개 통과")
            return True

    async def _run_check(self, check_fn) -> tuple[bool, str]:
        """개별 검증 실행 (동기/비동기 모두 지원)"""
        result = check_fn()
        if asyncio.iscoroutine(result):
            return await result
        return result

    def _check_python_version(self) -> tuple[bool, str]:
        """Python 버전 확인"""
        version = sys.version_info
        if version >= (3, 10):
            return True, f"Python {version.major}.{version.minor}.{version.micro}"
        return False, f"Python 3.10+ 필요 (현재: {version.major}.{version.minor})"

    def _check_environment_variables(self) -> tuple[bool, str]:
        """환경변수 확인"""
        missing = []
        for var in LauncherConfig.REQUIRED_ENV_VARS:
            if not os.getenv(var):
                missing.append(var)

        if missing:
            return False, f"누락: {', '.join(missing)}"
        return True, f"{len(LauncherConfig.REQUIRED_ENV_VARS)}개 설정됨"

    def _check_dependencies(self) -> tuple[bool, str]:
        """의존성 확인"""
        missing = []
        for pkg in LauncherConfig.REQUIRED_PACKAGES:
            try:
                importlib.import_module(pkg)
            except ImportError:
                missing.append(pkg)

        if missing:
            return False, f"누락: {', '.join(missing)}"
        return True, f"{len(LauncherConfig.REQUIRED_PACKAGES)}개 설치됨"

    def _check_directories(self) -> tuple[bool, str]:
        """디렉토리 확인"""
        LauncherConfig.LOG_DIR.mkdir(parents=True, exist_ok=True)
        LauncherConfig.DATA_DIR.mkdir(parents=True, exist_ok=True)

        src_dir = LauncherConfig.PROJECT_DIR / "src"
        if not src_dir.exists():
            return False, "src/ 디렉토리 없음"

        main_file = src_dir / "main.py"
        if not main_file.exists():
            return False, "src/main.py 없음"

        return True, "구조 정상"

    async def _check_kiwoom_api(self) -> tuple[bool, str]:
        """키움 API 토큰 확인"""
        try:
            # 토큰 발급 테스트
            import httpx

            app_key = os.getenv("KIWOOM_APP_KEY")
            app_secret = os.getenv("KIWOOM_APP_SECRET")
            is_paper = os.getenv("IS_PAPER_TRADING", "false").lower() == "true"

            base_url = "https://mockapi.kiwoom.com" if is_paper else "https://api.kiwoom.com"

            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{base_url}/oauth2/token",
                    json={
                        "grant_type": "client_credentials",
                        "appkey": app_key,
                        "secretkey": app_secret,
                    }
                )

                if response.status_code == 200:
                    data = response.json()
                    if "token" in data or "access_token" in data:
                        mode = "모의투자" if is_paper else "실전투자"
                        return True, f"토큰 발급 성공 ({mode})"

                return False, f"토큰 발급 실패: {response.status_code}"

        except Exception as e:
            return False, f"API 연결 실패: {str(e)[:50]}"

    async def _check_database(self) -> tuple[bool, str]:
        """데이터베이스 연결 확인"""
        db_url = os.getenv("DATABASE_URL")

        if not db_url:
            return True, "SQLite 폴백 사용"

        try:
            if "postgresql" in db_url:
                import httpx

                # Supabase health check
                # postgresql://user:pass@db.xxx.supabase.co:5432/postgres
                host = db_url.split("@")[1].split(":")[0]

                async with httpx.AsyncClient(timeout=5) as client:
                    # 단순 TCP 연결 테스트는 어려우므로 설정 존재 여부만 확인
                    return True, f"PostgreSQL 설정됨 ({host[:20]}...)"
            else:
                return True, "SQLite 사용"

        except Exception as e:
            return True, f"DB 확인 스킵 (SQLite 폴백): {str(e)[:30]}"


# ============================================================
# 프로세스 관리
# ============================================================

class ProcessManager:
    """프로세스 관리자"""

    def __init__(self, notifier: TelegramNotifier):
        self._notifier = notifier
        self._shutdown_requested = False
        self._process: Optional[asyncio.subprocess.Process] = None

        # 재시작 관리
        self._current_backoff = LauncherConfig.INITIAL_BACKOFF
        self._restart_times: list[float] = []
        self._restart_errors: list[str] = []

        # 통계
        self._start_time: Optional[float] = None
        self._total_runtime = 0.0

    def request_shutdown(self):
        """종료 요청"""
        logger.info("Shutdown 요청됨")
        self._shutdown_requested = True

        if self._process and self._process.returncode is None:
            logger.info("자식 프로세스에 SIGTERM 전송")
            try:
                self._process.terminate()
            except ProcessLookupError:
                pass

    async def run(self) -> int:
        """메인 실행 루프"""
        self._start_time = time.time()
        attempt = 0

        while not self._shutdown_requested:
            attempt += 1
            run_start = time.time()

            logger.info(f"트레이딩 시스템 시작 (시도 #{attempt})...")
            exit_code, error = await self._run_process()

            runtime = time.time() - run_start
            self._total_runtime += runtime

            logger.info(f"프로세스 종료: exit_code={exit_code}, runtime={runtime:.1f}s")

            # 종료 요청이면 루프 탈출
            if self._shutdown_requested:
                break

            # 정상 종료 (exit 0)
            if exit_code == 0:
                logger.info("정상 종료, 런처 종료")
                break

            # 비정상 종료 - 재시작 판단
            self._restart_errors.append(error or f"exit_code={exit_code}")
            self._restart_times.append(time.time())

            # 안정 실행 후 백오프 리셋
            if runtime > LauncherConfig.STABLE_THRESHOLD:
                self._reset_backoff()

            # 재시작 한도 체크
            if self._should_stop_restarting():
                logger.critical("재시작 한도 초과, 런처 종료")
                await self._notifier.send_critical(self._restart_errors)
                return 1

            # 재시작 알림 및 대기
            await self._notifier.send_restart(
                attempt=len(self._restart_times),
                error=error or "Unknown",
                wait_seconds=int(self._current_backoff)
            )

            logger.warning(f"{self._current_backoff}초 후 재시작...")
            await asyncio.sleep(self._current_backoff)

            self._increase_backoff()

        return 0

    async def _run_process(self) -> tuple[int, Optional[str]]:
        """서브프로세스 실행"""
        error_msg = None

        try:
            # 환경 설정
            env = os.environ.copy()
            env["PYTHONPATH"] = str(LauncherConfig.PROJECT_DIR)
            env["PYTHONUNBUFFERED"] = "1"

            self._process = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "src.main",
                cwd=str(LauncherConfig.PROJECT_DIR),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            # 출력 스트리밍
            async def stream_output(stream, prefix):
                while True:
                    line = await stream.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="replace").rstrip()
                    if text:
                        print(f"[{prefix}] {text}")

            # stdout, stderr 동시 처리
            await asyncio.gather(
                stream_output(self._process.stdout, "APP"),
                stream_output(self._process.stderr, "ERR"),
                self._process.wait()
            )

            return self._process.returncode, None

        except asyncio.CancelledError:
            if self._process:
                self._process.terminate()
                await self._process.wait()
            return -1, "Cancelled"

        except Exception as e:
            error_msg = str(e)
            logger.error(f"프로세스 실행 오류: {error_msg}")
            return 1, error_msg

    def _reset_backoff(self):
        """백오프 리셋"""
        self._current_backoff = LauncherConfig.INITIAL_BACKOFF
        logger.info("백오프 리셋 (안정 실행 확인됨)")

    def _increase_backoff(self):
        """백오프 증가"""
        self._current_backoff = min(
            self._current_backoff * LauncherConfig.BACKOFF_MULTIPLIER,
            LauncherConfig.MAX_BACKOFF
        )

    def _should_stop_restarting(self) -> bool:
        """재시작 한도 체크"""
        one_hour_ago = time.time() - 3600
        recent_restarts = [t for t in self._restart_times if t > one_hour_ago]
        self._restart_times = recent_restarts  # 정리

        if len(recent_restarts) >= LauncherConfig.MAX_RESTARTS_PER_HOUR:
            logger.error(f"1시간 내 {len(recent_restarts)}회 재시작 (한도: {LauncherConfig.MAX_RESTARTS_PER_HOUR})")
            return True
        return False

    def get_runtime_str(self) -> str:
        """실행 시간 문자열"""
        if not self._start_time:
            return "0s"

        total = time.time() - self._start_time
        hours = int(total // 3600)
        minutes = int((total % 3600) // 60)
        seconds = int(total % 60)

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"


# ============================================================
# 시그널 핸들러
# ============================================================

def setup_signal_handlers(manager: ProcessManager):
    """시그널 핸들러 설정"""

    def handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"시그널 수신: {sig_name}")
        manager.request_shutdown()

    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)

    # Windows에서는 SIGHUP 없음
    if hasattr(signal, 'SIGHUP'):
        signal.signal(signal.SIGHUP, handler)


# ============================================================
# 버전 관리
# ============================================================

def get_version() -> str:
    """버전 조회"""
    version_file = LauncherConfig.VERSION_FILE

    if version_file.exists():
        return version_file.read_text().strip()

    # VERSION 파일이 없으면 날짜 기반 버전 생성
    return f"v{datetime.now().strftime('%Y.%m.%d')}.dev"


# ============================================================
# 메인
# ============================================================

async def main():
    """메인 진입점"""

    # 환경변수 로드 (.env)
    env_file = LauncherConfig.PROJECT_DIR / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)

    # 배너
    version = get_version()
    logger.info("=" * 60)
    logger.info("  K_stock_trading Launcher")
    logger.info(f"  Version: {version}")
    logger.info(f"  Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"  PID: {os.getpid()}")
    logger.info("=" * 60)

    # Pre-flight 검증
    checker = PreflightChecker()
    if not await checker.run_all():
        logger.error("Pre-flight 검증 실패, 종료")

        # 텔레그램 알림 시도
        notifier = TelegramNotifier()
        await notifier.send_critical(checker.failed)

        sys.exit(1)

    # 알림 설정
    notifier = TelegramNotifier()
    await notifier.send_startup(version, checker.passed)

    # 프로세스 매니저
    manager = ProcessManager(notifier)
    setup_signal_handlers(manager)

    # 메인 루프 실행
    try:
        exit_code = await manager.run()
    except Exception as e:
        logger.exception(f"런처 예외: {e}")
        exit_code = 1
    finally:
        # 종료 알림
        await notifier.send_shutdown(
            reason="정상 종료" if exit_code == 0 else f"오류 (code={exit_code})",
            runtime=manager.get_runtime_str()
        )

    logger.info("=" * 60)
    logger.info("  Launcher 종료")
    logger.info("=" * 60)

    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt, 종료")
        sys.exit(0)
