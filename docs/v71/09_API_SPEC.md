# V7.1 API 명세 (API Spec)

> 이 문서는 V7.1 시스템의 **백엔드 REST API + WebSocket**을 정의합니다.
> 
> Claude Design UI 작업과 프론트엔드 통합의 **단일 진실 원천**입니다.

---

## 목차

- [§0. API 설계 원칙](#0-api-설계-원칙)
- [§1. 인증 및 권한](#1-인증-및-권한)
- [§2. 공통 응답 형식](#2-공통-응답-형식)
- [§3. 추적 종목 API](#3-추적-종목-api)
- [§4. 박스 API](#4-박스-api)
- [§5. 포지션 API](#5-포지션-api)
- [§6. 거래 이벤트 API](#6-거래-이벤트-api)
- [§7. 알림 API](#7-알림-api)
- [§8. 리포트 API](#8-리포트-api)
- [§9. 시스템 API](#9-시스템-api)
- [§10. 설정 API](#10-설정-api)
- [§11. WebSocket](#11-websocket)
- [§12. 에러 코드](#12-에러-코드)

---

## §0. API 설계 원칙

### 0.1 RESTful 원칙

```yaml
URL 구조:
  /api/v71/<resource>/<id>?<filters>
  
HTTP 메서드:
  GET: 조회
  POST: 생성 또는 액션
  PATCH: 부분 수정
  PUT: 전체 교체 (가급적 PATCH 사용)
  DELETE: 삭제

명명:
  복수형 (boxes, positions)
  스네이크 케이스 (tracked_stocks)
  명사 우선 (액션은 sub-resource로)

상태 코드:
  200: 성공 (조회/수정)
  201: 생성됨
  204: 성공, 응답 본문 없음
  400: 클라이언트 에러 (검증 실패)
  401: 인증 실패
  403: 권한 부족
  404: 리소스 없음
  409: 충돌 (중복 등)
  422: 비즈니스 룰 위반
  429: Rate Limit 초과
  500: 서버 에러
```

### 0.2 V7.1 API 특화 원칙

```yaml
원칙 1: 사용자 판단 존중
  자동 추천 API 없음
  검색만 (사용자가 결정)

원칙 2: 거래 룰 표시 (Read-only)
  손절선 등은 GET으로 조회만
  PATCH로 직접 수정 금지
  (시스템이 룰대로 계산)

원칙 3: 멱등성
  같은 요청 두 번 보내도 같은 결과
  중복 박스 생성 등 방지

원칙 4: 페이지네이션
  리스트는 cursor 기반 페이지네이션
  최대 100개/요청

원칙 5: 시간대
  서버: UTC
  클라이언트: 한국 시간 (KST, UTC+9) 변환
  ISO 8601 형식
```

### 0.3 버전 관리

```yaml
URL 버전: /api/v71/...
  V7.1 전용

향후 호환:
  /api/v72/... (V7.2 추가 시)
  V7.1 6개월 이상 유지

Deprecated 알림:
  Header: X-API-Deprecated: true
  Header: X-API-Sunset: 2027-04-01
```

---

## §1. 인증 및 권한

### 1.1 인증 방식

```yaml
방식: JWT (Access + Refresh)
  Access Token: 1시간 유효
  Refresh Token: 24시간 유효

Header:
  Authorization: Bearer <access_token>

Refresh:
  POST /api/v71/auth/refresh
  Body: { "refresh_token": "..." }
  Response: 새 access_token

자동 로그아웃:
  30분 비활성 시
  새 IP 감지 시 알림
```

### 1.2 로그인 플로우

#### POST /api/v71/auth/login

```yaml
설명: 1단계 로그인 (ID/PW 검증)

Request:
  Content-Type: application/json
  
  {
    "username": "string (3-50자, 영숫자_)",
    "password": "string (8-128자)"
  }

Response 200 (TOTP 필요):
  {
    "totp_required": true,
    "session_id": "uuid (15분 유효)",
    "message": "TOTP 코드를 입력해주세요"
  }

Response 200 (TOTP 비활성):
  {
    "totp_required": false,
    "access_token": "jwt...",
    "refresh_token": "jwt...",
    "expires_in": 3600
  }

Response 401:
  {
    "error_code": "INVALID_CREDENTIALS",
    "message": "Invalid credentials"
  }

Response 429:
  {
    "error_code": "RATE_LIMIT_EXCEEDED",
    "message": "Too many login attempts",
    "retry_after_seconds": 60
  }

보안:
  - IP당 5회/분 Rate Limit
  - 실패 시 timing attack 방어 (랜덤 0.1~0.3초)
  - audit_logs 기록
```

#### POST /api/v71/auth/totp/verify

```yaml
설명: 2단계 로그인 (TOTP 검증)

Request:
  {
    "session_id": "uuid",
    "totp_code": "6자리 숫자"
  }

Response 200:
  {
    "access_token": "jwt...",
    "refresh_token": "jwt...",
    "expires_in": 3600
  }

Response 401:
  {
    "error_code": "INVALID_TOTP",
    "message": "Invalid TOTP code"
  }

부수 효과:
  - 새 IP 감지 시 텔레그램 CRITICAL 알림
  - audit_logs 기록 (LOGIN)
  - user_sessions 레코드 생성
```

#### POST /api/v71/auth/refresh

```yaml
Request:
  {
    "refresh_token": "jwt..."
  }

Response 200:
  {
    "access_token": "jwt...",
    "expires_in": 3600
  }

Response 401:
  {
    "error_code": "REFRESH_EXPIRED",
    "message": "Refresh token expired, please login again"
  }
```

#### POST /api/v71/auth/logout

```yaml
Request:
  Header: Authorization: Bearer <access_token>

Response 204: (no content)

부수 효과:
  - user_sessions revoked
  - audit_logs 기록
```

#### POST /api/v71/auth/totp/setup

```yaml
설명: 2FA 활성화 (최초 설정)

Request: (인증 필요)

Response 200:
  {
    "totp_secret": "BASE32...",
    "qr_code_url": "otpauth://totp/...",
    "backup_codes": ["1234-5678", ...]  # 10개
  }

다음 단계:
  사용자가 Google Authenticator 등록 후
  POST /api/v71/auth/totp/confirm 으로 활성화
```

#### POST /api/v71/auth/totp/confirm

```yaml
Request:
  {
    "totp_code": "6자리 (검증용)"
  }

Response 200:
  {
    "totp_enabled": true
  }

부수 효과:
  - users.totp_enabled = true
  - audit_logs (TOTP_ENABLED)
```

---

## §2. 공통 응답 형식

### 2.1 성공 응답

```json
// 단일 리소스
{
  "data": { ... },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-04-25T05:30:00Z"
  }
}

// 리스트
{
  "data": [...],
  "meta": {
    "total": 150,
    "limit": 20,
    "next_cursor": "eyJpZCI6Li4uLCJjcmVhdGVkX2F0IjoiLi4uIn0=",
    "request_id": "uuid",
    "timestamp": "2026-04-25T05:30:00Z"
  }
}
```

### 2.2 에러 응답

```json
{
  "error_code": "VALIDATION_FAILED",
  "message": "Box upper price must be greater than lower price",
  "details": {
    "field": "upper_price",
    "value": 95000,
    "constraint": "> lower_price (= 100000)"
  },
  "meta": {
    "request_id": "uuid",
    "timestamp": "2026-04-25T05:30:00Z"
  }
}
```

### 2.3 페이지네이션

```yaml
요청:
  GET /api/v71/boxes?limit=20&cursor=eyJ...

응답:
  data: [...]
  meta:
    total: 150 (선택, 비싼 쿼리는 생략)
    limit: 20
    next_cursor: "..." (다음 페이지)
    prev_cursor: "..." (이전 페이지, 선택)

cursor 인코딩:
  Base64(JSON({id, sort_field}))
  예: {"id": "uuid...", "created_at": "..."}

마지막 페이지:
  next_cursor: null
```

### 2.4 필터링 + 정렬

```yaml
공통 쿼리 파라미터:
  ?limit=20
  ?cursor=...
  ?sort=-created_at  # - 접두사: 내림차순
  ?status=BOX_SET    # 필터
  ?path_type=PATH_A
  ?stock_code=005930

날짜 필터:
  ?from_date=2026-04-01
  ?to_date=2026-04-25
  ?after=2026-04-25T00:00:00Z
  ?before=2026-04-25T23:59:59Z
```

---

## §3. 추적 종목 API

### 3.1 GET /api/v71/tracked_stocks

```yaml
설명: 추적 종목 리스트 조회

Query Parameters:
  status: TRACKING | BOX_SET | POSITION_OPEN | POSITION_PARTIAL | EXITED
  path_type: PATH_A | PATH_B
  stock_code: 종목 코드 (정확 일치)
  q: 검색어 (종목명 like)
  limit: 1-100 (기본 20)
  cursor: 페이지네이션
  sort: -created_at | -last_status_changed_at | stock_name

Response 200:
{
  "data": [
    {
      "id": "uuid",
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "market": "KOSPI",
      "path_type": "PATH_A",
      "status": "BOX_SET",
      "user_memo": "...",
      "source": "HTS",
      "vi_recovered_today": false,
      "auto_exit_reason": null,
      "created_at": "2026-04-25T01:00:00Z",
      "last_status_changed_at": "2026-04-25T03:30:00Z",
      
      // 집계 정보
      "summary": {
        "active_box_count": 3,
        "triggered_box_count": 0,
        "current_position_qty": 0,
        "current_position_avg_price": null
      }
    }
  ],
  "meta": {...}
}
```

### 3.2 POST /api/v71/tracked_stocks

```yaml
설명: 새 종목 추적 등록

Request:
{
  "stock_code": "005930",       // 필수, 6자리
  "path_type": "PATH_A",         // 필수
  "user_memo": "...",            // 선택
  "source": "HTS"                // 선택
}

검증:
  - stock_code 키움 API에 존재하는지
  - 같은 stock_code + path_type + 활성 추적 중복 차단

Response 201:
{
  "data": {
    "id": "uuid",
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "path_type": "PATH_A",
    "status": "TRACKING",
    "created_at": "2026-04-25T05:30:00Z",
    ...
  }
}

Response 409:
{
  "error_code": "DUPLICATE_TRACKING",
  "message": "삼성전자(005930) PATH_A 이미 추적 중입니다",
  "details": {
    "existing_id": "uuid"
  }
}
```

### 3.3 GET /api/v71/tracked_stocks/{id}

```yaml
설명: 단일 추적 종목 상세 조회

Response 200:
{
  "data": {
    "id": "uuid",
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "market": "KOSPI",
    "path_type": "PATH_A",
    "status": "BOX_SET",
    "user_memo": "...",
    
    // 박스 리스트 포함
    "boxes": [
      {
        "id": "uuid",
        "box_tier": 1,
        "upper_price": 74000,
        "lower_price": 73000,
        "position_size_pct": 10.0,
        "stop_loss_pct": -0.05,
        "strategy_type": "PULLBACK",
        "status": "WAITING",
        "created_at": "..."
      }
    ],
    
    // 포지션 (있다면)
    "positions": [
      {
        "id": "uuid",
        "source": "SYSTEM_A",
        "weighted_avg_price": 73500,
        "total_quantity": 100,
        "status": "OPEN",
        ...
      }
    ],
    
    "created_at": "...",
    "last_status_changed_at": "..."
  }
}
```

### 3.4 PATCH /api/v71/tracked_stocks/{id}

```yaml
설명: 추적 종목 정보 수정 (메모 등)

Request:
{
  "user_memo": "...",
  "source": "..."
}

수정 가능 필드:
  - user_memo
  - source
  
수정 불가:
  - stock_code (생성 후 변경 불가)
  - path_type (변경 불가)
  - status (시스템이 관리)

Response 200:
{
  "data": {...}
}
```

### 3.5 DELETE /api/v71/tracked_stocks/{id}

```yaml
설명: 추적 종료 (수동)

처리:
  - 모든 미진입 박스 CANCELLED
  - 보유 포지션 있으면 거부 (먼저 청산 필요)
  - tracked_stocks.status = EXITED
  - 시세 구독 해제

Response 204: (no content)

Response 422:
{
  "error_code": "ACTIVE_POSITION_EXISTS",
  "message": "보유 포지션이 있어 추적 종료 불가",
  "details": {
    "position_count": 1,
    "total_quantity": 100
  }
}
```

### 3.6 POST /api/v71/stocks/search

```yaml
설명: 종목 검색 (등록 전 lookup)

Request:
{
  "q": "삼성"  // 종목명 또는 코드
}

Response 200:
{
  "data": [
    {
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "market": "KOSPI",
      "current_price": 73500,
      "is_managed": false,
      "is_warning": false
    },
    {
      "stock_code": "005935",
      "stock_name": "삼성전자우",
      "market": "KOSPI",
      "current_price": 65000,
      "is_managed": false,
      "is_warning": false
    }
  ]
}

데이터 소스:
  - 캐시: stocks 테이블 (있으면)
  - 또는 키움 API 실시간 조회
```

---

## §4. 박스 API

### 4.1 POST /api/v71/boxes

```yaml
설명: 박스 생성

Request:
{
  "tracked_stock_id": "uuid",
  "upper_price": 74000,
  "lower_price": 73000,
  "position_size_pct": 10.0,
  "stop_loss_pct": -0.05,         // 선택, 기본 -0.05
  "strategy_type": "PULLBACK",     // PULLBACK | BREAKOUT
  "memo": "..."                    // 선택
}

검증:
  - tracked_stock 존재 + 사용자 소유
  - upper > lower
  - 0 < position_size_pct <= 100
  - stop_loss_pct < 0
  - 박스 겹침 검증 (같은 종목 + 같은 path)
  - 종목 총 비중 30% 한도 검증 (실제 포지션 기준 + 신규 박스)

자동 처리:
  - tracked_stock.status: TRACKING → BOX_SET (전이 가능 시)
  - box_tier: 자동 부여 (가격 순)

Response 201:
{
  "data": {
    "id": "uuid",
    "tracked_stock_id": "uuid",
    "box_tier": 1,
    "upper_price": 74000,
    "lower_price": 73000,
    "position_size_pct": 10.0,
    "stop_loss_pct": -0.05,
    "strategy_type": "PULLBACK",
    "status": "WAITING",
    "memo": "...",
    "created_at": "...",
    "modified_at": "..."
  }
}

Response 422 (겹침):
{
  "error_code": "BOX_OVERLAP",
  "message": "박스 가격 범위가 기존 박스와 겹칩니다",
  "details": {
    "existing_box_id": "uuid",
    "existing_range": {"upper": 73500, "lower": 72500}
  }
}

Response 422 (한도):
{
  "error_code": "POSITION_LIMIT_EXCEEDED",
  "message": "종목당 30% 한도 초과",
  "details": {
    "current_actual_pct": 25.0,
    "requested_pct": 10.0,
    "limit_pct": 30.0
  }
}
```

### 4.2 GET /api/v71/boxes

```yaml
설명: 박스 리스트

Query:
  tracked_stock_id: 특정 종목의 박스
  status: WAITING | TRIGGERED | INVALIDATED | CANCELLED
  strategy_type: PULLBACK | BREAKOUT
  limit, cursor, sort

Response 200:
{
  "data": [
    {
      "id": "uuid",
      "tracked_stock_id": "uuid",
      "stock_code": "005930",        // join
      "stock_name": "삼성전자",       // join
      "path_type": "PATH_A",         // join
      "box_tier": 1,
      "upper_price": 74000,
      "lower_price": 73000,
      "position_size_pct": 10.0,
      "stop_loss_pct": -0.05,
      "strategy_type": "PULLBACK",
      "status": "WAITING",
      "memo": "...",
      "created_at": "...",
      
      // 진입 임박도 (선택)
      "entry_proximity_pct": 1.5  // 현재가 기준 박스 상단까지 +1.5%
    }
  ]
}
```

### 4.3 GET /api/v71/boxes/{id}

```yaml
설명: 박스 상세

Response 200:
{
  "data": {
    "id": "uuid",
    ... (위 필드),
    
    // 트리거 정보 (TRIGGERED 시)
    "triggered_at": "...",
    "triggered_position_id": "uuid",
    
    // 무효화 정보 (INVALIDATED 시)
    "invalidated_at": "...",
    "invalidation_reason": "MANUAL_BUY_DETECTED",
    
    // 다음 알림 시간
    "next_reminder_at": "2026-05-25T05:30:00Z"
  }
}
```

### 4.4 PATCH /api/v71/boxes/{id}

```yaml
설명: 박스 수정

Request:
{
  "upper_price": 74500,
  "lower_price": 73500,
  "position_size_pct": 12.0,
  "stop_loss_pct": -0.04,
  "memo": "..."
}

수정 가능:
  status가 WAITING이면 모든 필드
  status가 TRIGGERED면:
    - 매수 완료된 박스: 수정 불가
    - 별도 미진입 박스라면 위 룰 적용

수정 불가:
  - tracked_stock_id
  - box_tier (자동)
  - status (시스템 관리)
  - strategy_type (재생성 필요)

손절폭 완화 시 (예: -0.05 → -0.07):
  Response Header: X-Warning: STOP_LOSS_RELAXED

Response 200:
{
  "data": {...}
}

Response 422:
{
  "error_code": "BOX_NOT_EDITABLE",
  "message": "이미 매수 실행된 박스는 수정 불가",
  "details": {"current_status": "TRIGGERED"}
}
```

### 4.5 DELETE /api/v71/boxes/{id}

```yaml
설명: 박스 삭제

처리:
  - 미체결 매수 주문 자동 취소
  - status: CANCELLED
  - 마지막 박스 삭제 시 tracked_stock.status: BOX_SET → TRACKING (전이 가능 시)

Response 204:

Response 422:
{
  "error_code": "BOX_TRIGGERED_CANNOT_DELETE",
  "message": "매수 실행된 박스는 삭제 불가 (포지션 청산 필요)"
}
```

---

## §5. 포지션 API

### 5.1 GET /api/v71/positions

```yaml
설명: 포지션 리스트

Query:
  source: SYSTEM_A | SYSTEM_B | MANUAL
  status: OPEN | PARTIAL_CLOSED | CLOSED
  stock_code, limit, cursor, sort

Response 200:
{
  "data": [
    {
      "id": "uuid",
      "source": "SYSTEM_A",
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "tracked_stock_id": "uuid",
      "triggered_box_id": "uuid",
      
      // 평단가/수량
      "initial_avg_price": 73500,
      "weighted_avg_price": 73500,
      "total_quantity": 100,
      
      // 손절선
      "fixed_stop_price": 69825,    // 73500 × 0.95
      
      // 이벤트
      "profit_5_executed": false,
      "profit_10_executed": false,
      
      // TS
      "ts_activated": false,
      "ts_base_price": 73500,
      "ts_stop_price": null,
      "ts_active_multiplier": null,
      
      // 한도
      "actual_capital_invested": 7350000,
      
      // 상태
      "status": "OPEN",
      
      // 실시간 (선택, WebSocket으로 받는 게 효율)
      "current_price": 74200,
      "pnl_amount": 70000,
      "pnl_pct": 0.0095,
      
      // 청산 정보 (CLOSED 시)
      "closed_at": null,
      "final_pnl": null,
      "close_reason": null,
      
      "created_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### 5.2 GET /api/v71/positions/{id}

```yaml
설명: 단일 포지션 상세 + 이벤트 히스토리

Response 200:
{
  "data": {
    "id": "uuid",
    ... (위 필드),
    
    // 거래 이벤트 (시간순)
    "events": [
      {
        "id": "uuid",
        "event_type": "BUY_EXECUTED",
        "price": 73500,
        "quantity": 100,
        "occurred_at": "2026-04-25T01:30:00Z"
      },
      ...
    ],
    
    // 유효 청산선 계산 결과 (실시간)
    "effective_stop": {
      "fixed_stop": 69825,
      "ts_stop": null,
      "effective": 69825,
      "should_exit": false
    }
  }
}
```

### 5.3 GET /api/v71/positions/summary

```yaml
설명: 전체 포지션 요약 (대시보드)

Response 200:
{
  "data": {
    "total_positions": 5,
    "total_capital_invested": 30500000,
    "total_capital_pct": 30.5,    // 총 자본 대비
    "total_pnl_amount": 450000,
    "total_pnl_pct": 0.0148,
    
    "by_source": {
      "SYSTEM_A": {"count": 3, "capital": 18000000},
      "SYSTEM_B": {"count": 1, "capital": 8000000},
      "MANUAL": {"count": 1, "capital": 4500000}
    },
    
    "by_status": {
      "OPEN": 3,
      "PARTIAL_CLOSED": 2,
      "CLOSED": 0  // 오늘 청산된 것 (별도 쿼리)
    },
    
    "top_pnl": [...],   // 상위 5개
    "bottom_pnl": [...], // 하위 5개
    
    "stocks_at_limit": [  // 종목당 한도 임박
      {
        "stock_code": "005930",
        "actual_pct": 28.5,
        "limit_pct": 30.0
      }
    ]
  }
}
```

### 5.4 POST /api/v71/positions/reconcile

```yaml
설명: 정합성 확인 수동 트리거

Request: (인증 필요)

Response 202:  // Accepted, async
{
  "data": {
    "task_id": "uuid",
    "started_at": "...",
    "estimated_seconds": 30
  }
}

상태 조회:
  GET /api/v71/system/tasks/{task_id}

부수 효과:
  - reconciliation_skill 호출
  - 차이 발견 시 시나리오 처리
  - 텔레그램 알림
```

---

## §6. 거래 이벤트 API

### 6.1 GET /api/v71/trade_events

```yaml
설명: 거래 이벤트 리스트 (audit trail)

Query:
  position_id: 특정 포지션의 이벤트
  tracked_stock_id: 특정 종목
  event_type: BUY_EXECUTED | PROFIT_TAKE_5 | STOP_LOSS | ...
  from_date, to_date: 기간
  stock_code
  limit, cursor

Response 200:
{
  "data": [
    {
      "id": "uuid",
      "position_id": "uuid",
      "tracked_stock_id": "uuid",
      "box_id": "uuid",
      "stock_code": "005930",
      "stock_name": "삼성전자",
      "event_type": "BUY_EXECUTED",
      
      "price": 73500,
      "quantity": 100,
      
      "order_id": "ORDER123",
      "client_order_id": "OWN_uuid",
      "attempt": 1,
      
      "pnl_amount": null,
      "pnl_pct": null,
      
      "avg_price_before": null,
      "avg_price_after": 73500,
      
      "payload": {...},
      "reason": "박스 1차 진입",
      "error_message": null,
      
      "occurred_at": "2026-04-25T01:30:00Z"
    }
  ]
}
```

### 6.2 GET /api/v71/trade_events/today

```yaml
설명: 오늘 거래 요약 (대시보드 / 일일 마감)

Response 200:
{
  "data": {
    "date": "2026-04-25",
    "total_pnl": 245000,
    "total_pnl_pct": 0.0124,
    
    "buys": [
      {"stock_code": "005930", "quantity": 100, "price": 73500, "occurred_at": "..."},
      ...
    ],
    "sells": [
      {"stock_code": "036040", "quantity": 30, "price": 17800, 
       "pnl": 50000, "pnl_pct": 0.052, 
       "reason": "PROFIT_TAKE_5", "occurred_at": "..."},
      ...
    ],
    
    "auto_exits": [...],  // 자동 이탈
    "manual_trades": [...] // 수동 거래
  }
}
```

---

## §7. 알림 API

### 7.1 GET /api/v71/notifications

```yaml
설명: 알림 이력 + 큐 상태

Query:
  severity: CRITICAL | HIGH | MEDIUM | LOW
  status: PENDING | SENT | FAILED | SUPPRESSED
  event_type
  stock_code
  from_date, to_date
  limit, cursor

Response 200:
{
  "data": [
    {
      "id": "uuid",
      "severity": "CRITICAL",
      "channel": "BOTH",
      "event_type": "STOP_LOSS",
      "stock_code": "036040",
      "title": "[CRITICAL] 손절 실행",
      "message": "...",
      "payload": {...},
      "status": "SENT",
      "sent_at": "...",
      "created_at": "..."
    }
  ]
}
```

### 7.2 GET /api/v71/notifications/unread

```yaml
설명: 미확인 웹 알림 (CRITICAL/HIGH 중)

Response 200:
{
  "data": {
    "unread_count": 3,
    "items": [
      {
        "id": "uuid",
        "severity": "HIGH",
        "title": "...",
        "message": "...",
        "stock_code": "...",
        "created_at": "..."
      }
    ]
  }
}
```

### 7.3 POST /api/v71/notifications/{id}/mark_read

```yaml
설명: 알림 읽음 처리

Response 204:
```

### 7.4 POST /api/v71/notifications/test

```yaml
설명: 알림 시스템 테스트 (운영 전 검증)

Request:
{
  "severity": "MEDIUM",
  "channel": "TELEGRAM"
}

Response 200:
{
  "data": {
    "notification_id": "uuid",
    "status": "SENT",
    "sent_at": "..."
  }
}
```

---

## §8. 리포트 API

### 8.1 POST /api/v71/reports/request

```yaml
설명: 종목 리포트 생성 요청 (Claude Opus 4.7)

Request:
{
  "stock_code": "005930",
  "tracked_stock_id": "uuid"  // 선택, 컨텍스트 풍부화
}

처리:
  비동기 작업 (3~5분 소요 예상)
  task_id 반환

Response 202:
{
  "data": {
    "report_id": "uuid",
    "status": "PENDING",
    "estimated_seconds": 300,
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "requested_at": "..."
  }
}

비용 한도 (선택):
  월 10건 무료, 초과 시 알림
  Response 429: BUDGET_EXCEEDED
```

### 8.2 GET /api/v71/reports/{id}

```yaml
설명: 리포트 조회

Response 200 (생성 중):
{
  "data": {
    "id": "uuid",
    "status": "GENERATING",
    "progress": 60,  // 0-100
    "elapsed_seconds": 180
  }
}

Response 200 (완료):
{
  "data": {
    "id": "uuid",
    "stock_code": "005930",
    "stock_name": "삼성전자",
    "status": "COMPLETED",
    "model_version": "claude-opus-4-7",
    "prompt_tokens": 8500,
    "completion_tokens": 4200,
    
    // PART 1: 이야기 (서사)
    "narrative_part": "...",  // Markdown
    
    // PART 2: 객관 팩트
    "facts_part": "...",      // Markdown
    
    "data_sources": {...},
    
    "pdf_path": "/api/v71/reports/{id}/pdf",
    "excel_path": "/api/v71/reports/{id}/excel",
    
    "user_notes": null,
    
    "generation_started_at": "...",
    "generation_completed_at": "...",
    "generation_duration_seconds": 245,
    "created_at": "..."
  }
}

Response 200 (실패):
{
  "data": {
    "id": "uuid",
    "status": "FAILED",
    "error_message": "Claude API timeout"
  }
}
```

### 8.3 GET /api/v71/reports

```yaml
설명: 리포트 리스트

Query:
  stock_code: 특정 종목 리포트
  status: PENDING | GENERATING | COMPLETED | FAILED
  from_date, to_date
  limit, cursor

Response 200:
{
  "data": [...],
  "meta": {...}
}
```

### 8.4 GET /api/v71/reports/{id}/pdf

```yaml
설명: PDF 다운로드

Response 200:
  Content-Type: application/pdf
  Content-Disposition: attachment; filename="report_005930_2026-04-25.pdf"
  
  [PDF binary]
```

### 8.5 GET /api/v71/reports/{id}/excel

```yaml
설명: Excel 다운로드

Response 200:
  Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
  Content-Disposition: attachment; filename="report_005930_2026-04-25.xlsx"
```

### 8.6 PATCH /api/v71/reports/{id}

```yaml
설명: 사용자 메모 추가

Request:
{
  "user_notes": "..."
}

Response 200:
{
  "data": {...}
}
```

---

## §9. 시스템 API

### 9.1 GET /api/v71/system/status

```yaml
설명: 시스템 상태 (대시보드 헤더)

Response 200:
{
  "data": {
    "status": "RUNNING",  // RUNNING | SAFE_MODE | RECOVERING
    "uptime_seconds": 86400,
    
    "websocket": {
      "connected": true,
      "last_disconnect_at": null,
      "reconnect_count_today": 0
    },
    
    "kiwoom_api": {
      "available": true,
      "rate_limit_used_per_sec": 1.2,
      "rate_limit_max": 4.5
    },
    
    "telegram_bot": {
      "active": true,
      "circuit_breaker_state": "CLOSED"
    },
    
    "database": {
      "connected": true,
      "latency_ms": 5
    },
    
    "feature_flags": {
      "v71.box_system": true,
      "v71.exit_system": true,
      ...
    },
    
    "market": {
      "is_open": true,
      "session": "REGULAR",  // PRE | REGULAR | POST
      "next_open_at": null,
      "next_close_at": "2026-04-25T06:30:00Z"  // 15:30 KST
    },
    
    "current_time": "2026-04-25T05:30:00Z"
  }
}
```

### 9.2 GET /api/v71/system/health

```yaml
설명: 헬스 체크 (모니터링용)

Response 200:
{
  "data": {
    "status": "healthy",
    "checks": {
      "db": "ok",
      "kiwoom": "ok",
      "websocket": "ok",
      "telegram": "ok"
    }
  }
}

Response 503:
{
  "data": {
    "status": "degraded",
    "checks": {
      "db": "ok",
      "kiwoom": "ok",
      "websocket": "fail",
      "telegram": "ok"
    },
    "details": {
      "websocket": "Disconnected, reconnecting (Phase 2)"
    }
  }
}
```

### 9.3 POST /api/v71/system/safe_mode

```yaml
설명: 수동 안전 모드 진입 (텔레그램 /stop 명령어와 동일)

Request:
{
  "reason": "..."
}

처리:
  - 신규 매수 차단
  - 신규 박스 등록 차단
  - 기존 포지션 관리는 계속

Response 200:
{
  "data": {
    "safe_mode": true,
    "entered_at": "..."
  }
}
```

### 9.4 POST /api/v71/system/resume

```yaml
설명: 안전 모드 해제

Response 200:
{
  "data": {
    "safe_mode": false,
    "resumed_at": "..."
  }
}
```

### 9.5 GET /api/v71/system/restarts

```yaml
설명: 재시작 이력

Query: limit, cursor, from_date

Response 200:
{
  "data": [
    {
      "id": "uuid",
      "restart_at": "...",
      "recovery_completed_at": "...",
      "recovery_duration_seconds": 45,
      "reason": "KNOWN_DEPLOY",
      "reason_detail": "...",
      "reconciliation_summary": {
        "case_a": 5, "case_b": 0, ...
      },
      "cancelled_orders_count": 0
    }
  ]
}
```

### 9.6 GET /api/v71/system/tasks/{task_id}

```yaml
설명: 비동기 작업 상태 조회

Response 200:
{
  "data": {
    "task_id": "uuid",
    "type": "RECONCILIATION",
    "status": "RUNNING",  // PENDING | RUNNING | COMPLETED | FAILED
    "progress": 75,
    "started_at": "...",
    "completed_at": null,
    "result": null  // 완료 시 결과
  }
}
```

### 9.7 POST /api/v71/system/audit/box_entry_miss

```yaml
설명: 박스 진입 누락 감사 수동 실행

처리:
  당일 모든 BOX_SET 종목 점검
  봉 데이터로 진입 조건 충족 여부 검증

Response 202:
{
  "data": {
    "task_id": "uuid",
    "checked_stocks": 0,  // 진행 중
    "found_misses": 0
  }
}
```

---

## §10. 설정 API

### 10.1 GET /api/v71/settings

```yaml
설명: 사용자 설정 조회

Response 200:
{
  "data": {
    "total_capital": 100000000,  // 1억원
    
    "notify_critical": true,    // 강제 ON
    "notify_high": true,
    "notify_medium": true,
    "notify_low": true,
    
    "quiet_hours_enabled": false,
    "quiet_hours_start": null,
    "quiet_hours_end": null,
    
    "theme": "dark",
    "language": "ko",
    
    "preferences": {...},
    
    "telegram_chat_id": "1234567890",
    "totp_enabled": true,
    
    "updated_at": "..."
  }
}
```

### 10.2 PATCH /api/v71/settings

```yaml
설명: 설정 변경

Request:
{
  "total_capital": 100000000,
  "notify_high": true,
  "theme": "dark",
  "preferences": {...}
}

검증:
  notify_critical = false 시도 → 거부 (안전장치)
  total_capital > 0

Response 200:
{
  "data": {...}
}

Response 422:
{
  "error_code": "CRITICAL_NOTIFICATION_REQUIRED",
  "message": "CRITICAL 알림은 비활성화할 수 없습니다"
}
```

### 10.3 GET /api/v71/settings/feature_flags

```yaml
설명: Feature Flag 상태

권한: ADMIN/OWNER

Response 200:
{
  "data": {
    "v71": {
      "box_system": true,
      "exit_system": true,
      "vi_monitor": true,
      ...
    }
  }
}
```

### 10.4 PATCH /api/v71/settings/feature_flags

```yaml
설명: Feature Flag 변경 (런타임)

Request:
{
  "v71.box_system": false  // 즉시 비활성화 (긴급)
}

Response 200:
{
  "data": {...}
}

부수 효과:
  - audit_logs 기록
  - 텔레그램 알림 (CRITICAL)
  - 시스템 즉시 반영
```

---

## §11. WebSocket

### 11.1 연결

```yaml
URL: wss://server.com/api/v71/ws

연결 인증:
  Authorization Header (HTTP Upgrade 시)
  Bearer <access_token>

또는 Query:
  wss://server.com/api/v71/ws?token=<access_token>

연결 후:
  서버가 연결 확인 메시지 발송:
  {
    "type": "CONNECTION_ESTABLISHED",
    "session_id": "uuid",
    "server_time": "..."
  }

Heartbeat:
  클라이언트 → 서버: { "type": "PING" } (30초마다)
  서버 → 클라이언트: { "type": "PONG" }
```

### 11.2 구독 관리

```yaml
구독:
  → { "type": "SUBSCRIBE", "channels": ["positions", "boxes", "notifications"] }
  ← { "type": "SUBSCRIBED", "channels": [...] }

구독 해제:
  → { "type": "UNSUBSCRIBE", "channels": [...] }

채널:
  - positions: 포지션 변동 (가격 + 손익)
  - boxes: 박스 진입 임박/실행
  - notifications: 신규 알림 (CRITICAL/HIGH)
  - system: 시스템 상태 변경
  - tracked_stocks: 추적 종목 상태 변경
```

### 11.3 이벤트 (서버 → 클라이언트)

#### positions 채널

```json
// 가격 업데이트 (1초마다 또는 변동 시)
{
  "type": "POSITION_PRICE_UPDATE",
  "channel": "positions",
  "data": {
    "position_id": "uuid",
    "stock_code": "005930",
    "current_price": 74200,
    "pnl_amount": 70000,
    "pnl_pct": 0.0095,
    "timestamp": "..."
  }
}

// 포지션 변경 (이벤트 발생 시)
{
  "type": "POSITION_CHANGED",
  "channel": "positions",
  "data": {
    "position_id": "uuid",
    "event": "PROFIT_TAKE_5",
    "old_quantity": 100,
    "new_quantity": 70,
    "trigger_price": 77175,
    ...
  }
}

// 신규 포지션
{
  "type": "POSITION_OPENED",
  "channel": "positions",
  "data": {...}
}

// 청산
{
  "type": "POSITION_CLOSED",
  "channel": "positions",
  "data": {
    "position_id": "uuid",
    "close_reason": "STOP_LOSS",
    "final_pnl": -250000,
    "final_pnl_pct": -0.05
  }
}
```

#### boxes 채널

```json
// 박스 진입 임박 (±5%)
{
  "type": "BOX_ENTRY_PROXIMITY",
  "channel": "boxes",
  "data": {
    "box_id": "uuid",
    "stock_code": "005930",
    "current_price": 74100,
    "upper_price": 74000,
    "proximity_pct": 0.13,  // +0.13%
    "timestamp": "..."
  }
}

// 박스 트리거 (매수 직전)
{
  "type": "BOX_TRIGGERED",
  "channel": "boxes",
  "data": {
    "box_id": "uuid",
    "trigger_price": 74050,
    "buy_order_id": "ORDER123"
  }
}

// 박스 무효화
{
  "type": "BOX_INVALIDATED",
  "channel": "boxes",
  "data": {
    "box_id": "uuid",
    "reason": "AUTO_EXIT_BOX_DROP"
  }
}
```

#### notifications 채널

```json
{
  "type": "NEW_NOTIFICATION",
  "channel": "notifications",
  "data": {
    "id": "uuid",
    "severity": "CRITICAL",
    "title": "[CRITICAL] 손절 실행",
    "message": "...",
    "stock_code": "036040",
    "created_at": "..."
  }
}
```

#### system 채널

```json
// WebSocket 끊김
{
  "type": "WEBSOCKET_DISCONNECTED",
  "channel": "system",
  "data": {
    "duration_seconds": 15,
    "reconnect_phase": "PHASE_1"
  }
}

// VI 발동
{
  "type": "VI_TRIGGERED",
  "channel": "system",
  "data": {
    "stock_code": "005930",
    "trigger_price": 80500,
    "resume_at": "..."
  }
}

// 시스템 재시작
{
  "type": "SYSTEM_RESTARTING",
  "channel": "system",
  "data": {
    "reason": "DEPLOYMENT",
    "estimated_recovery_seconds": 60
  }
}
```

### 11.4 클라이언트 → 서버

```json
// PING/PONG
{ "type": "PING" }

// 구독
{ "type": "SUBSCRIBE", "channels": ["positions"] }
{ "type": "UNSUBSCRIBE", "channels": ["positions"] }
```

### 11.5 재연결 전략

```yaml
클라이언트 측:
  연결 끊김 시 지수 백오프
    1초 → 2초 → 4초 → 8초 → 16초
    이후 30초 간격
  
  재연결 시:
    재구독 자동
    마지막 수신 메시지 ID로 누락 검사 (선택)

서버 측:
  세션 ID로 재연결 인식
  최근 N초간의 이벤트 버퍼 보관 (선택)
```

---

## §12. 에러 코드

### 12.1 표준 에러 코드

```yaml
# 인증/권한
INVALID_CREDENTIALS         # 401: 잘못된 ID/PW
INVALID_TOTP                # 401: 잘못된 TOTP
SESSION_EXPIRED             # 401: 세션 만료
REFRESH_EXPIRED             # 401: refresh token 만료
UNAUTHORIZED                # 401: 인증 필요
FORBIDDEN                   # 403: 권한 부족
NEW_IP_BLOCKED              # 403: 새 IP 차단 (옵션)

# 검증
VALIDATION_FAILED           # 400: 일반 검증 실패
INVALID_STOCK_CODE          # 400: 종목 코드 오류
INVALID_PRICE               # 400: 가격 오류
INVALID_PERCENTAGE          # 400: 비율 오류
INVALID_DATE                # 400: 날짜 오류
INVALID_PARAMETER           # 400: 파라미터 오류

# 리소스
NOT_FOUND                   # 404: 리소스 없음
TRACKED_STOCK_NOT_FOUND     # 404
BOX_NOT_FOUND               # 404
POSITION_NOT_FOUND          # 404
REPORT_NOT_FOUND            # 404

# 충돌
DUPLICATE_TRACKING          # 409: 중복 추적
BOX_OVERLAP                 # 409: 박스 겹침
POSITION_LIMIT_EXCEEDED     # 422: 한도 초과
ACTIVE_POSITION_EXISTS      # 422: 활성 포지션 존재

# 비즈니스 룰
BOX_NOT_EDITABLE            # 422: 박스 수정 불가
BOX_TRIGGERED_CANNOT_DELETE # 422: 트리거된 박스 삭제 불가
TRACKING_HAS_POSITION       # 422: 보유 중 추적 종료 불가
CRITICAL_NOTIFICATION_REQUIRED # 422: CRITICAL OFF 불가
SAFE_MODE_ACTIVE            # 422: 안전 모드 중

# Rate Limit / 자원
RATE_LIMIT_EXCEEDED         # 429: API 한도 초과
LOGIN_RATE_LIMIT            # 429: 로그인 시도 초과
BUDGET_EXCEEDED             # 429: 리포트 예산 초과 (선택)

# 외부 시스템
KIWOOM_API_ERROR            # 502: 키움 API 에러
KIWOOM_TIMEOUT              # 504: 키움 타임아웃
DB_ERROR                    # 500: DB 에러
CLAUDE_API_ERROR            # 502: Claude API 에러

# 시스템
INTERNAL_ERROR              # 500: 일반 서버 에러
SERVICE_UNAVAILABLE         # 503: 시스템 다운
```

### 12.2 에러 응답 예시

```json
// 검증 실패
{
  "error_code": "VALIDATION_FAILED",
  "message": "박스 가격 검증 실패",
  "details": {
    "fields": [
      {
        "field": "upper_price",
        "value": 73000,
        "constraint": "must be > lower_price (74000)"
      }
    ]
  }
}

// 한도 초과
{
  "error_code": "POSITION_LIMIT_EXCEEDED",
  "message": "종목당 30% 한도 초과",
  "details": {
    "stock_code": "005930",
    "current_pct": 25.0,
    "requested_pct": 10.0,
    "limit_pct": 30.0
  }
}

// Rate Limit
{
  "error_code": "RATE_LIMIT_EXCEEDED",
  "message": "API rate limit exceeded",
  "details": {
    "limit": 100,
    "window": "1 minute",
    "retry_after_seconds": 30
  }
}
```

---

## 부록 A: API 빠른 참조

| 분류 | 메서드 | 엔드포인트 | 설명 |
|------|--------|-----------|------|
| Auth | POST | /api/v71/auth/login | 1단계 로그인 |
| Auth | POST | /api/v71/auth/totp/verify | 2단계 TOTP |
| Auth | POST | /api/v71/auth/refresh | 토큰 갱신 |
| Auth | POST | /api/v71/auth/logout | 로그아웃 |
| Tracked | GET | /api/v71/tracked_stocks | 추적 종목 리스트 |
| Tracked | POST | /api/v71/tracked_stocks | 추적 등록 |
| Tracked | GET | /api/v71/tracked_stocks/{id} | 단일 조회 |
| Tracked | PATCH | /api/v71/tracked_stocks/{id} | 메모 수정 |
| Tracked | DELETE | /api/v71/tracked_stocks/{id} | 추적 종료 |
| Tracked | POST | /api/v71/stocks/search | 종목 검색 |
| Box | POST | /api/v71/boxes | 박스 생성 |
| Box | GET | /api/v71/boxes | 박스 리스트 |
| Box | GET | /api/v71/boxes/{id} | 박스 상세 |
| Box | PATCH | /api/v71/boxes/{id} | 박스 수정 |
| Box | DELETE | /api/v71/boxes/{id} | 박스 삭제 |
| Position | GET | /api/v71/positions | 포지션 리스트 |
| Position | GET | /api/v71/positions/{id} | 포지션 상세 |
| Position | GET | /api/v71/positions/summary | 전체 요약 |
| Position | POST | /api/v71/positions/reconcile | 정합성 확인 |
| Event | GET | /api/v71/trade_events | 거래 이벤트 |
| Event | GET | /api/v71/trade_events/today | 오늘 거래 |
| Notif | GET | /api/v71/notifications | 알림 이력 |
| Notif | GET | /api/v71/notifications/unread | 미확인 |
| Notif | POST | /api/v71/notifications/{id}/mark_read | 읽음 처리 |
| Report | POST | /api/v71/reports/request | 리포트 생성 요청 |
| Report | GET | /api/v71/reports/{id} | 리포트 조회 |
| Report | GET | /api/v71/reports | 리포트 리스트 |
| Report | GET | /api/v71/reports/{id}/pdf | PDF 다운로드 |
| Report | GET | /api/v71/reports/{id}/excel | Excel 다운로드 |
| System | GET | /api/v71/system/status | 시스템 상태 |
| System | GET | /api/v71/system/health | 헬스 체크 |
| System | POST | /api/v71/system/safe_mode | 안전 모드 진입 |
| System | POST | /api/v71/system/resume | 안전 모드 해제 |
| System | GET | /api/v71/system/restarts | 재시작 이력 |
| Settings | GET | /api/v71/settings | 설정 조회 |
| Settings | PATCH | /api/v71/settings | 설정 변경 |
| WS | - | wss://.../api/v71/ws | WebSocket |

---

## 부록 B: 미정 사항

```yaml
B.1 OpenAPI 스키마:
  YAML/JSON 형식
  Swagger UI 통합
  자동 클라이언트 생성

B.2 Rate Limit 정확한 값:
  분당 요청 수
  엔드포인트별 차등

B.3 캐시 정책:
  ETag, Last-Modified
  종목 검색 결과 캐싱

B.4 GraphQL 검토:
  REST 충분?
  복잡 쿼리 시 GraphQL?

B.5 WebSocket 인증 갱신:
  연결 중 토큰 만료 처리
  재인증 메커니즘
```

---

*이 문서는 V7.1 API의 단일 진실 원천입니다.*  
*Claude Design UI 작업 + 프론트엔드 구현 시 기준.*

*최종 업데이트: 2026-04-25*
