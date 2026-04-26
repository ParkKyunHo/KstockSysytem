# V7.1 스킬 명세 (Skills Spec)

> 이 문서는 V7.1 시스템의 **8개 표준 스킬**을 정의합니다.
> 
> 스킬은 반복 작업의 **표준 프로시저**이며, Claude Code가 코드 작성 시 강제로 사용해야 합니다.
> 
> 직접 구현 금지 → 스킬 사용 의무 → 하네스가 강제

---

## 목차

- [§0. 스킬 개요](#0-스킬-개요)
- [§1. 스킬 1: kiwoom_api_skill](#1-스킬-1-kiwoom_api_skill)
- [§2. 스킬 2: box_entry_skill](#2-스킬-2-box_entry_skill)
- [§3. 스킬 3: exit_calc_skill](#3-스킬-3-exit_calc_skill)
- [§4. 스킬 4: avg_price_skill](#4-스킬-4-avg_price_skill)
- [§5. 스킬 5: vi_skill](#5-스킬-5-vi_skill)
- [§6. 스킬 6: notification_skill](#6-스킬-6-notification_skill)
- [§7. 스킬 7: reconciliation_skill](#7-스킬-7-reconciliation_skill)
- [§8. 스킬 8: test_template](#8-스킬-8-test_template)
- [§9. 스킬 사용 강제 메커니즘](#9-스킬-사용-강제-메커니즘)

---

## §0. 스킬 개요

### 0.1 스킬이란

```yaml
정의:
  반복 작업의 표준 프로시저
  특정 작업을 일관된 방식으로 수행하는 표준 함수/패턴

목적:
  - 일관성 (Claude Code가 매번 같은 방식)
  - 안전성 (룰 위반 차단)
  - 가독성 (한눈에 의도 파악)
  - 재사용 (DRY)

특징:
  - 순수 함수 (가능한 한)
  - 부수 효과 명시적
  - 타입 힌트 완전
  - Docstring 완전
  - 단위 테스트 100%
```

### 0.2 V7.1 스킬 8개

```yaml
1. kiwoom_api_skill
   목적: 키움 API 호출 표준
   위치: src/core/v71/skills/kiwoom_api_skill.py

2. box_entry_skill
   목적: 박스 진입 조건 판정
   위치: src/core/v71/skills/box_entry_skill.py

3. exit_calc_skill
   목적: 손절/익절/TS 계산
   위치: src/core/v71/skills/exit_calc_skill.py

4. avg_price_skill
   목적: 평단가 관리
   위치: src/core/v71/skills/avg_price_skill.py

5. vi_skill
   목적: VI 상태 처리
   위치: src/core/v71/skills/vi_skill.py

6. notification_skill
   목적: 알림 발송 표준
   위치: src/core/v71/skills/notification_skill.py

7. reconciliation_skill
   목적: 포지션 정합성 확인
   위치: src/core/v71/skills/reconciliation_skill.py

8. test_template
   목적: 테스트 작성 표준 패턴
   위치: src/core/v71/skills/test_template.py
   (테스트 파일이 따라야 할 템플릿)
```

### 0.3 스킬 작성 원칙

```yaml
원칙 1: 순수 함수 우선
  부수 효과 최소화
  반환값 명확
  멱등성 (가능한 곳)

원칙 2: 입력 검증
  모든 입력 검증
  None, NaN, 0, 음수 처리
  명시적 에러 발생

원칙 3: 매직 넘버 없음
  V71Constants 사용
  상수 직접 사용 금지

원칙 4: 단일 책임
  하나의 스킬은 하나의 일
  복잡한 로직 분리

원칙 5: 테스트 가능
  의존성 주입
  Mock 가능
  100% 커버리지 목표
```

### 0.4 강제 사용 (하네스 3)

```yaml
하네스 3 (Trading Rule Enforcer)가 강제:
  
  금지 패턴 (자동 차단):
    - 매직 넘버 (-0.05, 0.30 등)
    - raw API 호출 (httpx.post)
    - raw telegram.send_message()
    - 평단가 직접 수정 (position.avg = ...)
    - 직접 손절선 계산
  
  허용 패턴:
    - V71Constants 상수 사용
    - 스킬 함수 호출
    - 스킬 통한 간접 작업
```

---

## §1. 스킬 1: kiwoom_api_skill

### 1.1 목적

```yaml
모든 키움 API 호출의 일관된 패턴:
  - Rate Limiter 통과 (초당 4.5회)
  - OAuth 토큰 자동 갱신
  - 재시도 (3회, 지수 백오프)
  - 타임아웃 (10초)
  - 구조화 로깅
  - 에러 표준화
```

### 1.2 모듈 구조

```python
# src/core/v71/skills/kiwoom_api_skill.py

"""
키움 API 호출 표준 스킬.

모든 키움 API 호출은 이 모듈을 통해서만 가능합니다.
직접 httpx.post() 등의 호출은 하네스 3에 의해 차단됩니다.
"""

from typing import Any, Optional
from dataclasses import dataclass
from enum import Enum

from src.api.client import KiwoomAPIClient
from src.api.auth import OAuthManager
from src.api.rate_limiter import KiwoomRateLimiter
from src.utils.logger import get_logger
from src.core.v71.v71_constants import V71Constants

logger = get_logger(__name__)


class KiwoomAPIError(Exception):
    """키움 API 에러 기본."""
    pass


class KiwoomRateLimitError(KiwoomAPIError):
    """Rate Limit 초과."""
    pass


class KiwoomAuthError(KiwoomAPIError):
    """인증 오류 (토큰 만료 등)."""
    pass


class KiwoomTimeoutError(KiwoomAPIError):
    """타임아웃."""
    pass


@dataclass(frozen=True)
class KiwoomAPIRequest:
    """키움 API 요청."""
    endpoint: str        # "/api/dostk/ordr"
    method: str          # "POST" or "GET"
    api_id: str          # "kt10000" 등
    payload: dict
    timeout_seconds: int = 10


@dataclass(frozen=True)
class KiwoomAPIResponse:
    """키움 API 응답 표준."""
    success: bool
    data: Optional[dict]
    error_code: Optional[str]
    error_message: Optional[str]
    raw_response: dict
    duration_ms: int
```

### 1.3 핵심 함수

```python
async def call_kiwoom_api(
    client: KiwoomAPIClient,
    auth_manager: OAuthManager,
    rate_limiter: KiwoomRateLimiter,
    request: KiwoomAPIRequest,
) -> KiwoomAPIResponse:
    """
    키움 API 호출 표준.
    
    Args:
        client: 키움 API 클라이언트 (V7.0 인프라)
        auth_manager: OAuth 토큰 관리자
        rate_limiter: Rate Limiter (초당 4.5회)
        request: API 요청 객체
    
    Returns:
        KiwoomAPIResponse: 표준화된 응답
    
    Raises:
        KiwoomTimeoutError: 타임아웃
        KiwoomRateLimitError: Rate Limit 초과 (3회 재시도 후)
        KiwoomAuthError: 인증 실패
        KiwoomAPIError: 기타 API 에러
    
    Example:
        >>> response = await call_kiwoom_api(
        ...     client=kiwoom_client,
        ...     auth_manager=auth,
        ...     rate_limiter=rate_limiter,
        ...     request=KiwoomAPIRequest(
        ...         endpoint="/api/dostk/ordr",
        ...         method="POST",
        ...         api_id="kt10000",
        ...         payload={"stock_code": "005930", "qty": 100, ...}
        ...     )
        ... )
        >>> if response.success:
        ...     print(response.data)
    """
    import time
    
    start_time = time.perf_counter()
    
    # 1. Rate Limiter 통과
    async with rate_limiter.acquire():
        # 2. 토큰 검증/갱신
        token = await auth_manager.get_valid_token()
        
        # 3. 재시도 루프
        last_error = None
        for attempt in range(V71Constants.API_MAX_RETRIES):
            try:
                # 4. 실제 API 호출
                raw_response = await client.request(
                    method=request.method,
                    endpoint=request.endpoint,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "api-id": request.api_id,
                        "Content-Type": "application/json;charset=UTF-8",
                    },
                    json=request.payload,
                    timeout=request.timeout_seconds,
                )
                
                # 5. 응답 검증
                if raw_response.get("rt_cd") == "0":  # 성공 코드
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    
                    logger.info(
                        "kiwoom_api_success",
                        api_id=request.api_id,
                        endpoint=request.endpoint,
                        duration_ms=duration_ms,
                        attempt=attempt + 1,
                    )
                    
                    return KiwoomAPIResponse(
                        success=True,
                        data=raw_response.get("output"),
                        error_code=None,
                        error_message=None,
                        raw_response=raw_response,
                        duration_ms=duration_ms,
                    )
                
                # 6. 에러 분류
                error_code = raw_response.get("msg_cd", "UNKNOWN")
                error_message = raw_response.get("msg1", "")
                
                # 7. 토큰 만료 → 갱신 후 재시도
                if error_code in V71Constants.AUTH_ERROR_CODES:
                    logger.warning(
                        "kiwoom_api_auth_error",
                        api_id=request.api_id,
                        error_code=error_code,
                        attempt=attempt + 1,
                    )
                    token = await auth_manager.refresh_token()
                    last_error = KiwoomAuthError(error_message)
                    continue  # 재시도
                
                # 8. Rate Limit → 백오프 후 재시도
                if error_code in V71Constants.RATE_LIMIT_ERROR_CODES:
                    backoff = V71Constants.API_BACKOFF_BASE * (2 ** attempt)
                    logger.warning(
                        "kiwoom_api_rate_limit",
                        api_id=request.api_id,
                        backoff_seconds=backoff,
                        attempt=attempt + 1,
                    )
                    await asyncio.sleep(backoff)
                    last_error = KiwoomRateLimitError(error_message)
                    continue
                
                # 9. 비즈니스 에러 (재시도 안 함)
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                logger.error(
                    "kiwoom_api_business_error",
                    api_id=request.api_id,
                    error_code=error_code,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
                return KiwoomAPIResponse(
                    success=False,
                    data=None,
                    error_code=error_code,
                    error_message=error_message,
                    raw_response=raw_response,
                    duration_ms=duration_ms,
                )
            
            except asyncio.TimeoutError as e:
                logger.warning(
                    "kiwoom_api_timeout",
                    api_id=request.api_id,
                    timeout=request.timeout_seconds,
                    attempt=attempt + 1,
                )
                last_error = KiwoomTimeoutError(str(e))
                # 백오프 후 재시도
                await asyncio.sleep(V71Constants.API_BACKOFF_BASE * (2 ** attempt))
            
            except Exception as e:
                logger.error(
                    "kiwoom_api_unexpected_error",
                    api_id=request.api_id,
                    error=str(e),
                    error_type=type(e).__name__,
                )
                last_error = KiwoomAPIError(str(e))
                await asyncio.sleep(V71Constants.API_BACKOFF_BASE * (2 ** attempt))
        
        # 10. 모든 재시도 실패
        duration_ms = int((time.perf_counter() - start_time) * 1000)
        logger.error(
            "kiwoom_api_all_retries_failed",
            api_id=request.api_id,
            duration_ms=duration_ms,
            last_error=str(last_error),
        )
        raise last_error or KiwoomAPIError("All retries failed")
```

### 1.4 편의 함수 (자주 쓰는 패턴)

```python
async def send_buy_order(
    api_context: KiwoomAPIContext,
    stock_code: str,
    quantity: int,
    price: int,
    order_type: str = "LIMIT",  # "LIMIT" or "MARKET"
) -> KiwoomAPIResponse:
    """
    매수 주문 발송.
    
    Args:
        api_context: API 호출 컨텍스트 (client, auth, rate_limiter)
        stock_code: 종목 코드
        quantity: 매수 수량
        price: 지정가 (LIMIT인 경우)
        order_type: 주문 타입
    
    Returns:
        KiwoomAPIResponse
    """
    payload = {
        "stk_cd": stock_code,
        "ord_qty": quantity,
        "ord_uprc": price if order_type == "LIMIT" else 0,
        "ord_dvsn": "00" if order_type == "LIMIT" else "01",
        "trad_dvsn": "01",  # 매수
    }
    
    return await call_kiwoom_api(
        client=api_context.client,
        auth_manager=api_context.auth_manager,
        rate_limiter=api_context.rate_limiter,
        request=KiwoomAPIRequest(
            endpoint="/api/dostk/ordr",
            method="POST",
            api_id="kt10000",
            payload=payload,
        )
    )


async def send_sell_order(...) -> KiwoomAPIResponse:
    """매도 주문 발송."""
    ...


async def cancel_order(...) -> KiwoomAPIResponse:
    """주문 취소."""
    ...


async def get_position(...) -> KiwoomAPIResponse:
    """포지션 조회."""
    ...


async def get_balance(...) -> KiwoomAPIResponse:
    """계좌 잔고 조회."""
    ...


async def get_order_status(...) -> KiwoomAPIResponse:
    """주문 상태 조회."""
    ...
```

### 1.5 V71Constants 상수

```python
# src/core/v71/v71_constants.py 일부

class V71Constants:
    # API 호출
    API_MAX_RETRIES = 3
    API_BACKOFF_BASE = 1.0  # 초
    API_TIMEOUT_SECONDS = 10
    
    # 에러 코드
    AUTH_ERROR_CODES = ["EGW00001", "EGW00002"]  # 토큰 만료, 인증 실패
    RATE_LIMIT_ERROR_CODES = ["EGW00201"]  # Rate Limit
```

### 1.6 단위 테스트

```python
# tests/v71/test_skills/test_kiwoom_api.py

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.core.v71.skills.kiwoom_api_skill import (
    call_kiwoom_api,
    KiwoomAPIRequest,
    KiwoomAuthError,
    KiwoomRateLimitError,
)


@pytest.fixture
def mock_client():
    return AsyncMock()


@pytest.fixture
def mock_auth():
    auth = AsyncMock()
    auth.get_valid_token.return_value = "fake_token"
    return auth


@pytest.fixture
def mock_rate_limiter():
    limiter = MagicMock()
    limiter.acquire = MagicMock()
    return limiter


@pytest.mark.asyncio
async def test_successful_call(mock_client, mock_auth, mock_rate_limiter):
    """정상 응답."""
    # Given
    mock_client.request.return_value = {
        "rt_cd": "0",
        "output": {"order_id": "ORDER123"},
    }
    
    # When
    response = await call_kiwoom_api(
        client=mock_client,
        auth_manager=mock_auth,
        rate_limiter=mock_rate_limiter,
        request=KiwoomAPIRequest(
            endpoint="/test", method="POST", api_id="test", payload={}
        ),
    )
    
    # Then
    assert response.success is True
    assert response.data == {"order_id": "ORDER123"}


@pytest.mark.asyncio
async def test_token_expired_retry(mock_client, mock_auth, mock_rate_limiter):
    """토큰 만료 → 갱신 → 재시도 → 성공."""
    # Given: 첫 호출은 인증 실패, 두 번째는 성공
    mock_client.request.side_effect = [
        {"rt_cd": "1", "msg_cd": "EGW00001", "msg1": "Token expired"},
        {"rt_cd": "0", "output": {"data": "ok"}},
    ]
    
    # When
    response = await call_kiwoom_api(
        client=mock_client,
        auth_manager=mock_auth,
        rate_limiter=mock_rate_limiter,
        request=KiwoomAPIRequest(...),
    )
    
    # Then
    assert response.success is True
    mock_auth.refresh_token.assert_called_once()


@pytest.mark.asyncio
async def test_rate_limit_backoff(...):
    """Rate Limit → 백오프 → 재시도."""
    ...


@pytest.mark.asyncio
async def test_timeout(...):
    """타임아웃."""
    ...


@pytest.mark.asyncio
async def test_all_retries_failed(...):
    """3회 모두 실패 → 예외."""
    ...
```

### 1.7 사용 예시 (실제 코드)

```python
# 잘못된 예 (하네스 3 차단)
import httpx

async def buy_stock_bad():
    # ❌ 직접 httpx 사용 → 차단
    response = await httpx.post(
        "https://api.kiwoom.com/api/dostk/ordr",
        json={...}
    )

# 올바른 예 (스킬 사용)
from src.core.v71.skills.kiwoom_api_skill import send_buy_order

async def buy_stock_good(api_context, stock_code, qty, price):
    # ✅ 스킬 사용 → 통과
    response = await send_buy_order(
        api_context=api_context,
        stock_code=stock_code,
        quantity=qty,
        price=price,
    )
    if response.success:
        return response.data["order_id"]
    else:
        raise OrderFailedError(response.error_message)
```

---

## §2. 스킬 2: box_entry_skill

### 2.1 목적

```yaml
박스 진입 조건의 일관된 판정:
  - 눌림 (PULLBACK)
  - 돌파 (BREAKOUT)
  - 경로 A (3분봉) / 경로 B (일봉) 모두 지원
  - VI 봉 그대로 판정
  - 엣지 케이스 처리
```

### 2.2 모듈 구조

```python
# src/core/v71/skills/box_entry_skill.py

"""
박스 진입 조건 판정 스킬.

02_TRADING_RULES.md §3.8~§3.11 룰 정확히 구현.
모든 박스 진입 판정은 이 스킬을 통해서만 가능.
"""

from typing import Optional, Literal
from dataclasses import dataclass
from datetime import datetime

from src.core.v71.v71_constants import V71Constants


@dataclass(frozen=True)
class Candle:
    """봉 데이터."""
    timestamp: datetime
    open_price: int
    high_price: int
    low_price: int
    close_price: int
    volume: int
    
    @property
    def is_bullish(self) -> bool:
        """양봉 여부 (Close > Open)."""
        return self.close_price > self.open_price


@dataclass(frozen=True)
class Box:
    """박스 정보 (스킬 사용 한정 minimal struct)."""
    upper_price: int
    lower_price: int
    strategy_type: Literal["PULLBACK", "BREAKOUT"]
    path_type: Literal["PATH_A", "PATH_B"]


@dataclass(frozen=True)
class MarketContext:
    """시장 컨텍스트."""
    is_vi_recovered_today: bool  # 당일 VI 복구 후
    is_vi_active: bool           # 현재 VI 발동 중
    is_market_open: bool         # 정규장 진행 중
    current_time: datetime


@dataclass(frozen=True)
class EntryDecision:
    """진입 판정 결과."""
    should_enter: bool
    reason: str  # 진입 / 거부 사유
    box_id: Optional[str]
    expected_buy_price: Optional[int]  # 예상 매수가
    expected_buy_at: Optional[datetime]  # 예상 매수 시각 (경로 B는 익일 09:01)
    
    # 안전장치 메타데이터 (경로 B 전용, 02_TRADING_RULES.md §3.10/§3.11/§10.9)
    fallback_buy_at: Optional[datetime] = None  # 1차 실패 시 fallback 시각 (09:05)
    fallback_uses_market_order: bool = False    # fallback 시점 시장가 강제 여부
    fallback_gap_recheck_required: bool = False # fallback 시점 갭업 5% 재검증 필요 여부
```

### 2.3 핵심 함수

```python
def evaluate_box_entry(
    box: Box,
    current_candle: Candle,
    previous_candle: Optional[Candle],
    market_context: MarketContext,
) -> EntryDecision:
    """
    박스 진입 조건 평가.
    
    Args:
        box: 박스 정보
        current_candle: 현재 봉 (방금 완성된)
        previous_candle: 직전 봉 (PULLBACK 룰에 필요)
        market_context: 시장 컨텍스트 (VI 등)
    
    Returns:
        EntryDecision: 진입 판정 결과
    
    Raises:
        ValueError: 입력 검증 실패
    
    Example:
        >>> decision = evaluate_box_entry(
        ...     box=my_box,
        ...     current_candle=latest_candle,
        ...     previous_candle=prev_candle,
        ...     market_context=ctx,
        ... )
        >>> if decision.should_enter:
        ...     await execute_buy(box, decision.expected_buy_price)
    """
    # 1. 입력 검증
    _validate_inputs(box, current_candle, previous_candle, market_context)
    
    # 2. 시장 상태 체크
    if not market_context.is_market_open:
        return EntryDecision(
            should_enter=False,
            reason="MARKET_CLOSED",
            box_id=None,
            expected_buy_price=None,
            expected_buy_at=None,
        )
    
    # 3. VI 발동 중이면 별도 처리 (vi_skill에서 단일가 매매)
    if market_context.is_vi_active:
        return EntryDecision(
            should_enter=False,
            reason="VI_ACTIVE_USE_VI_SKILL",
            box_id=None,
            expected_buy_price=None,
            expected_buy_at=None,
        )
    
    # 4. 당일 VI 복구 후 신규 진입 금지
    if market_context.is_vi_recovered_today:
        return EntryDecision(
            should_enter=False,
            reason="VI_RECOVERED_TODAY_BLOCKED",
            box_id=None,
            expected_buy_price=None,
            expected_buy_at=None,
        )
    
    # 5. 전략별 분기
    if box.strategy_type == "PULLBACK":
        return _evaluate_pullback(box, current_candle, previous_candle, market_context)
    elif box.strategy_type == "BREAKOUT":
        return _evaluate_breakout(box, current_candle, market_context)
    else:
        raise ValueError(f"Unknown strategy type: {box.strategy_type}")


def _validate_inputs(
    box: Box,
    current: Candle,
    previous: Optional[Candle],
    context: MarketContext,
) -> None:
    """입력 검증."""
    if box.upper_price <= box.lower_price:
        raise ValueError("Box upper_price must be > lower_price")
    if current.close_price <= 0:
        raise ValueError("Invalid candle close_price")
    if box.strategy_type == "PULLBACK" and previous is None:
        raise ValueError("PULLBACK requires previous candle")


def _evaluate_pullback(
    box: Box,
    current: Candle,
    previous: Candle,
    context: MarketContext,
) -> EntryDecision:
    """
    눌림 판정.
    
    경로 A (3분봉):
      조건 1 (직전 봉): 양봉 + 박스 내 종가
      조건 2 (현재 봉): 양봉 + 박스 내 종가
      매수: 봉 완성 직후 (즉시)
    
    경로 B (일봉):
      조건 (당일 일봉): 양봉 + 박스 내 종가
      매수: 익일 09:01
    """
    if box.path_type == "PATH_A":
        # 경로 A: 두 봉 모두 조건 충족
        cond_prev = (
            previous.is_bullish
            and box.lower_price <= previous.close_price <= box.upper_price
        )
        cond_curr = (
            current.is_bullish
            and box.lower_price <= current.close_price <= box.upper_price
        )
        
        if not cond_prev:
            return EntryDecision(False, "PULLBACK_A_PREV_NOT_MET", None, None, None)
        if not cond_curr:
            return EntryDecision(False, "PULLBACK_A_CURR_NOT_MET", None, None, None)
        
        return EntryDecision(
            should_enter=True,
            reason="PULLBACK_A_TRIGGERED",
            box_id=None,  # 호출자가 box.id 보유
            expected_buy_price=current.close_price,
            expected_buy_at=context.current_time,  # 즉시
        )
    
    elif box.path_type == "PATH_B":
        # 경로 B: 일봉 1개 조건 충족, 익일 매수 (1차 09:01 + 2차 09:05 안전장치)
        cond = (
            current.is_bullish
            and box.lower_price <= current.close_price <= box.upper_price
        )
        
        if not cond:
            return EntryDecision(False, "PULLBACK_B_NOT_MET", None, None, None)
        
        # 익일 1차 매수 시각 + 2차 fallback 매수 시각 (§3.10 + §10.9)
        next_day_buy_time = _calculate_next_trading_day_at(
            context.current_time, V71Constants.PATH_B_PRIMARY_BUY_TIME_HHMM
        )
        next_day_fallback_time = _calculate_next_trading_day_at(
            context.current_time, V71Constants.PATH_B_FALLBACK_BUY_TIME_HHMM
        )
        
        return EntryDecision(
            should_enter=True,
            reason="PULLBACK_B_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close_price,  # 참고용 (실제는 익일 시초가)
            expected_buy_at=next_day_buy_time,
            fallback_buy_at=next_day_fallback_time,
            fallback_uses_market_order=V71Constants.PATH_B_FALLBACK_USES_MARKET_ORDER,
            fallback_gap_recheck_required=True,
        )
    
    raise ValueError(f"Unknown path_type: {box.path_type}")


def _evaluate_breakout(
    box: Box,
    current: Candle,
    context: MarketContext,
) -> EntryDecision:
    """
    돌파 판정.
    
    경로 A (3분봉):
      조건: 종가 > 박스 상단 + 양봉 + 시가 >= 박스 하단 (정상 돌파)
      매수: 봉 완성 직후
    
    경로 B (일봉):
      조건: 종가 > 박스 상단 + 양봉 + 시가 >= 박스 하단
      매수: 익일 09:01
    """
    cond_breakout = current.close_price > box.upper_price
    cond_bullish = current.is_bullish
    cond_normal_open = current.open_price >= box.lower_price  # 갭업 아닌 정상
    
    if not cond_breakout:
        return EntryDecision(False, "BREAKOUT_NO_BREAK", None, None, None)
    if not cond_bullish:
        return EntryDecision(False, "BREAKOUT_NOT_BULLISH", None, None, None)
    if not cond_normal_open:
        return EntryDecision(False, "BREAKOUT_GAP_OPEN", None, None, None)
    
    if box.path_type == "PATH_A":
        return EntryDecision(
            should_enter=True,
            reason="BREAKOUT_A_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close_price,
            expected_buy_at=context.current_time,
        )
    
    elif box.path_type == "PATH_B":
        # 1차 09:01 + 2차 09:05 안전장치 (§3.11 + §10.9)
        next_day_buy_time = _calculate_next_trading_day_at(
            context.current_time, V71Constants.PATH_B_PRIMARY_BUY_TIME_HHMM
        )
        next_day_fallback_time = _calculate_next_trading_day_at(
            context.current_time, V71Constants.PATH_B_FALLBACK_BUY_TIME_HHMM
        )
        return EntryDecision(
            should_enter=True,
            reason="BREAKOUT_B_TRIGGERED",
            box_id=None,
            expected_buy_price=current.close_price,
            expected_buy_at=next_day_buy_time,
            fallback_buy_at=next_day_fallback_time,
            fallback_uses_market_order=V71Constants.PATH_B_FALLBACK_USES_MARKET_ORDER,
            fallback_gap_recheck_required=True,
        )
    
    raise ValueError(f"Unknown path_type: {box.path_type}")


def _calculate_next_trading_day_at(current_time: datetime, hhmm: str) -> datetime:
    """
    다음 영업일 특정 시각 계산.
    
    Args:
        current_time: 현재 시각
        hhmm: 시각 문자열 (예: "09:01", "09:05")
    
    Returns:
        다음 영업일의 hhmm 시각 datetime
    """
    from src.core.market_schedule import get_next_trading_day
    next_day = get_next_trading_day(current_time.date())
    return datetime.combine(next_day, datetime.strptime(hhmm, "%H:%M").time())
```

### 2.4 갭업 검증 (경로 B 1차 + 2차 fallback 공통)

```python
def check_gap_up_for_path_b(
    previous_close: int,
    reference_price: int,
) -> tuple[bool, float]:
    """
    경로 B 갭업 검증 (1차 09:01 시초가, 2차 09:05 fallback 모두 사용).
    
    Args:
        previous_close: 전일 종가 (일봉 진입 조건 형성된 날의 종가)
        reference_price: 검증 시점 가격
            - 1차 (09:01): 익일 시초가
            - 2차 (09:05): 09:05 시점 현재가
    
    Returns:
        (should_proceed, gap_pct):
            should_proceed: True면 매수 진행, False면 포기
            gap_pct: 갭업률 (참고)
    
    Note:
        - 1차 시점 갭업 5% 초과: 매수 포기 (안전장치 미발동, §3.10)
        - 2차 시점 갭업 5% 초과: 안전장치 무력화 (§10.9)
        - 동일 임계값 PATH_B_GAP_UP_LIMIT 사용 (일관성)
    
    Example:
        >>> # 1차 시점
        >>> proceed, gap = check_gap_up_for_path_b(10000, 10300)
        >>> if not proceed:
        ...     log.warning(f"Gap up {gap}% exceeds limit, abandoning buy")
        >>> 
        >>> # 2차 시점 (fallback 발동 직전)
        >>> proceed_fb, gap_fb = check_gap_up_for_path_b(10000, 10500)
        >>> if not proceed_fb:
        ...     log.warning(f"Gap up at fallback {gap_fb}%, safety net invalidated")
    """
    if previous_close <= 0 or reference_price <= 0:
        raise ValueError("Invalid prices")
    
    gap_pct = (reference_price - previous_close) / previous_close
    
    should_proceed = gap_pct < V71Constants.PATH_B_GAP_UP_LIMIT  # 5%
    
    return should_proceed, gap_pct
```

### 2.5 단위 테스트 케이스

```python
# tests/v71/test_skills/test_box_entry.py

class TestPullbackPathA:
    """경로 A 눌림 테스트."""
    
    def test_both_candles_meet_conditions(self):
        """직전봉 + 현재봉 모두 양봉 + 박스 내 종가."""
        box = Box(upper_price=100, lower_price=90, ...)
        prev = Candle(open_price=92, high_price=98, low_price=91, close_price=95, ...)
        curr = Candle(open_price=95, high_price=99, low_price=94, close_price=97, ...)
        ctx = MarketContext(is_market_open=True, ...)
        
        decision = evaluate_box_entry(box, curr, prev, ctx)
        
        assert decision.should_enter is True
        assert decision.reason == "PULLBACK_A_TRIGGERED"
    
    def test_prev_candle_not_bullish(self):
        """직전봉 음봉."""
        prev = Candle(open_price=98, close_price=95, ...)  # Open > Close
        ...
        assert decision.should_enter is False
        assert decision.reason == "PULLBACK_A_PREV_NOT_MET"
    
    def test_close_above_box(self):
        """종가가 박스 상단 위."""
        ...
    
    def test_close_below_box(self):
        """종가가 박스 하단 아래."""
        ...
    
    def test_market_closed(self):
        """장 마감 후."""
        ctx = MarketContext(is_market_open=False, ...)
        ...
        assert decision.should_enter is False
        assert decision.reason == "MARKET_CLOSED"
    
    def test_vi_active(self):
        """VI 발동 중."""
        ...
    
    def test_vi_recovered_today(self):
        """당일 VI 복구 후 진입 금지."""
        ...


class TestBreakoutPathA:
    """경로 A 돌파 테스트."""
    
    def test_normal_breakout(self):
        """정상 돌파."""
        ...
    
    def test_gap_open_breakout(self):
        """갭업 돌파 (시가가 박스 위)."""
        ...
    
    def test_close_below_upper(self):
        """종가가 박스 상단 아래."""
        ...


class TestPullbackPathB:
    """경로 B 일봉 눌림 테스트."""
    
    def test_pullback_b_triggered(self):
        """일봉 양봉 + 박스 내 종가."""
        ...
        assert decision.should_enter is True
        assert decision.expected_buy_at.time() == time(9, 1)


class TestGapUpCheck:
    """갭업 검증."""
    
    def test_gap_under_5pct_proceed(self):
        proceed, gap = check_gap_up_for_path_b(10000, 10400)
        assert proceed is True
        assert gap == 0.04  # 4%
    
    def test_gap_over_5pct_abandon(self):
        proceed, gap = check_gap_up_for_path_b(10000, 10550)
        assert proceed is False
        assert gap == 0.055
    
    def test_invalid_prices(self):
        with pytest.raises(ValueError):
            check_gap_up_for_path_b(0, 10000)
```

---

## §3. 스킬 3: exit_calc_skill

### 3.1 목적

```yaml
손절/익절/TS 청산선의 정확한 계산:
  - 단계별 손절선 (-5/-2/+4)
  - 분할 익절 임계 (+5%, +10%)
  - TS 활성화/유효화 판정
  - ATR 배수 단계 (4.0/3.0/2.5/2.0)
  - 유효 청산선 = max(고정, TS)
```

### 3.2 모듈 구조

```python
# src/core/v71/skills/exit_calc_skill.py

"""
청산 조건 계산 스킬.

02_TRADING_RULES.md §5 (매수 후 관리) 룰 정확히 구현.
모든 청산 판정은 이 스킬을 통해서만 가능.
"""

from dataclasses import dataclass
from typing import Optional, Literal
from src.core.v71.v71_constants import V71Constants


@dataclass(frozen=True)
class PositionSnapshot:
    """청산 계산용 포지션 정보."""
    weighted_avg_price: int
    total_quantity: int
    profit_5_executed: bool
    profit_10_executed: bool
    ts_activated: bool
    ts_base_price: Optional[int]   # 매수 후 최고가
    ts_stop_price: Optional[int]   # 이전 TS 청산선


@dataclass(frozen=True)
class EffectiveStopResult:
    """유효 청산선 계산 결과."""
    fixed_stop: int                 # 고정 손절선
    ts_stop: Optional[int]          # TS 청산선 (None이면 미적용)
    effective_stop: int             # 유효 청산선 = max(fixed, ts) 또는 fixed
    should_exit: bool               # 현재가 <= effective_stop
    exit_reason: Optional[str]      # "STOP_LOSS" / "TS_EXIT"


@dataclass(frozen=True)
class ProfitTakeResult:
    """익절 판정 결과."""
    should_take_5: bool             # +5% 익절 실행 여부
    should_take_10: bool            # +10% 익절 실행 여부
    quantity_5: int                 # +5% 청산 수량
    quantity_10: int                # +10% 청산 수량


@dataclass(frozen=True)
class TSUpdateResult:
    """TS 업데이트 결과."""
    new_base_price: int             # 새 BasePrice (최고가)
    new_ts_stop: Optional[int]      # 새 TS 청산선
    new_multiplier: float           # 현재 ATR 배수
```

### 3.3 핵심 함수: calculate_effective_stop

```python
def calculate_effective_stop(
    position: PositionSnapshot,
    current_price: int,
) -> EffectiveStopResult:
    """
    유효 청산선 계산.
    
    Args:
        position: 포지션 스냅샷
        current_price: 현재가
    
    Returns:
        EffectiveStopResult
    
    Raises:
        ValueError: 입력 검증 실패
    
    Example:
        >>> result = calculate_effective_stop(position, current_price=98000)
        >>> if result.should_exit:
        ...     await execute_market_sell(position, reason=result.exit_reason)
    """
    # 입력 검증
    if position.weighted_avg_price <= 0:
        raise ValueError("Invalid weighted_avg_price")
    if current_price <= 0:
        raise ValueError("Invalid current_price")
    
    # 1. 고정 손절선 단계
    fixed_stop = _calculate_fixed_stop(position)
    
    # 2. TS 청산선
    ts_stop = _calculate_ts_stop(position, current_price)
    
    # 3. 유효 청산선
    if ts_stop is not None and position.profit_10_executed:
        # +10% 청산 후만 TS 청산선 비교 유효
        effective = max(fixed_stop, ts_stop)
    else:
        effective = fixed_stop
    
    # 4. 청산 판정
    should_exit = current_price <= effective
    
    # 5. 청산 사유 결정
    exit_reason = None
    if should_exit:
        if ts_stop is not None and effective == ts_stop:
            exit_reason = "TS_EXIT"
        else:
            exit_reason = "STOP_LOSS"
    
    return EffectiveStopResult(
        fixed_stop=fixed_stop,
        ts_stop=ts_stop,
        effective_stop=effective,
        should_exit=should_exit,
        exit_reason=exit_reason,
    )


def _calculate_fixed_stop(position: PositionSnapshot) -> int:
    """단계별 고정 손절선."""
    avg = position.weighted_avg_price
    
    if not position.profit_5_executed:
        # 단계 1: 매수 ~ +5% 미만
        return round(avg * (1 + V71Constants.STOP_LOSS_INITIAL_PCT))  # × 0.95
    elif not position.profit_10_executed:
        # 단계 2: +5% 청산 후
        return round(avg * (1 + V71Constants.STOP_LOSS_AFTER_PROFIT_5))  # × 0.98
    else:
        # 단계 3: +10% 청산 후
        return round(avg * (1 + V71Constants.STOP_LOSS_AFTER_PROFIT_10))  # × 1.04


def _calculate_ts_stop(
    position: PositionSnapshot,
    current_price: int,
) -> Optional[int]:
    """TS 청산선 계산."""
    if not position.ts_activated or position.ts_base_price is None:
        return None
    
    # ATR 배수 결정
    multiplier = _get_atr_multiplier(position, current_price)
    
    # ATR 값은 외부에서 계산되어야 함 (이 스킬은 multiplier만 결정)
    # 실제 호출 시: ts_stop = base_price - atr * multiplier
    # 여기서는 단순 계산만 (호출자가 atr_value 제공 필요)
    # → calculate_effective_stop에 atr_value 인자 추가 권장
    
    return None  # 추후 보완: atr_value 인자 추가


def _get_atr_multiplier(
    position: PositionSnapshot,
    current_price: int,
) -> float:
    """수익률에 따른 ATR 배수 (단방향 축소만)."""
    pnl_pct = (current_price - position.weighted_avg_price) / position.weighted_avg_price
    
    if pnl_pct < V71Constants.TS_VALID_LEVEL:  # +10% 미만
        # 청산선 비교 미사용 단계
        return V71Constants.ATR_MULTIPLIER_TIER_1  # 4.0 (의미 없음, 비교 안 함)
    elif pnl_pct < 0.15:
        return V71Constants.ATR_MULTIPLIER_TIER_1  # 4.0
    elif pnl_pct < 0.25:
        return V71Constants.ATR_MULTIPLIER_TIER_2  # 3.0
    elif pnl_pct < 0.40:
        return V71Constants.ATR_MULTIPLIER_TIER_3  # 2.5
    else:
        return V71Constants.ATR_MULTIPLIER_TIER_4  # 2.0
```

### 3.4 개선된 calculate_effective_stop (atr_value 포함)

```python
def calculate_effective_stop(
    position: PositionSnapshot,
    current_price: int,
    atr_value: Optional[float] = None,
) -> EffectiveStopResult:
    """
    유효 청산선 계산 (atr_value 포함).
    
    Args:
        position: 포지션 스냅샷
        current_price: 현재가
        atr_value: ATR(10) 값 (TS 계산 시 필요)
    
    Returns:
        EffectiveStopResult
    """
    # 입력 검증 (위와 동일)
    
    # 1. 고정 손절선
    fixed_stop = _calculate_fixed_stop(position)
    
    # 2. TS 청산선 계산
    ts_stop = None
    if (
        position.ts_activated
        and position.ts_base_price is not None
        and atr_value is not None
        and atr_value > 0
    ):
        multiplier = _get_atr_multiplier(position, current_price)
        candidate_ts = round(position.ts_base_price - atr_value * multiplier)
        
        # 단방향 (상승만)
        if position.ts_stop_price is not None:
            candidate_ts = max(candidate_ts, position.ts_stop_price)
        
        ts_stop = candidate_ts
    
    # 3. 유효 청산선
    if ts_stop is not None and position.profit_10_executed:
        effective = max(fixed_stop, ts_stop)
    else:
        effective = fixed_stop
    
    # 4. 청산 판정
    should_exit = current_price <= effective
    
    exit_reason = None
    if should_exit:
        if ts_stop is not None and effective == ts_stop and position.profit_10_executed:
            exit_reason = "TS_EXIT"
        else:
            exit_reason = "STOP_LOSS"
    
    return EffectiveStopResult(
        fixed_stop=fixed_stop,
        ts_stop=ts_stop,
        effective_stop=effective,
        should_exit=should_exit,
        exit_reason=exit_reason,
    )
```

### 3.5 익절 판정

```python
def check_profit_take(
    position: PositionSnapshot,
    current_price: int,
) -> ProfitTakeResult:
    """
    분할 익절 조건 판정.
    
    Args:
        position: 포지션 스냅샷
        current_price: 현재가
    
    Returns:
        ProfitTakeResult
    """
    if position.weighted_avg_price <= 0 or current_price <= 0:
        return ProfitTakeResult(False, False, 0, 0)
    
    pnl_pct = (current_price - position.weighted_avg_price) / position.weighted_avg_price
    
    # +5% 판정
    should_5 = (
        not position.profit_5_executed
        and pnl_pct >= V71Constants.PROFIT_TAKE_LEVEL_1  # 0.05
    )
    qty_5 = 0
    if should_5:
        qty_5 = int(position.total_quantity * V71Constants.PROFIT_TAKE_RATIO)  # 30%
        if qty_5 == 0 and position.total_quantity > 0:
            qty_5 = 1  # 최소 1주
    
    # +10% 판정 (1차 청산 완료 후)
    should_10 = (
        position.profit_5_executed
        and not position.profit_10_executed
        and pnl_pct >= V71Constants.PROFIT_TAKE_LEVEL_2  # 0.10
    )
    qty_10 = 0
    if should_10:
        # 현재 보유 수량의 30%
        qty_10 = int(position.total_quantity * V71Constants.PROFIT_TAKE_RATIO)
        if qty_10 == 0 and position.total_quantity > 0:
            qty_10 = 1
    
    return ProfitTakeResult(
        should_take_5=should_5,
        should_take_10=should_10,
        quantity_5=qty_5,
        quantity_10=qty_10,
    )
```

### 3.6 TS 업데이트

```python
def update_trailing_stop(
    position: PositionSnapshot,
    current_high: int,
    atr_value: float,
) -> TSUpdateResult:
    """
    TS BasePrice + 청산선 업데이트.
    
    Args:
        position: 포지션 스냅샷
        current_high: 현재 봉의 고가 (또는 현재가)
        atr_value: ATR(10) 값
    
    Returns:
        TSUpdateResult
    
    Note:
        BasePrice는 단방향 (상승만)
        ATR 배수는 단방향 (축소만, 한 번 작아지면 커지지 않음)
    """
    # BasePrice 업데이트 (단방향)
    if position.ts_base_price is None:
        new_base = current_high
    else:
        new_base = max(position.ts_base_price, current_high)
    
    # ATR 배수 (수익률 기반)
    pnl_pct = (current_high - position.weighted_avg_price) / position.weighted_avg_price
    new_multiplier = _get_atr_multiplier_with_ratchet(position, pnl_pct)
    
    # TS 청산선 (단방향 상승)
    candidate_ts = round(new_base - atr_value * new_multiplier)
    if position.ts_stop_price is not None:
        new_ts = max(candidate_ts, position.ts_stop_price)
    else:
        new_ts = candidate_ts
    
    return TSUpdateResult(
        new_base_price=new_base,
        new_ts_stop=new_ts,
        new_multiplier=new_multiplier,
    )


def _get_atr_multiplier_with_ratchet(
    position: PositionSnapshot,
    pnl_pct: float,
) -> float:
    """
    ATR 배수 단방향 축소 (래칫).
    
    한 번 작아진 배수는 커지지 않음.
    예: 한 번 2.5 도달 후 수익률 떨어져도 2.5 유지
    """
    # 현재 PnL 기반 후보 배수
    if pnl_pct < V71Constants.TS_VALID_LEVEL:
        candidate = V71Constants.ATR_MULTIPLIER_TIER_1  # 4.0
    elif pnl_pct < 0.15:
        candidate = V71Constants.ATR_MULTIPLIER_TIER_1  # 4.0
    elif pnl_pct < 0.25:
        candidate = V71Constants.ATR_MULTIPLIER_TIER_2  # 3.0
    elif pnl_pct < 0.40:
        candidate = V71Constants.ATR_MULTIPLIER_TIER_3  # 2.5
    else:
        candidate = V71Constants.ATR_MULTIPLIER_TIER_4  # 2.0
    
    # 단방향: 작아지기만
    # position에 현재 active_multiplier 필드 추가 필요
    # 또는 ts_active_multiplier 필드 활용
    # 여기서는 candidate 반환 (호출자가 min 처리)
    return candidate
```

### 3.7 단위 테스트 케이스

[06_AGENTS_SPEC.md §5.4의 25+개 케이스 참조]

핵심 케이스:
- 단계 1 매수 직후 (-5% 손절선)
- 단계 2 +5% 청산 후 (-2%)
- 단계 3 +10% 청산 후 (+4%)
- TS 활성화 vs 비활성
- ATR 배수 4단계
- 단방향 (BasePrice, TS 청산선, 배수)
- max(fixed, ts) 케이스 분기

---

## §4. 스킬 4: avg_price_skill

### 4.1 목적

```yaml
평단가 정확한 관리:
  - 매수 시 가중 평균 재계산
  - 매수 시 이벤트 리셋 (profit_5/10)
  - 매수 시 손절선 재계산 (단계 1 복귀)
  - 매수 시 TS BasePrice 유지
  - 매도 시 평단가 변경 없음
```

### 4.2 핵심 함수

```python
# src/core/v71/skills/avg_price_skill.py

"""
평단가 관리 스킬.

02_TRADING_RULES.md §6 룰 정확히 구현.
모든 평단가/포지션 변경은 이 스킬을 통해서만.
"""

from dataclasses import dataclass, replace
from typing import Optional
from src.core.v71.v71_constants import V71Constants


@dataclass(frozen=True)
class PositionState:
    """포지션 상태 (평단가 관리 대상)."""
    weighted_avg_price: int
    initial_avg_price: int
    total_quantity: int
    profit_5_executed: bool
    profit_10_executed: bool
    ts_activated: bool
    ts_base_price: Optional[int]
    ts_stop_price: Optional[int]
    fixed_stop_price: int
    actual_capital_invested: int


def update_position_after_buy(
    position: Optional[PositionState],
    buy_price: int,
    buy_qty: int,
) -> PositionState:
    """
    매수 후 포지션 업데이트.
    
    신규 매수: 평단가 = buy_price, 모든 이벤트 초기화
    추가 매수: 가중 평균 재계산 + 이벤트 리셋 + 손절선 재계산
    
    Args:
        position: 기존 포지션 (None이면 신규)
        buy_price: 매수가
        buy_qty: 매수 수량
    
    Returns:
        업데이트된 PositionState
    
    Raises:
        ValueError: 입력 검증 실패
    
    Example:
        >>> # 신규 매수
        >>> pos = update_position_after_buy(None, buy_price=180000, buy_qty=100)
        
        >>> # 추가 매수
        >>> pos = update_position_after_buy(existing_pos, buy_price=175000, buy_qty=100)
    """
    if buy_price <= 0:
        raise ValueError("Invalid buy_price")
    if buy_qty <= 0:
        raise ValueError("Invalid buy_qty")
    
    if position is None:
        # 신규 매수
        return PositionState(
            weighted_avg_price=buy_price,
            initial_avg_price=buy_price,
            total_quantity=buy_qty,
            profit_5_executed=False,
            profit_10_executed=False,
            ts_activated=False,
            ts_base_price=buy_price,  # 시작점
            ts_stop_price=None,
            fixed_stop_price=round(buy_price * (1 + V71Constants.STOP_LOSS_INITIAL_PCT)),
            actual_capital_invested=buy_price * buy_qty,
        )
    
    # 추가 매수
    if position.total_quantity <= 0:
        raise ValueError("Cannot add to closed position")
    
    new_total_qty = position.total_quantity + buy_qty
    new_avg = round(
        (position.total_quantity * position.weighted_avg_price + buy_qty * buy_price)
        / new_total_qty
    )
    new_capital = position.actual_capital_invested + buy_price * buy_qty
    
    # 이벤트 리셋 (핵심!)
    return PositionState(
        weighted_avg_price=new_avg,
        initial_avg_price=position.initial_avg_price,  # 변경 없음
        total_quantity=new_total_qty,
        profit_5_executed=False,  # ★ 리셋
        profit_10_executed=False,  # ★ 리셋
        ts_activated=position.ts_activated,  # 유지 (한 번 활성화면 유지)
        ts_base_price=position.ts_base_price,  # 유지 (최고가 이력)
        ts_stop_price=None,  # 리셋 (새 평단가 기준 다시 계산)
        fixed_stop_price=round(new_avg * (1 + V71Constants.STOP_LOSS_INITIAL_PCT)),  # 단계 1 복귀
        actual_capital_invested=new_capital,
    )


def update_position_after_sell(
    position: PositionState,
    sell_qty: int,
    sell_reason: str,  # "PROFIT_TAKE_5", "PROFIT_TAKE_10", "STOP_LOSS", "TS_EXIT", "MANUAL"
) -> PositionState:
    """
    매도 후 포지션 업데이트.
    
    핵심: 평단가 변경 없음, 수량만 감소
    
    Args:
        position: 기존 포지션
        sell_qty: 매도 수량
        sell_reason: 매도 사유
    
    Returns:
        업데이트된 PositionState
    """
    if sell_qty <= 0:
        raise ValueError("Invalid sell_qty")
    if sell_qty > position.total_quantity:
        raise ValueError(f"sell_qty ({sell_qty}) > total ({position.total_quantity})")
    
    new_total_qty = position.total_quantity - sell_qty
    
    # 이벤트 플래그 갱신
    new_profit_5 = position.profit_5_executed
    new_profit_10 = position.profit_10_executed
    
    if sell_reason == "PROFIT_TAKE_5":
        new_profit_5 = True
        # TS 활성화 (BasePrice 추적 시작, 청산선 비교는 +10% 후)
        new_ts_activated = True
    elif sell_reason == "PROFIT_TAKE_10":
        new_profit_10 = True
        new_ts_activated = position.ts_activated  # 이미 True
    else:
        new_ts_activated = position.ts_activated
    
    # 손절선 단계별 갱신
    if sell_reason == "PROFIT_TAKE_5":
        new_fixed_stop = round(
            position.weighted_avg_price * (1 + V71Constants.STOP_LOSS_AFTER_PROFIT_5)
        )
    elif sell_reason == "PROFIT_TAKE_10":
        new_fixed_stop = round(
            position.weighted_avg_price * (1 + V71Constants.STOP_LOSS_AFTER_PROFIT_10)
        )
    else:
        new_fixed_stop = position.fixed_stop_price  # 변경 없음
    
    # 자본 비례 차감 (한도 계산용)
    if position.total_quantity > 0:
        capital_ratio = (position.total_quantity - sell_qty) / position.total_quantity
        new_capital = round(position.actual_capital_invested * capital_ratio)
    else:
        new_capital = 0
    
    return replace(
        position,
        weighted_avg_price=position.weighted_avg_price,  # 변경 없음
        total_quantity=new_total_qty,
        profit_5_executed=new_profit_5,
        profit_10_executed=new_profit_10,
        ts_activated=new_ts_activated,
        # ts_base_price, ts_stop_price 유지 (변경 없음)
        fixed_stop_price=new_fixed_stop,
        actual_capital_invested=new_capital,
    )
```

### 4.3 단위 테스트

```python
class TestUpdateAfterBuy:
    def test_new_position(self):
        """신규 매수."""
        pos = update_position_after_buy(None, 180000, 100)
        
        assert pos.weighted_avg_price == 180000
        assert pos.total_quantity == 100
        assert pos.profit_5_executed is False
        assert pos.fixed_stop_price == 171000  # 180000 × 0.95
    
    def test_pyramid_buy_average(self):
        """추가 매수 - 가중 평균."""
        pos1 = update_position_after_buy(None, 180000, 100)
        pos2 = update_position_after_buy(pos1, 175000, 100)
        
        # (100 × 180000 + 100 × 175000) / 200 = 177500
        assert pos2.weighted_avg_price == 177500
        assert pos2.total_quantity == 200
    
    def test_pyramid_buy_event_reset(self):
        """추가 매수 - 이벤트 리셋."""
        pos1 = update_position_after_buy(None, 180000, 100)
        # +5% 청산 가정
        pos1 = replace(pos1, profit_5_executed=True, fixed_stop_price=176400)
        
        pos2 = update_position_after_buy(pos1, 175000, 100)
        
        # 이벤트 리셋 검증
        assert pos2.profit_5_executed is False  # ★
        assert pos2.profit_10_executed is False
        # 손절선 단계 1 복귀
        assert pos2.fixed_stop_price == 168625  # 177500 × 0.95
    
    def test_invalid_buy_price(self):
        with pytest.raises(ValueError):
            update_position_after_buy(None, 0, 100)
    
    def test_initial_price_preserved(self):
        """initial_avg_price는 첫 매수가 유지."""
        pos1 = update_position_after_buy(None, 180000, 100)
        pos2 = update_position_after_buy(pos1, 175000, 100)
        
        assert pos1.initial_avg_price == 180000
        assert pos2.initial_avg_price == 180000  # 변경 없음


class TestUpdateAfterSell:
    def test_partial_sell_avg_unchanged(self):
        """부분 매도 - 평단가 변경 없음."""
        pos1 = update_position_after_buy(None, 180000, 100)
        pos2 = update_position_after_sell(pos1, 30, "PROFIT_TAKE_5")
        
        assert pos2.weighted_avg_price == 180000  # 변경 없음 ★
        assert pos2.total_quantity == 70
        assert pos2.profit_5_executed is True
        assert pos2.fixed_stop_price == 176400  # 180000 × 0.98
    
    def test_full_sell(self):
        """전량 매도."""
        pos1 = update_position_after_buy(None, 180000, 100)
        pos2 = update_position_after_sell(pos1, 100, "STOP_LOSS")
        
        assert pos2.total_quantity == 0
        assert pos2.weighted_avg_price == 180000  # 변경 없음
    
    def test_sell_more_than_held(self):
        """보유보다 많이 매도 시도."""
        pos1 = update_position_after_buy(None, 180000, 100)
        with pytest.raises(ValueError):
            update_position_after_sell(pos1, 200, "MANUAL")
```

---

## §5. 스킬 5: vi_skill

### 5.1 목적

```yaml
VI 상태 처리:
  - VI 발동 감지
  - VI 중 매매 판정 중단
  - VI 해제 후 즉시 재평가
  - 갭 측정 (3% 기준)
  - 당일 신규 진입 금지 플래그
```

### 5.2 핵심 함수

```python
# src/core/v71/skills/vi_skill.py

"""
VI 상태 처리 스킬.

02_TRADING_RULES.md §10 룰 정확히 구현.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional
from datetime import datetime

from src.core.v71.v71_constants import V71Constants


class VIState(Enum):
    NORMAL = "NORMAL"
    TRIGGERED = "TRIGGERED"
    RESUMED = "RESUMED"


@dataclass(frozen=True)
class VIStateContext:
    """VI 상태 컨텍스트."""
    state: VIState
    trigger_price: Optional[int]
    trigger_at: Optional[datetime]
    resume_at: Optional[datetime]


@dataclass(frozen=True)
class VIDecision:
    """VI 처리 결정."""
    should_block_buy: bool         # 신규 매수 차단 여부
    should_block_exit: bool        # 청산 판정 차단 여부
    should_attempt_single_price: bool  # 단일가 매매 참여 여부
    should_set_recovered_today: bool   # 당일 진입 금지 플래그 설정
    reason: str


def handle_vi_state(
    vi_context: VIStateContext,
    current_state_in_position: bool,  # 보유 포지션 여부
) -> VIDecision:
    """
    VI 상태에 따른 처리 결정.
    
    Args:
        vi_context: 현재 VI 상태
        current_state_in_position: 보유 중인 포지션이 있는지
    
    Returns:
        VIDecision: 시스템 행동 결정
    """
    if vi_context.state == VIState.NORMAL:
        return VIDecision(
            should_block_buy=False,
            should_block_exit=False,
            should_attempt_single_price=False,
            should_set_recovered_today=False,
            reason="VI_NORMAL",
        )
    
    elif vi_context.state == VIState.TRIGGERED:
        # VI 발동 중
        return VIDecision(
            should_block_buy=False,  # 단일가 매매로 시도 가능
            should_block_exit=True,  # 손절/익절 판정 중단
            should_attempt_single_price=True,
            should_set_recovered_today=False,
            reason="VI_TRIGGERED",
        )
    
    elif vi_context.state == VIState.RESUMED:
        # VI 해제 직후 - 즉시 재평가
        return VIDecision(
            should_block_buy=False,
            should_block_exit=False,  # 재평가 가능
            should_attempt_single_price=False,
            should_set_recovered_today=True,  # 당일 신규 진입 금지 플래그 설정
            reason="VI_RESUMED",
        )
    
    raise ValueError(f"Unknown VI state: {vi_context.state}")


def check_post_vi_gap(
    vi_trigger_price: int,
    current_price: int,
) -> tuple[bool, float]:
    """
    VI 해제 후 갭 측정.
    
    3% 이상 갭이면 매수 포기.
    
    Args:
        vi_trigger_price: VI 발동 시 가격
        current_price: VI 해제 후 현재가
    
    Returns:
        (should_proceed, gap_pct)
    """
    if vi_trigger_price <= 0 or current_price <= 0:
        raise ValueError("Invalid prices")
    
    gap_pct = abs(current_price - vi_trigger_price) / vi_trigger_price
    should_proceed = gap_pct < V71Constants.VI_GAP_LIMIT  # 3%
    
    return should_proceed, gap_pct


def transition_vi_state(
    current: VIState,
    event: str,  # "TRIGGER" or "RESUME"
) -> VIState:
    """VI 상태 머신 전이."""
    if current == VIState.NORMAL and event == "TRIGGER":
        return VIState.TRIGGERED
    elif current == VIState.TRIGGERED and event == "RESUME":
        return VIState.RESUMED
    elif current == VIState.RESUMED:
        # 자동 NORMAL 복귀 (호출자가 시점 결정)
        return VIState.NORMAL
    else:
        raise ValueError(f"Invalid transition: {current} + {event}")
```

---

## §6. 스킬 6: notification_skill

### 6.1 목적

```yaml
표준 알림 발송:
  - 등급 결정 (CRITICAL/HIGH/MEDIUM/LOW)
  - 표준 메시지 포맷
  - 빈도 제한 (5분)
  - Circuit Breaker 통합
  - 우선순위 큐 enqueue
  - CRITICAL/HIGH는 웹 동시
```

### 6.2 핵심 함수

```python
# src/core/v71/skills/notification_skill.py

"""
알림 발송 표준 스킬.

raw telegram.send_message() 사용 금지.
모든 알림은 이 스킬을 통해서만.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Any
from datetime import datetime, timedelta

from src.core.v71.v71_constants import V71Constants
from src.notification.notification_queue import NotificationQueue


class Severity(Enum):
    CRITICAL = "CRITICAL"
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EventType(Enum):
    # 거래
    BUY_EXECUTED = "BUY_EXECUTED"
    PROFIT_TAKE_5 = "PROFIT_TAKE_5"
    PROFIT_TAKE_10 = "PROFIT_TAKE_10"
    STOP_LOSS = "STOP_LOSS"
    TS_EXIT = "TS_EXIT"
    AUTO_EXIT = "AUTO_EXIT"
    
    # 수동 거래
    MANUAL_BUY_DETECTED = "MANUAL_BUY_DETECTED"
    MANUAL_SELL_DETECTED = "MANUAL_SELL_DETECTED"
    
    # 시스템
    SYSTEM_RESTART_COMPLETED = "SYSTEM_RESTART_COMPLETED"
    WEBSOCKET_DISCONNECTED = "WEBSOCKET_DISCONNECTED"
    WEBSOCKET_RECONNECTED = "WEBSOCKET_RECONNECTED"
    
    # 보안
    NEW_IP_LOGIN = "NEW_IP_LOGIN"
    
    # VI
    VI_TRIGGERED = "VI_TRIGGERED"
    VI_RESUMED = "VI_RESUMED"
    
    # 박스
    BOX_ENTRY_IMMINENT = "BOX_ENTRY_IMMINENT"
    BOX_EXPIRY_REMINDER = "BOX_EXPIRY_REMINDER"
    
    # 일별/월별
    DAILY_SUMMARY = "DAILY_SUMMARY"
    MONTHLY_REVIEW = "MONTHLY_REVIEW"


@dataclass(frozen=True)
class NotificationRequest:
    """알림 요청."""
    severity: Severity
    event_type: EventType
    stock_code: Optional[str]
    title: str
    message: str
    payload: Optional[dict] = None


async def send_notification(
    queue: NotificationQueue,
    request: NotificationRequest,
) -> bool:
    """
    알림 발송 (큐에 enqueue).
    
    Args:
        queue: 알림 큐
        request: 알림 요청
    
    Returns:
        bool: enqueue 성공 여부
    
    Note:
        - CRITICAL은 빈도 제한 무시
        - HIGH/MEDIUM/LOW는 5분 내 동일 이벤트 차단
        - CRITICAL/HIGH는 웹 알림 동시
    
    Example:
        >>> await send_notification(
        ...     queue=notif_queue,
        ...     request=NotificationRequest(
        ...         severity=Severity.CRITICAL,
        ...         event_type=EventType.STOP_LOSS,
        ...         stock_code="036040",
        ...         title="손절 실행",
        ...         message=format_stop_loss_message(...),
        ...     )
        ... )
    """
    # 1. 빈도 제한 체크 (CRITICAL 제외)
    if request.severity != Severity.CRITICAL:
        rate_limit_key = _make_rate_limit_key(
            request.event_type, request.stock_code
        )
        if await queue.is_rate_limited(rate_limit_key):
            return False  # 빈도 제한으로 차단
    
    # 2. 채널 결정
    if request.severity in (Severity.CRITICAL, Severity.HIGH):
        channel = "BOTH"  # 텔레그램 + 웹
    else:
        channel = "TELEGRAM"
    
    # 3. 우선순위 결정
    priority = _severity_to_priority(request.severity)
    
    # 4. 만료 시각 (MEDIUM/LOW만)
    expires_at = None
    if request.severity in (Severity.MEDIUM, Severity.LOW):
        expires_at = datetime.utcnow() + timedelta(minutes=5)
    
    # 5. enqueue
    await queue.enqueue(
        severity=request.severity.value,
        event_type=request.event_type.value,
        stock_code=request.stock_code,
        title=request.title,
        message=request.message,
        payload=request.payload,
        channel=channel,
        priority=priority,
        rate_limit_key=_make_rate_limit_key(request.event_type, request.stock_code),
        expires_at=expires_at,
    )
    return True


def _severity_to_priority(severity: Severity) -> int:
    """등급 → 우선순위 정수 (낮을수록 높음)."""
    return {
        Severity.CRITICAL: 1,
        Severity.HIGH: 2,
        Severity.MEDIUM: 3,
        Severity.LOW: 4,
    }[severity]


def _make_rate_limit_key(event_type: EventType, stock_code: Optional[str]) -> str:
    """빈도 제한 키."""
    if stock_code:
        return f"{event_type.value}:{stock_code}"
    return event_type.value


# 표준 메시지 포맷터
def format_stop_loss_message(
    stock_name: str,
    stock_code: str,
    sell_price: int,
    avg_price: int,
    quantity: int,
    timestamp: datetime,
    pnl_amount: int,
    pnl_pct: float,
    reason: str,
) -> tuple[str, str]:
    """손절 알림 메시지 포맷."""
    title = "[CRITICAL] 손절 실행"
    message = (
        f"종목: {stock_name} ({stock_code})\n"
        f"매도가: {sell_price:,}원 (평단가 {avg_price:,}원)\n"
        f"수량: {quantity}주\n"
        f"시각: {timestamp.strftime('%H:%M:%S')}\n\n"
        f"손익: {pnl_pct:+.2%} ({pnl_amount:+,}원)\n"
        f"사유: {reason}"
    )
    return title, message


def format_buy_message(...):
    """매수 알림 메시지 포맷."""
    ...


def format_profit_take_message(...):
    """익절 알림 메시지 포맷."""
    ...
```

---

## §7. 스킬 7: reconciliation_skill

### 7.1 목적

```yaml
포지션 정합성 확인:
  - 키움 잔고 ↔ 시스템 DB 비교
  - 시나리오 A/B/C/D 분기
  - 이중 경로 자동 비례 차감
  - 차이 발생 시 알림
```

### 7.2 핵심 함수

```python
# src/core/v71/skills/reconciliation_skill.py

"""
포지션 정합성 확인 스킬.

02_TRADING_RULES.md §7 (수동 거래 시나리오) 구현.
"""

from dataclasses import dataclass
from enum import Enum
from typing import List, Optional


class ReconciliationCase(Enum):
    A_MATCH = "A_MATCH"                    # 키움 = DB (일치)
    B_MANUAL_BUY = "B_MANUAL_BUY"          # 키움 > DB (사용자 매수)
    C_MANUAL_SELL = "C_MANUAL_SELL"        # 키움 < DB (사용자 매도)
    D_DB_ONLY = "D_DB_ONLY"                # 키움 0, DB 있음 (전량 매도)
    E_KIWOOM_ONLY = "E_KIWOOM_ONLY"        # 키움 있음, DB 0 (수동 신규)


@dataclass(frozen=True)
class KiwoomBalance:
    """키움 잔고."""
    stock_code: str
    quantity: int
    avg_price: int


@dataclass(frozen=True)
class SystemPosition:
    """시스템 DB 포지션 (집계)."""
    stock_code: str
    system_a_qty: int      # 경로 A 시스템 포지션
    system_b_qty: int      # 경로 B 시스템 포지션
    manual_qty: int        # MANUAL 포지션
    
    @property
    def total_qty(self) -> int:
        return self.system_a_qty + self.system_b_qty + self.manual_qty
    
    @property
    def system_total_qty(self) -> int:
        return self.system_a_qty + self.system_b_qty


@dataclass(frozen=True)
class ReconciliationAction:
    """정합성 조정 액션."""
    case: ReconciliationCase
    stock_code: str
    diff: int  # 수량 차이 (양수: 키움이 많음, 음수: DB가 많음)
    
    # 처리 액션
    add_manual_qty: int = 0
    reduce_manual_qty: int = 0
    reduce_system_a_qty: int = 0
    reduce_system_b_qty: int = 0
    invalidate_tracking: bool = False  # 시나리오 C에서 추적 종료
    
    # 알림 정보
    notify: bool = True
    notify_severity: str = "HIGH"
    notify_message: str = ""


def reconcile_position(
    kiwoom: Optional[KiwoomBalance],
    system: Optional[SystemPosition],
    is_in_tracking_box_set_state: bool = False,  # 시나리오 C 판정용
) -> ReconciliationAction:
    """
    단일 종목 정합성 확인 + 액션 결정.
    
    Args:
        kiwoom: 키움 잔고 (없으면 None)
        system: 시스템 DB 집계 (없으면 None)
        is_in_tracking_box_set_state: tracked_stock이 BOX_SET 상태인지
    
    Returns:
        ReconciliationAction: 처리할 액션
    
    Note:
        case별 처리:
          A: 액션 없음
          B: MANUAL_PYRAMID_BUY (시나리오 A) 또는 MANUAL_NEW (시나리오 D)
          C: MANUAL 우선 차감 후 시스템 차감
          D: tracked_stock EXITED 처리
          E: MANUAL 신규 등록 (시나리오 C 또는 D)
    """
    kiwoom_qty = kiwoom.quantity if kiwoom else 0
    system_qty = system.total_qty if system else 0
    
    # 시나리오 분기
    if kiwoom_qty == system_qty:
        return ReconciliationAction(
            case=ReconciliationCase.A_MATCH,
            stock_code=(kiwoom or system).stock_code if (kiwoom or system) else "",
            diff=0,
            notify=False,
            notify_message="일치",
        )
    
    diff = kiwoom_qty - system_qty
    stock_code = (kiwoom or system).stock_code
    
    if kiwoom_qty == 0 and system_qty > 0:
        # Case D: 시스템에 있는데 키움에 없음 → 전량 매도
        return ReconciliationAction(
            case=ReconciliationCase.D_DB_ONLY,
            stock_code=stock_code,
            diff=diff,
            reduce_manual_qty=system.manual_qty,
            reduce_system_a_qty=system.system_a_qty,
            reduce_system_b_qty=system.system_b_qty,
            notify_severity="HIGH",
            notify_message=f"수동 전량 매도: {stock_code} {system_qty}주",
        )
    
    if system_qty == 0 and kiwoom_qty > 0:
        # Case E: 시스템에 없는데 키움에 있음 → MANUAL 신규
        return ReconciliationAction(
            case=ReconciliationCase.E_KIWOOM_ONLY,
            stock_code=stock_code,
            diff=diff,
            add_manual_qty=kiwoom_qty,
            invalidate_tracking=is_in_tracking_box_set_state,  # 시나리오 C
            notify_severity="HIGH",
            notify_message=f"수동 매수 감지: {stock_code} {kiwoom_qty}주",
        )
    
    if diff > 0:
        # Case B: 사용자 추가 매수
        return ReconciliationAction(
            case=ReconciliationCase.B_MANUAL_BUY,
            stock_code=stock_code,
            diff=diff,
            add_manual_qty=diff,
            notify_severity="HIGH",
            notify_message=f"수동 추가 매수: {stock_code} {diff}주",
        )
    
    if diff < 0:
        # Case C: 사용자 부분 매도
        # 우선순위: MANUAL → 단일 경로 → 이중 경로 비례
        sold_qty = abs(diff)
        
        reduce_manual = min(sold_qty, system.manual_qty)
        remaining = sold_qty - reduce_manual
        
        if remaining == 0:
            # MANUAL만 차감
            return ReconciliationAction(
                case=ReconciliationCase.C_MANUAL_SELL,
                stock_code=stock_code,
                diff=diff,
                reduce_manual_qty=reduce_manual,
                notify_severity="HIGH",
                notify_message=f"수동 매도 (MANUAL): {stock_code} {sold_qty}주",
            )
        
        # 시스템 경로 차감
        if system.system_a_qty > 0 and system.system_b_qty == 0:
            # 단일 경로 A
            return ReconciliationAction(
                case=ReconciliationCase.C_MANUAL_SELL,
                stock_code=stock_code,
                diff=diff,
                reduce_manual_qty=reduce_manual,
                reduce_system_a_qty=remaining,
                notify_severity="HIGH",
                notify_message=f"수동 매도 (경로 A): {stock_code} {sold_qty}주",
            )
        elif system.system_b_qty > 0 and system.system_a_qty == 0:
            # 단일 경로 B
            return ReconciliationAction(
                case=ReconciliationCase.C_MANUAL_SELL,
                stock_code=stock_code,
                diff=diff,
                reduce_manual_qty=reduce_manual,
                reduce_system_b_qty=remaining,
                notify_severity="HIGH",
                notify_message=f"수동 매도 (경로 B): {stock_code} {sold_qty}주",
            )
        else:
            # 이중 경로 - 자동 비례 차감
            reduce_a, reduce_b = _allocate_proportional(
                remaining,
                system.system_a_qty,
                system.system_b_qty,
            )
            return ReconciliationAction(
                case=ReconciliationCase.C_MANUAL_SELL,
                stock_code=stock_code,
                diff=diff,
                reduce_manual_qty=reduce_manual,
                reduce_system_a_qty=reduce_a,
                reduce_system_b_qty=reduce_b,
                notify_severity="HIGH",
                notify_message=(
                    f"수동 매도 (이중 경로 비례): {stock_code} {sold_qty}주, "
                    f"A {reduce_a}주, B {reduce_b}주"
                ),
            )
    
    raise RuntimeError("Unreachable")


def _allocate_proportional(
    total_to_reduce: int,
    qty_a: int,
    qty_b: int,
) -> tuple[int, int]:
    """
    이중 경로 비례 차감 (큰 경로 우선 반올림).
    
    예시:
        total_to_reduce=10, qty_a=100, qty_b=50
        a 비율 = 100/150 = 0.667
        b 비율 = 50/150 = 0.333
        a 할당 = 10 × 0.667 = 6.67
        b 할당 = 10 × 0.333 = 3.33
        반올림: a=7, b=3 (큰 경로 우선)
    """
    total_qty = qty_a + qty_b
    if total_qty == 0:
        return 0, 0
    
    raw_a = total_to_reduce * qty_a / total_qty
    raw_b = total_to_reduce * qty_b / total_qty
    
    # 큰 경로 우선 반올림
    if qty_a >= qty_b:
        reduce_a = round(raw_a)
        reduce_b = total_to_reduce - reduce_a
    else:
        reduce_b = round(raw_b)
        reduce_a = total_to_reduce - reduce_b
    
    # 안전: 보유 수량 초과 방지
    reduce_a = min(reduce_a, qty_a)
    reduce_b = min(reduce_b, qty_b)
    
    return reduce_a, reduce_b
```

---

## §8. 스킬 8: test_template

### 8.1 목적

```yaml
테스트 작성의 표준 패턴:
  - Given-When-Then 구조
  - Fixture 표준
  - Mock 표준
  - 엣지 케이스 체크리스트
```

### 8.2 표준 템플릿

```python
# src/core/v71/skills/test_template.py

"""
V7.1 테스트 작성 표준 템플릿.

이 템플릿은 모든 V7.1 테스트의 기준입니다.
하네스 7 (Test Coverage Enforcer)이 패턴 검증.
"""

# ============================================================
# 1. 표준 import
# ============================================================
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
from uuid import uuid4

# 테스트 대상
from src.core.v71.skills.example_skill import (
    target_function,
    TargetClass,
)

# 헬퍼
from tests.v71.helpers import make_position, make_box, make_candle


# ============================================================
# 2. 표준 Fixture (conftest.py에서)
# ============================================================
@pytest.fixture
def base_position():
    """기본 포지션."""
    return PositionState(
        weighted_avg_price=100000,
        initial_avg_price=100000,
        total_quantity=100,
        profit_5_executed=False,
        profit_10_executed=False,
        ts_activated=False,
        ts_base_price=100000,
        ts_stop_price=None,
        fixed_stop_price=95000,
        actual_capital_invested=10000000,
    )


@pytest.fixture
def stage2_position(base_position):
    """단계 2 (+5% 청산 후)."""
    from dataclasses import replace
    return replace(
        base_position,
        profit_5_executed=True,
        ts_activated=True,
        ts_base_price=105000,
        fixed_stop_price=98000,
        total_quantity=70,
    )


@pytest.fixture
def stage3_position(stage2_position):
    """단계 3 (+10% 청산 후)."""
    from dataclasses import replace
    return replace(
        stage2_position,
        profit_10_executed=True,
        ts_base_price=110000,
        fixed_stop_price=104000,
        total_quantity=49,
    )


# ============================================================
# 3. 표준 테스트 클래스 패턴
# ============================================================
class TestTargetFunction:
    """target_function() 단위 테스트."""
    
    # 정상 경로 (Happy Path)
    def test_normal_case(self, base_position):
        """정상 케이스 1."""
        # Given
        input_value = 100
        
        # When
        result = target_function(base_position, input_value)
        
        # Then
        assert result.success is True
        assert result.value == 200
    
    # 분기 경로
    def test_alternative_path(self, base_position):
        """다른 분기."""
        # Given-When-Then
        ...
    
    # 엣지 케이스 (boundary)
    def test_boundary_zero(self):
        """입력 0."""
        with pytest.raises(ValueError):
            target_function(None, 0)
    
    def test_boundary_max(self):
        """최대값."""
        ...
    
    def test_boundary_negative(self):
        """음수."""
        with pytest.raises(ValueError):
            target_function(None, -1)
    
    def test_boundary_none_input(self):
        """None 입력."""
        ...
    
    # 실패 케이스
    def test_failure_invalid_state(self):
        """잘못된 상태."""
        ...
    
    def test_failure_external_error(self, mock_dependency):
        """외부 의존성 실패."""
        # Given
        mock_dependency.fetch.side_effect = Exception("Boom")
        
        # When/Then
        with pytest.raises(Exception):
            target_function(...)


# ============================================================
# 4. 비동기 테스트 표준 (pytest-asyncio)
# ============================================================
@pytest.mark.asyncio
class TestAsyncFunction:
    
    async def test_async_normal(self):
        """비동기 정상 케이스."""
        result = await async_function(...)
        assert result is not None
    
    async def test_async_timeout(self):
        """타임아웃."""
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_function(), timeout=0.1)


# ============================================================
# 5. Property-Based Testing (Hypothesis)
# ============================================================
from hypothesis import given, strategies as st


@given(
    avg_price=st.integers(min_value=1000, max_value=1000000),
    qty=st.integers(min_value=1, max_value=10000),
    buy_price=st.integers(min_value=1000, max_value=1000000),
    buy_qty=st.integers(min_value=1, max_value=10000),
)
def test_weighted_avg_invariant(avg_price, qty, buy_price, buy_qty):
    """평단가 불변식: 가중 평균은 두 가격 사이에 있다."""
    # When
    new_pos = update_position_after_buy(
        position=PositionState(
            weighted_avg_price=avg_price,
            total_quantity=qty,
            ...
        ),
        buy_price=buy_price,
        buy_qty=buy_qty,
    )
    
    # Then: 새 평단가는 [min(avg, buy), max(avg, buy)] 범위
    assert min(avg_price, buy_price) <= new_pos.weighted_avg_price <= max(avg_price, buy_price)


# ============================================================
# 6. Mock 패턴 표준
# ============================================================
@pytest.fixture
def mock_kiwoom_api():
    """키움 API 모킹."""
    api = AsyncMock()
    api.send_buy_order.return_value = MagicMock(
        success=True,
        data={"order_id": "ORDER123"},
    )
    return api


@pytest.fixture
def mock_db():
    """DB 모킹."""
    db = AsyncMock()
    return db


@pytest.fixture
def freezed_time():
    """시간 고정 (freezegun)."""
    from freezegun import freeze_time
    with freeze_time("2026-04-25 10:00:00"):
        yield


# ============================================================
# 7. 엣지 케이스 체크리스트 (모든 함수가 검토해야 할 것)
# ============================================================
"""
체크리스트:
  ☐ Happy path (정상)
  ☐ Boundary (0, max, min, MAX_INT)
  ☐ None / NaN / 빈 값
  ☐ 음수 (부적절한 경우)
  ☐ 매우 큰 값 (overflow)
  ☐ 매우 작은 값 (underflow)
  ☐ 빈 문자열, 빈 리스트
  ☐ 동시성 (race condition)
  ☐ 시간 의존 (장 마감, VI 등)
  ☐ 외부 의존성 실패
  ☐ 타임아웃
  ☐ 부분 실패 (트랜잭션 중간 실패)
"""
```

---

## §9. 스킬 사용 강제 메커니즘

### 9.1 하네스 3 통합

```yaml
하네스 3 (Trading Rule Enforcer)가 자동 검증:

차단 패턴:
  - import httpx (직접 HTTP 요청)
  - 매직 넘버 (0.05, 0.30, 0.04 등 하드코딩)
  - position.weighted_avg_price = ... (직접 수정)
  - telegram.send_message(...) (raw 호출)
  - DB 쿼리 직접 작성 (SELECT * FROM ...)

허용 패턴:
  - from src.core.v71.skills.* import ... (스킬 import)
  - V71Constants.* 사용
  - 스킬 함수 호출
```

### 9.2 코드 리뷰 체크리스트

```yaml
PR 머지 전 검토:
  ☐ 외부 API 호출이 kiwoom_api_skill 통하는가?
  ☐ 박스 진입 판정이 box_entry_skill 통하는가?
  ☐ 손절/익절 계산이 exit_calc_skill 통하는가?
  ☐ 평단가 변경이 avg_price_skill 통하는가?
  ☐ VI 처리가 vi_skill 통하는가?
  ☐ 알림이 notification_skill 통하는가?
  ☐ 정합성이 reconciliation_skill 통하는가?
  ☐ 테스트가 test_template 패턴 따르는가?
  ☐ 매직 넘버 없음 (V71Constants 사용)
  ☐ 타입 힌트 완전
  ☐ Docstring 완전
```

### 9.3 하네스 차단 시 응답

```python
# 하네스 3이 차단할 때 출력 예시:

"""
================================================================
HARNESS 3: TRADING RULE VIOLATION DETECTED
================================================================

FILE: src/core/v71/exit_executor.py
LINE: 42

VIOLATION:
  Direct magic number usage detected.
  
  Found:
    if (current - position.avg) / position.avg <= -0.05:
                                                      ^^^^^
  
  Required:
    Use V71Constants.STOP_LOSS_INITIAL_PCT
    Or use exit_calc_skill.calculate_effective_stop()

REASON:
  V7.1 Constitution Rule 5: 단순함 우선
  V7.1 Constitution Rule 3: 충돌 금지
  
  Magic numbers cause:
    - Inconsistency (same rule in multiple places)
    - Refactoring difficulty
    - Rule violation when constants change

REFERENCE:
  - 02_TRADING_RULES.md §5 (청산 룰)
  - 07_SKILLS_SPEC.md §3 (exit_calc_skill)
  - 02_TRADING_RULES.md 부록 A.4 (V71Constants)

REMEDY:
  1. Import skill:
     from src.core.v71.skills.exit_calc_skill import calculate_effective_stop
  
  2. Replace logic:
     result = calculate_effective_stop(position, current_price)
     if result.should_exit:
         await execute_market_sell(position)
  
  3. Re-run pre-commit:
     pre-commit run --all-files

BUILD STATUS: BLOCKED
================================================================
"""
```

---

## 부록 A: 스킬 빠른 참조

| 스킬 | 위치 | 주요 함수 | 사용 시점 |
|------|------|-----------|-----------|
| 1. kiwoom_api | `skills/kiwoom_api_skill.py` | `call_kiwoom_api()`, `send_buy_order()`, `send_sell_order()` | 모든 외부 API 호출 |
| 2. box_entry | `skills/box_entry_skill.py` | `evaluate_box_entry()`, `check_gap_up_for_path_b()` | 박스 진입 판정 |
| 3. exit_calc | `skills/exit_calc_skill.py` | `calculate_effective_stop()`, `check_profit_take()`, `update_trailing_stop()` | 청산 계산 |
| 4. avg_price | `skills/avg_price_skill.py` | `update_position_after_buy()`, `update_position_after_sell()` | 평단가 변경 |
| 5. vi | `skills/vi_skill.py` | `handle_vi_state()`, `check_post_vi_gap()` | VI 처리 |
| 6. notification | `skills/notification_skill.py` | `send_notification()`, `format_*_message()` | 알림 발송 |
| 7. reconciliation | `skills/reconciliation_skill.py` | `reconcile_position()`, `_allocate_proportional()` | 정합성 확인 |
| 8. test_template | `skills/test_template.py` | (템플릿) | 테스트 작성 시 참고 |

---

## 부록 B: 미정 사항

```yaml
B.1 키움 API 정확한 엔드포인트:
  - kt10000 (매수), kt10001 (매도) 등
  - 구현 시 키움 OpenAPI 문서 확인

B.2 ATR 값 계산 위치:
  - exit_calc_skill 외부에서 계산하여 인자로
  - 또는 indicator_library 활용

B.3 시간 의존 함수의 모킹:
  - freezegun 라이브러리
  - 또는 datetime 주입 패턴

B.4 reconciliation 호출 빈도:
  - 5분 vs 사용자 요청 시
  - 운영 데이터로 결정
```

---

*이 문서는 V7.1 스킬의 단일 진실 원천입니다.*  
*스킬 추가/수정 시 이 문서 갱신 필수.*  
*하네스 3이 모든 코드에서 스킬 사용을 강제합니다.*

*최종 업데이트: 2026-04-25*
