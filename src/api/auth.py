"""
토큰 관리 모듈

OAuth2 토큰 발급, 갱신, 캐싱을 담당합니다.
모의투자/실전투자 인증 정보는 config에서 자동 선택됩니다.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
import asyncio
import json
import os
import stat

import httpx

from src.utils.config import get_config, AppConfig
from src.utils.logger import get_logger
from src.utils.exceptions import AuthenticationError, TokenExpiredError


@dataclass
class TokenInfo:
    """토큰 정보 컨테이너"""
    access_token: str
    token_type: str  # "bearer"
    expires_dt: datetime
    issued_at: datetime

    @property
    def is_expired(self) -> bool:
        """토큰 만료 여부"""
        return datetime.now() >= self.expires_dt

    @property
    def should_refresh(self) -> bool:
        """갱신 필요 여부 (만료 5분 전)"""
        return datetime.now() >= (self.expires_dt - timedelta(minutes=5))

    @property
    def remaining_seconds(self) -> int:
        """만료까지 남은 시간 (초)"""
        delta = self.expires_dt - datetime.now()
        return max(0, int(delta.total_seconds()))

    def to_dict(self) -> dict:
        """직렬화"""
        return {
            "access_token": self.access_token,
            "token_type": self.token_type,
            "expires_dt": self.expires_dt.isoformat(),
            "issued_at": self.issued_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TokenInfo":
        """역직렬화"""
        return cls(
            access_token=data["access_token"],
            token_type=data["token_type"],
            expires_dt=datetime.fromisoformat(data["expires_dt"]),
            issued_at=datetime.fromisoformat(data["issued_at"]),
        )


class TokenManager:
    """
    OAuth2 토큰 관리자

    기능:
    - 토큰 발급 및 자동 갱신 (만료 5분 전)
    - 디스크 캐싱 (.token_cache.json)
    - 모의/실전 자동 전환 (config 기반)

    Usage:
        token_manager = TokenManager()
        token = await token_manager.get_token()  # 자동으로 발급/갱신
    """

    # 토큰 캐시 파일 경로
    _TOKEN_FILENAME = ".token_cache.json"
    _cache_path: Optional[str] = None  # 캐싱된 경로

    @property
    def TOKEN_FILE(self) -> Optional[str]:
        """
        토큰 캐시 파일 경로 (쓰기 가능한 위치)

        우선순위:
        1. 프로젝트 루트
        2. 홈 디렉토리
        3. /tmp (Linux)
        4. None (캐시 비활성화)
        """
        # 이미 확인된 경로가 있으면 재사용
        if TokenManager._cache_path is not None:
            return TokenManager._cache_path if TokenManager._cache_path else None

        import os
        import sys

        candidates = []

        # Linux/Mac: 홈 디렉토리 우선
        if sys.platform != "win32":
            home = Path.home()
            candidates.append(home / self._TOKEN_FILENAME)
            # /tmp 폴백
            candidates.append(Path("/tmp") / self._TOKEN_FILENAME)

        # 프로젝트 루트 (절대 경로로 변환)
        project_root = Path(__file__).resolve().parent.parent.parent
        if project_root.is_dir() and str(project_root) != ".":
            candidates.append(project_root / self._TOKEN_FILENAME)

        for path in candidates:
            try:
                # 디렉토리가 아닌 파일 경로인지 확인
                if path.is_dir():
                    continue
                path.touch(exist_ok=True)
                TokenManager._cache_path = str(path)
                return TokenManager._cache_path
            except (PermissionError, OSError):
                continue

        # 모든 경로 실패 - 캐시 비활성화
        TokenManager._cache_path = ""  # 빈 문자열 = 비활성화
        return None

    TOKEN_ENDPOINT = "/oauth2/token"
    REVOKE_ENDPOINT = "/oauth2/revoke"

    def __init__(self, config: Optional[AppConfig] = None):
        self._config = config or get_config()
        self._token: Optional[TokenInfo] = None
        self._lock = asyncio.Lock()
        self._refresh_task: Optional[asyncio.Task] = None
        self._logger = get_logger(__name__)

    @property
    def _base_url(self) -> str:
        """API 베이스 URL (모의/실전 자동 선택)"""
        return self._config.settings.api_host

    @property
    def _credentials(self) -> tuple[str, str]:
        """API 인증 정보 (모의/실전 자동 선택)"""
        return self._config.get_active_credentials()

    @property
    def is_paper_trading(self) -> bool:
        """모의투자 모드 여부"""
        return self._config.settings.is_paper_trading

    async def get_token(self) -> str:
        """
        유효한 액세스 토큰 반환

        - 캐시에서 로드 시도
        - 만료되었거나 없으면 새로 발급
        - 곧 만료될 예정이면 갱신

        Returns:
            str: Bearer 토큰
        """
        async with self._lock:
            # 메모리에 없으면 캐시에서 로드
            if self._token is None:
                self._token = self._load_from_cache()

            # 만료되었거나 없으면 새로 발급
            if self._token is None or self._token.is_expired:
                await self._issue_new_token()

            # 곧 만료될 예정이면 갱신
            elif self._token.should_refresh:
                await self._issue_new_token()

            return self._token.access_token

    async def invalidate_and_refresh(self) -> str:
        """
        [P1-2] 토큰 강제 무효화 후 새로 발급

        401 Unauthorized 응답 시 클라이언트에서 호출.
        서버가 토큰을 무효화했지만 로컬 캐시에는 남아있을 때 사용.

        Returns:
            str: 새로 발급된 Bearer 토큰
        """
        async with self._lock:
            self._logger.warning("토큰 강제 갱신 요청 (401 응답)")
            self._token = None
            self._clear_cache()
            await self._issue_new_token()
            return self._token.access_token

    async def _issue_new_token(self) -> None:
        """새 토큰 발급"""
        app_key, app_secret = self._credentials

        payload = {
            "grant_type": "client_credentials",
            "appkey": app_key,
            "secretkey": app_secret,
        }

        self._logger.info(
            "토큰 발급 요청",
            base_url=self._base_url,
            is_paper=self.is_paper_trading,
        )

        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(
                    f"{self._base_url}{self.TOKEN_ENDPOINT}",
                    json=payload,
                    headers={"Content-Type": "application/json;charset=UTF-8"},
                    timeout=30.0,
                )
                response.raise_for_status()
                data = response.json()

                # 에러 응답 체크
                return_code = data.get("return_code")
                if return_code is not None and return_code != 0:
                    raise AuthenticationError(
                        f"토큰 발급 실패: {data.get('return_msg')}",
                        code=str(return_code),
                    )

                # 만료 시간 파싱: "20241107083713" -> datetime
                expires_str = data.get("expires_dt", "")
                if expires_str:
                    expires_dt = datetime.strptime(expires_str, "%Y%m%d%H%M%S")
                else:
                    # expires_in 사용 (초 단위)
                    expires_in = int(data.get("expires_in", 86400))
                    expires_dt = datetime.now() + timedelta(seconds=expires_in)

                self._token = TokenInfo(
                    access_token=data["token"],
                    token_type=data.get("token_type", "bearer"),
                    expires_dt=expires_dt,
                    issued_at=datetime.now(),
                )

                self._save_to_cache()
                self._logger.info(
                    "토큰 발급 성공",
                    expires_in_seconds=self._token.remaining_seconds,
                )

            except httpx.HTTPStatusError as e:
                self._logger.error("HTTP 에러", status_code=e.response.status_code)
                raise AuthenticationError(f"토큰 발급 HTTP 에러: {e}")
            except httpx.RequestError as e:
                self._logger.error("요청 에러", error=str(e))
                raise AuthenticationError(f"토큰 발급 요청 에러: {e}")
            except KeyError as e:
                self._logger.error("응답 파싱 에러", missing_key=str(e))
                raise AuthenticationError(f"토큰 응답 파싱 에러: {e}")

    async def revoke_token(self) -> None:
        """토큰 폐기 (선택적 정리)"""
        if self._token is None:
            return

        try:
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"{self._base_url}{self.REVOKE_ENDPOINT}",
                    json={"token": self._token.access_token},
                    headers={"Content-Type": "application/json;charset=UTF-8"},
                    timeout=10.0,
                )
        except Exception as e:
            self._logger.warning("토큰 폐기 실패", error=str(e))

        self._token = None
        self._clear_cache()

    def _load_from_cache(self) -> Optional[TokenInfo]:
        """캐시에서 토큰 로드"""
        token_file = self.TOKEN_FILE
        if token_file is None:
            return None

        cache_path = Path(token_file)
        if not cache_path.exists():
            return None

        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            token = TokenInfo.from_dict(data)

            # 만료된 토큰은 사용하지 않음
            if token.is_expired:
                self._clear_cache()
                return None

            self._logger.debug(
                "캐시에서 토큰 로드",
                remaining_seconds=token.remaining_seconds,
            )
            return token

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self._logger.warning("캐시 로드 실패", error=str(e))
            self._clear_cache()
            return None

    def _save_to_cache(self) -> None:
        """토큰을 캐시에 저장 (보안: 600 권한 설정)"""
        if self._token is None:
            return

        token_file = self.TOKEN_FILE
        if token_file is None:
            return  # 캐시 비활성화

        try:
            cache_path = Path(token_file)
            cache_path.write_text(
                json.dumps(self._token.to_dict(), indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            # [P0-1] 보안: 소유자만 읽기/쓰기 가능 (chmod 600)
            # Windows에서는 무시됨 (ACL 사용)
            if os.name != "nt":
                os.chmod(cache_path, stat.S_IRUSR | stat.S_IWUSR)
        except (PermissionError, OSError) as e:
            self._logger.warning(f"토큰 캐시 저장 실패 (무시): {e}")

    def _clear_cache(self) -> None:
        """캐시 파일 삭제"""
        token_file = self.TOKEN_FILE
        if token_file is None:
            return

        try:
            cache_path = Path(token_file)
            if cache_path.exists():
                cache_path.unlink()
        except (PermissionError, OSError):
            pass  # 삭제 실패 무시

    async def start_auto_refresh(self) -> None:
        """백그라운드 자동 갱신 시작"""
        if self._refresh_task is not None:
            return

        self._refresh_task = asyncio.create_task(self._auto_refresh_loop())
        self._logger.info("토큰 자동 갱신 시작")

    async def stop_auto_refresh(self) -> None:
        """백그라운드 자동 갱신 중지"""
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass
            self._refresh_task = None
            self._logger.info("토큰 자동 갱신 중지")

    async def _auto_refresh_loop(self) -> None:
        """토큰 자동 갱신 루프"""
        while True:
            try:
                if self._token and self._token.should_refresh:
                    await self.get_token()

                # 1분마다 체크
                await asyncio.sleep(60)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self._logger.error("자동 갱신 에러", error=str(e))
                await asyncio.sleep(60)


# 싱글톤 인스턴스
_token_manager: Optional[TokenManager] = None


def get_token_manager() -> TokenManager:
    """싱글톤 TokenManager 인스턴스 반환"""
    global _token_manager
    if _token_manager is None:
        _token_manager = TokenManager()
    return _token_manager
