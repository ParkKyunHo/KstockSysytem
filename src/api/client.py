"""
키움증권 REST API HTTP 클라이언트

비동기 HTTP 클라이언트로 Rate Limiting, 재시도, 에러 처리를 제공합니다.
"""

from dataclasses import dataclass, field
from typing import Any, Optional
import asyncio
import time

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from src.api.auth import TokenManager, get_token_manager
from src.utils.config import get_config, AppConfig
from src.utils.logger import get_logger
from src.utils.exceptions import (
    APIError,
    RateLimitError,
    APIResponseError,
    CircuitBreakerOpenError,
)


from enum import Enum


class CircuitState(str, Enum):
    """Circuit Breaker 상태"""
    CLOSED = "CLOSED"      # 정상 (요청 허용)
    OPEN = "OPEN"          # 차단 (요청 거부)
    HALF_OPEN = "HALF_OPEN"  # 테스트 (제한적 요청)


@dataclass
class CircuitBreaker:
    """
    API Circuit Breaker

    연속 실패 시 자동으로 요청을 차단하여 시스템 안정성을 보호합니다.

    상태 전이:
    - CLOSED: 정상 상태, 모든 요청 허용
    - OPEN: 연속 실패 임계치 초과, 모든 요청 차단
    - HALF_OPEN: 복구 타임아웃 후, 테스트 요청 허용

    Usage:
        cb = CircuitBreaker()
        if cb.can_request():
            try:
                result = await api_call()
                cb.on_success()
            except Exception:
                cb.on_failure()
        else:
            raise CircuitBreakerOpenError()
    """
    failure_threshold: int = 5       # 연속 실패 임계치
    recovery_timeout: float = 60.0   # 복구 대기 시간 (초)

    # 내부 상태 (field(init=False)로 초기화 제외)
    _state: CircuitState = field(default=CircuitState.CLOSED, init=False)
    _failure_count: int = field(default=0, init=False)
    _last_failure_time: float = field(default=0.0, init=False)
    _half_open_success: bool = field(default=False, init=False)

    @property
    def state(self) -> CircuitState:
        """현재 상태 (시간에 따라 자동 전이)"""
        if self._state == CircuitState.OPEN:
            # 복구 타임아웃 경과 시 HALF_OPEN으로 전이
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_success = False
        return self._state

    def can_request(self) -> bool:
        """요청 가능 여부 (HALF_OPEN은 단일 요청만 허용)"""
        current_state = self.state
        if current_state == CircuitState.CLOSED:
            return True
        if current_state == CircuitState.HALF_OPEN:
            if not self._half_open_success:
                # HALF_OPEN 진입 후 첫 요청만 허용
                self._half_open_success = True
                return True
            return False
        return False

    def on_success(self) -> None:
        """요청 성공 시 호출"""
        if self._state == CircuitState.HALF_OPEN:
            # HALF_OPEN에서 성공 시 CLOSED로 복구
            self._state = CircuitState.CLOSED
            self._failure_count = 0
        elif self._state == CircuitState.CLOSED:
            # 연속 실패 카운트 리셋
            self._failure_count = 0

    def on_failure(self) -> None:
        """요청 실패 시 호출"""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            # HALF_OPEN에서 실패 시 다시 OPEN
            self._state = CircuitState.OPEN
        elif self._failure_count >= self.failure_threshold:
            # 임계치 초과 시 OPEN으로 전이
            self._state = CircuitState.OPEN

    def reset(self) -> None:
        """상태 초기화"""
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time = 0.0


@dataclass
class APIResponse:
    """표준화된 API 응답 래퍼"""
    success: bool
    data: Optional[dict] = None
    return_code: int = 0
    return_msg: str = ""

    # 페이지네이션
    has_next: bool = False
    next_key: Optional[str] = None

    # 메타데이터
    api_id: str = ""
    raw_response: Optional[dict] = None


class RateLimiter:
    """
    Token Bucket Rate Limiter

    키움 API는 호출 간 0.3초 간격 필요
    """

    def __init__(self, calls_per_second: float = 3.0):
        """
        Args:
            calls_per_second: 초당 최대 호출 수 (기본 3.0 = 0.33초 간격)
        """
        self._min_interval = 1.0 / calls_per_second
        self._last_call: float = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """다음 호출 가능할 때까지 대기"""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_call

            if elapsed < self._min_interval:
                wait_time = self._min_interval - elapsed
                await asyncio.sleep(wait_time)

            self._last_call = time.monotonic()


class KiwoomAPIClient:
    """
    키움증권 REST API 비동기 HTTP 클라이언트

    기능:
    - 자동 토큰 관리
    - Rate Limiting (0.3초 간격)
    - 지수 백오프 재시도 (최대 3회)
    - 401 자동 처리 (토큰 갱신)
    - 페이지네이션 지원

    Usage:
        async with KiwoomAPIClient() as client:
            response = await client.post(
                url="/api/dostk/acnt",
                api_id="kt00001",
                body={"qry_tp": "3"},
            )
    """

    # API URL 경로
    ACCOUNT_URL = "/api/dostk/acnt"
    ORDER_URL = "/api/dostk/ordr"
    MARKET_URL = "/api/dostk/mrkcond"
    STOCK_INFO_URL = "/api/dostk/stkinfo"

    def __init__(
        self,
        config: Optional[AppConfig] = None,
        token_manager: Optional[TokenManager] = None,
    ):
        self._config = config or get_config()
        self._token_manager = token_manager or get_token_manager()
        # 모의투자: 3초에 1회 (429 에러 방지), 실전투자: 초당 4.5회 (키움 제한 5회)
        calls_per_second = 0.33 if self._config.settings.is_paper_trading else 4.5
        self._rate_limiter = RateLimiter(calls_per_second=calls_per_second)
        self._circuit_breaker = CircuitBreaker()
        self._client: Optional[httpx.AsyncClient] = None
        self._logger = get_logger(__name__)

    @property
    def _base_url(self) -> str:
        """API 베이스 URL (모의/실전 자동 선택)"""
        return self._config.settings.api_host

    @property
    def is_paper_trading(self) -> bool:
        """모의투자 모드 여부"""
        return self._config.settings.is_paper_trading

    async def __aenter__(self) -> "KiwoomAPIClient":
        """비동기 컨텍스트 매니저 진입"""
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            headers={"Content-Type": "application/json;charset=UTF-8"},
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """비동기 컨텍스트 매니저 종료"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get_auth_headers(self, api_id: str) -> dict:
        """인증 헤더 생성"""
        token = await self._token_manager.get_token()
        return {
            "api-id": api_id,
            "authorization": f"Bearer {token}",
        }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.RequestError, httpx.HTTPStatusError, RateLimitError)),
        reraise=True,
    )
    async def _request(
        self,
        method: str,
        url: str,
        api_id: str,
        body: Optional[dict] = None,
        cont_yn: Optional[str] = None,
        next_key: Optional[str] = None,
    ) -> APIResponse:
        """
        API 요청 (재시도 및 Rate Limiting 포함)

        Args:
            method: HTTP 메서드 (GET, POST)
            url: API 엔드포인트 경로
            api_id: 키움 API ID (예: "kt00001")
            body: 요청 본문
            cont_yn: 연속조회 여부
            next_key: 연속조회 키
        """
        if self._client is None:
            raise APIError("클라이언트 미초기화. async with 사용 필요")

        # Circuit Breaker 체크
        if not self._circuit_breaker.can_request():
            self._logger.warning(
                "Circuit Breaker OPEN - 요청 차단",
                state=self._circuit_breaker.state.value,
            )
            raise CircuitBreakerOpenError()

        # Rate Limiting
        await self._rate_limiter.acquire()

        # 헤더 구성
        headers = await self._get_auth_headers(api_id)
        if cont_yn:
            headers["cont-yn"] = cont_yn
        if next_key:
            headers["next-key"] = next_key

        self._logger.debug(
            "API 요청",
            method=method,
            url=url,
            api_id=api_id,
            is_paper=self.is_paper_trading,
        )

        try:
            response = await self._client.request(
                method=method,
                url=url,
                json=body,
                headers=headers,
            )

            # [P1-2] 401 처리 - 토큰 강제 무효화 후 재시도
            # 서버가 토큰을 무효화했을 수 있으므로 캐시 비우고 새로 발급
            if response.status_code == 401:
                self._logger.warning("401 Unauthorized - 토큰 강제 갱신 중...")
                await self._token_manager.invalidate_and_refresh()

                headers = await self._get_auth_headers(api_id)
                if cont_yn:
                    headers["cont-yn"] = cont_yn
                if next_key:
                    headers["next-key"] = next_key

                response = await self._client.request(
                    method=method,
                    url=url,
                    json=body,
                    headers=headers,
                )

            # 429 처리 - Rate Limit (tenacity에서 자동 재시도)
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 1))
                self._logger.warning(
                    f"Rate Limit 도달 (429), {retry_after}초 후 재시도",
                    api_id=api_id,
                    retry_after=retry_after,
                )
                # Retry-After 시간만큼 대기 후 재시도
                await asyncio.sleep(retry_after)
                raise RateLimitError(retry_after=retry_after)

            response.raise_for_status()
            data = response.json()

            # 키움 return_code 확인
            return_code = data.get("return_code", 0)
            return_msg = data.get("return_msg", "")

            # [8005] 토큰 무효 에러 - 토큰 갱신 후 재시도
            if return_code != 0 and "8005" in return_msg:
                self._logger.warning("토큰 무효(8005) - 토큰 강제 갱신 중...")
                await self._token_manager.invalidate_and_refresh()

                headers = await self._get_auth_headers(api_id)
                if cont_yn:
                    headers["cont-yn"] = cont_yn
                if next_key:
                    headers["next-key"] = next_key

                response = await self._client.request(
                    method=method,
                    url=url,
                    json=body,
                    headers=headers,
                )
                response.raise_for_status()
                data = response.json()
                return_code = data.get("return_code", 0)
                return_msg = data.get("return_msg", "")

            if return_code != 0:
                self._logger.error(
                    "API 에러 응답",
                    api_id=api_id,
                    return_code=return_code,
                    return_msg=return_msg,
                )
                raise APIResponseError(
                    message=return_msg,
                    status_code=response.status_code,
                    response_body=data,
                )

            # 페이지네이션 정보 파싱
            resp_headers = response.headers
            has_next = resp_headers.get("cont-yn", "N") == "Y"
            next_key_value = resp_headers.get("next-key")

            # Circuit Breaker 성공 기록
            self._circuit_breaker.on_success()

            return APIResponse(
                success=True,
                data=data,
                return_code=return_code,
                return_msg=return_msg,
                has_next=has_next,
                next_key=next_key_value,
                api_id=api_id,
                raw_response=data,
            )

        except httpx.HTTPStatusError as e:
            self._circuit_breaker.on_failure()
            self._logger.error("HTTP 에러", status_code=e.response.status_code, url=url)
            raise APIResponseError(
                message=str(e),
                status_code=e.response.status_code,
            )
        except httpx.RequestError as e:
            self._circuit_breaker.on_failure()
            self._logger.error("요청 에러", error=str(e), url=url)
            raise APIError(f"요청 실패: {e}")

    async def post(
        self,
        url: str,
        api_id: str,
        body: dict,
        **kwargs,
    ) -> APIResponse:
        """POST 요청"""
        return await self._request("POST", url, api_id, body=body, **kwargs)

    async def get(
        self,
        url: str,
        api_id: str,
        body: Optional[dict] = None,
        **kwargs,
    ) -> APIResponse:
        """GET 요청 (키움 API는 대부분 POST 사용)"""
        return await self._request("POST", url, api_id, body=body, **kwargs)

    async def paginate(
        self,
        url: str,
        api_id: str,
        body: dict,
        max_pages: int = 10,
    ) -> list[dict]:
        """
        페이지네이션 데이터 전체 조회

        Args:
            url: API 엔드포인트
            api_id: 키움 API ID
            body: 요청 본문
            max_pages: 최대 페이지 수 (안전 제한)

        Returns:
            모든 페이지의 데이터 리스트
        """
        all_data = []
        cont_yn = None
        next_key = None

        for page in range(max_pages):
            response = await self._request(
                "POST", url, api_id, body=body,
                cont_yn=cont_yn, next_key=next_key,
            )

            if response.data:
                all_data.append(response.data)

            if not response.has_next:
                break

            cont_yn = "Y"
            next_key = response.next_key

            self._logger.debug(f"페이지 {page + 2} 조회 중...")

        return all_data


# 싱글톤 팩토리
_api_client: Optional[KiwoomAPIClient] = None


async def get_api_client() -> KiwoomAPIClient:
    """API 클라이언트 인스턴스 반환"""
    global _api_client
    if _api_client is None:
        _api_client = KiwoomAPIClient()
    return _api_client
