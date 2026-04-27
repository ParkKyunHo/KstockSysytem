# V7.1 데이터 모델 (Data Model)

> 이 문서는 V7.1 시스템의 **Supabase (PostgreSQL) 스키마**를 정의합니다.
> 
> 모든 데이터 영속화는 이 스키마를 따라야 합니다.
> 
> 02_TRADING_RULES.md의 모든 거래 룰이 이 데이터 모델로 표현됩니다.

---

## 목차

- [§0. 설계 원칙](#0-설계-원칙)
- [§1. 스키마 개요](#1-스키마-개요)
- [§2. 핵심 거래 테이블](#2-핵심-거래-테이블)
  - 2.1 tracked_stocks
  - 2.2 support_boxes
  - 2.3 positions
  - 2.4 trade_events
- [§3. 이벤트 및 모니터링 테이블](#3-이벤트-및-모니터링-테이블)
  - 3.1 system_events
  - 3.2 system_restarts
  - 3.3 vi_events
  - 3.4 notifications
- [§4. 리포트 테이블](#4-리포트-테이블)
  - 4.1 daily_reports
  - 4.2 monthly_reviews
- [§5. 사용자 및 보안 테이블](#5-사용자-및-보안-테이블)
  - 5.1 users
  - 5.2 user_sessions
  - 5.3 audit_logs
  - 5.4 user_settings
- [§6. 마스터 데이터 테이블](#6-마스터-데이터-테이블)
  - 6.1 market_calendar
  - 6.2 stocks (마스터)
- [§7. 인덱스 및 제약](#7-인덱스-및-제약)
- [§8. 마이그레이션 전략](#8-마이그레이션-전략)
- [§9. 데이터 보존 정책](#9-데이터-보존-정책)

---

## §0. 설계 원칙

### 0.1 V7.1 데이터 모델 5원칙

```yaml
원칙 1: V7.0 호환 (충돌 금지)
  V7.0 기존 테이블 보존
  V7.1 신규 컬럼/테이블만 추가
  파괴적 변경 금지 (DROP COLUMN 등)

원칙 2: 이력 보존 (Audit Trail)
  거래 관련 데이터는 물리적 삭제 안 함
  status 필드로 논리적 삭제
  trade_events에 모든 변경 기록

원칙 3: 이중 경로 분리 (NFR3)
  같은 종목의 PATH_A와 PATH_B는 별도 레코드
  positions의 source 필드로 명확 구분
  MANUAL 포지션은 SYSTEM과 분리

원칙 4: 단일 진실 원천 (Single Source of Truth)
  계산 가능한 값은 저장 안 함 (예: 손익률)
  실시간 계산
  저장 데이터는 원시 사실만

원칙 5: 마이그레이션 안전 (Schema Migration Validator)
  모든 마이그레이션 UP/DOWN 양방향
  기본값으로 NULL 허용 (기존 데이터 호환)
  하네스 4 (Schema Migration Validator) 통과
```

### 0.2 명명 규칙

```yaml
테이블:
  스네이크 케이스 (snake_case)
  복수형 (positions, trade_events)
  V7.1 신규: 자연스러운 이름 (V71 접두사 불필요)
  단, 기존 V7.0 테이블 확장은 컬럼만 추가

컬럼:
  스네이크 케이스
  명확한 의미 (qty 보다 quantity)
  Boolean: is_, has_, can_ 접두사
  타임스탬프: _at 접미사 (created_at, updated_at)
  외래 키: 참조 테이블의 단수형 + _id (tracked_stock_id)

Enum:
  대문자 + 언더스코어 (TRACKING, BOX_SET)
  PostgreSQL ENUM 타입 또는 CHECK 제약
```

### 0.3 데이터 타입 표준

```yaml
ID:
  UUID (uuid_generate_v4())
  Primary Key 모두 UUID

타임스탬프:
  TIMESTAMPTZ (UTC 기준)
  애플리케이션에서 한국 시간 변환

가격:
  NUMERIC(12, 0) - 원 단위 정수
  주식은 1원 단위, 소수점 없음

수량:
  INTEGER - 주식 수량

비율 (%):
  NUMERIC(5, 2) - 예: 30.50
  10000.00까지 표현 가능

비율 (소수):
  NUMERIC(8, 6) - 예: 0.045000 (4.5%)
  손절폭 등에 사용

JSON 필드:
  JSONB (PostgreSQL 최적화)
  payload, metadata 등
```

---

## §1. 스키마 개요

### 1.1 테이블 분류

```
거래 핵심 (거래 룰 직접 표현):
├── tracked_stocks       # 추적 종목 (이중 경로 지원)
├── support_boxes        # 박스 (사용자 정의 매수 계획)
├── positions            # 보유 포지션 (SYSTEM_A/B/MANUAL)
└── trade_events         # 모든 거래 이벤트 (audit trail)

이벤트 및 모니터링:
├── system_events        # 시스템 레벨 이벤트
├── system_restarts      # 재시작 이력
├── vi_events           # VI 발동/해제 이력
└── notifications        # 알림 큐 + 이력

리포트:
├── daily_reports        # On-Demand 리포트 (Opus 4.7)
└── monthly_reviews      # 월 1회 리뷰 자동 생성

사용자 및 보안:
├── users                # 사용자 (1인 시스템이지만 확장성)
├── user_sessions        # 세션 (JWT, 2FA)
├── audit_logs           # 보안 감사 로그
└── user_settings        # 사용자 설정

마스터 데이터:
├── market_calendar      # 한국 시장 일정 (휴장일)
└── stocks               # 종목 마스터 (선택, 캐싱용)
```

### 1.2 관계도

```
users
  │
  └─[1:N]─ user_sessions
  └─[1:N]─ audit_logs
  └─[1:1]─ user_settings

tracked_stocks
  │
  └─[1:N]─ support_boxes
  └─[1:N]─ positions
  └─[1:N]─ daily_reports

support_boxes
  │
  └─[0:1]─ positions (TRIGGERED 시)

positions
  │
  └─[1:N]─ trade_events
  └─[N:1]─ tracked_stocks (NULLable - MANUAL 케이스)
  └─[N:1]─ support_boxes (NULLable - MANUAL 케이스)

vi_events
  └─[N:1]─ stocks (종목 코드 참조)

monthly_reviews
  └─ 통계성 (외래 키 없음)
```

### 1.3 PostgreSQL 확장 사용

```sql
-- 필수 확장
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";       -- UUID 생성
CREATE EXTENSION IF NOT EXISTS "pgcrypto";        -- 암호화 (보안)
CREATE EXTENSION IF NOT EXISTS "pg_trgm";         -- 종목명 검색
CREATE EXTENSION IF NOT EXISTS "btree_gist";      -- 박스 겹침 검증 (선택)
```

---

## §2. 핵심 거래 테이블

### 2.1 tracked_stocks (추적 종목)

> ⚠️ **PRD Patch #3 (2026-04-25)**: `path_type` 컴럼 제거.
> 경로는 박스의 속성 (`support_boxes.path_type`)으로 이동.
> 같은 종목의 이중 경로는 1개 tracked_stocks 레코드 + 다수 support_boxes로 처리.

```sql
-- 추적 상태 ENUM
CREATE TYPE tracked_status AS ENUM (
    'TRACKING',         -- 추적만, 박스 미설정
    'BOX_SET',          -- 박스 설정됨, 진입 대기
    'POSITION_OPEN',    -- 포지션 보유
    'POSITION_PARTIAL', -- 부분 익절 발생
    'EXITED'            -- 청산 완료 (자동 재진입 안 함)
);

-- 경로 ENUM (support_boxes에서 사용, ⚠️ tracked_stocks에서는 제거)
CREATE TYPE path_type AS ENUM (
    'PATH_A',  -- 주도주 단타 (3분봉)
    'PATH_B'   -- 수동 중기 (일봉)
);

CREATE TABLE tracked_stocks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 종목 정보
    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,
    market VARCHAR(20),  -- 'KOSPI', 'KOSDAQ', 'KONEX'
    
    -- ⚠️ path_type 제거 (PRD Patch #3)
    -- 경로는 support_boxes에서 관리
    
    -- 상태
    status tracked_status NOT NULL DEFAULT 'TRACKING',
    
    -- 메타데이터
    user_memo TEXT,
    source VARCHAR(50),  -- 어디서 발견했는지 (HTS, 시그널리포트 등)
    
    -- VI 관련 플래그
    vi_recovered_today BOOLEAN NOT NULL DEFAULT FALSE,
    vi_recovered_at TIMESTAMPTZ,
    
    -- 자동 이탈 정보
    auto_exit_reason VARCHAR(50),  -- BOX_DROP_20, TRADING_HALTED, DELISTING_RISK
    auto_exit_at TIMESTAMPTZ,
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_status_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 제약: 같은 종목 활성 추적은 1개만 (PRD Patch #3, path_type 없이)
    CONSTRAINT tracked_stocks_unique_active 
        EXCLUDE USING gist (stock_code WITH =) 
        WHERE (status != 'EXITED')
);

CREATE INDEX idx_tracked_stocks_code ON tracked_stocks(stock_code);
CREATE INDEX idx_tracked_stocks_status ON tracked_stocks(status);
CREATE INDEX idx_tracked_stocks_active ON tracked_stocks(stock_code) 
    WHERE status != 'EXITED';

-- 코멘트
COMMENT ON TABLE tracked_stocks IS '추적 종목 (종목당 1개, 경로는 support_boxes에 있음 - PRD Patch #3)';
COMMENT ON COLUMN tracked_stocks.vi_recovered_today IS 'VI 발동 후 당일 신규 진입 금지 플래그';
```

**제약 사항**:
```yaml
EXCLUDE USING gist (PRD Patch #3 적용):
  같은 종목 + 활성 상태 (EXITED 아님)인 레코드는 단 1개
  EXITED는 여러 개 허용 (이력 보존)
  
  예시:
    삼성전자 + TRACKING 1개  ← 가능
    삼성전자 + TRACKING 2개  ← 차단 (제약 위반)
    삼성전자 + EXITED 5개    ← 가능 (이력)
    
  → 동일 종목 이중 경로는 이제 support_boxes에서 처리
```

### 2.2 support_boxes (박스)

> ⚠️ **PRD Patch #3 (2026-04-25)**: `path_type` 컴럼 추가.
> 경로가 tracked_stocks에서 support_boxes로 이동.
> 같은 종목 안에서 박스마다 다른 경로 가능.

```sql
-- 박스 상태 ENUM
CREATE TYPE box_status AS ENUM (
    'WAITING',       -- 진입 대기
    'TRIGGERED',     -- 매수 실행됨
    'INVALIDATED',   -- 시나리오 C 또는 자동 이탈로 무효화
    'CANCELLED'      -- 사용자 삭제 또는 손절 후 자동 취소
);

-- 전략 유형 ENUM
CREATE TYPE strategy_type AS ENUM (
    'PULLBACK',  -- 눌림
    'BREAKOUT'   -- 돌파
);

CREATE TABLE support_boxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 추적 종목 연결
    tracked_stock_id UUID NOT NULL REFERENCES tracked_stocks(id) ON DELETE CASCADE,
    
    -- ★ 경로 (PRD Patch #3 신규)
    -- 박스마다 path_type 보유, 같은 종목에 다른 경로 박스 가능
    path_type path_type NOT NULL,
    
    -- 박스 정보
    box_tier INTEGER NOT NULL,  -- 1, 2, 3, ... (다층 박스 순서)
    upper_price NUMERIC(12, 0) NOT NULL,
    lower_price NUMERIC(12, 0) NOT NULL,
    
    -- 매수 계획
    position_size_pct NUMERIC(5, 2) NOT NULL,  -- 0.01 ~ 100.00
    stop_loss_pct NUMERIC(8, 6) NOT NULL DEFAULT -0.05,  -- 기본 -5%
    
    -- 전략
    strategy_type strategy_type NOT NULL,
    
    -- 상태
    status box_status NOT NULL DEFAULT 'WAITING',
    
    -- 메타데이터
    memo TEXT,
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    last_reminder_at TIMESTAMPTZ,  -- 30일 만료 알림 발송 시각
    
    -- 무효화 정보
    invalidation_reason VARCHAR(100),  -- MANUAL_BUY_DETECTED, AUTO_EXIT_BOX_DROP, USER_DELETED
    
    -- 제약: 박스 유효성
    CONSTRAINT box_price_valid CHECK (upper_price > lower_price),
    CONSTRAINT box_size_valid CHECK (position_size_pct > 0 AND position_size_pct <= 100),
    CONSTRAINT box_stop_loss_valid CHECK (stop_loss_pct < 0)
);

CREATE INDEX idx_boxes_tracked_stock ON support_boxes(tracked_stock_id);
CREATE INDEX idx_boxes_status ON support_boxes(status);
CREATE INDEX idx_boxes_path ON support_boxes(path_type);  -- ★ PRD Patch #3 신규
CREATE INDEX idx_boxes_active ON support_boxes(tracked_stock_id, path_type, status) 
    WHERE status = 'WAITING';
CREATE INDEX idx_boxes_pending_reminder ON support_boxes(created_at, last_reminder_at) 
    WHERE status = 'WAITING';

COMMENT ON TABLE support_boxes IS '사용자 정의 박스 (매수 계획) - 경로는 박스 속성 (PRD Patch #3)';
COMMENT ON COLUMN support_boxes.path_type IS '경로 A: 3분봉 단타, 경로 B: 일봉 중기 (박스마다 독립)';
COMMENT ON COLUMN support_boxes.box_tier IS '박스 층 (1차, 2차, ...). 다층 박스 시 진입 순서 자유';
COMMENT ON COLUMN support_boxes.position_size_pct IS '총 자본 대비 투입 비중 %';
COMMENT ON COLUMN support_boxes.stop_loss_pct IS '음수로 저장 (-0.05 = -5%)';
```

**박스 겹침 검증** (애플리케이션 레벨):
```python
# 같은 tracked_stock + WAITING 상태 박스끼리만 검증
def validate_no_overlap(tracked_stock_id: UUID, new_box: Box) -> bool:
    existing_boxes = query_active_boxes(tracked_stock_id)
    for box in existing_boxes:
        # 겹침 조건: A.upper > B.lower AND A.lower < B.upper
        if (new_box.upper_price > box.lower_price and 
            new_box.lower_price < box.upper_price):
            return False  # 겹침 발견
    return True  # 겹침 없음
```

### 2.3 positions (보유 포지션)

```sql
-- 포지션 출처 ENUM
CREATE TYPE position_source AS ENUM (
    'SYSTEM_A',  -- 경로 A 자동 매수
    'SYSTEM_B',  -- 경로 B 자동 매수
    'MANUAL'     -- 사용자 수동 매수
);

-- 포지션 상태 ENUM
CREATE TYPE position_status AS ENUM (
    'OPEN',            -- 활성, 부분 익절 미발생
    'PARTIAL_CLOSED',  -- 부분 익절 발생
    'CLOSED'           -- 전량 청산 (이력 보존)
);

CREATE TABLE positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 출처
    source position_source NOT NULL,
    
    -- 종목 정보
    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,
    
    -- 추적 연결 (NULL 가능, MANUAL의 경우)
    tracked_stock_id UUID REFERENCES tracked_stocks(id),
    
    -- 박스 연결 (NULL 가능, MANUAL의 경우)
    triggered_box_id UUID REFERENCES support_boxes(id),
    
    -- 평단가 및 수량
    initial_avg_price NUMERIC(12, 0) NOT NULL,    -- 첫 매수 시 평단가 (변경 없음)
    weighted_avg_price NUMERIC(12, 0) NOT NULL,   -- 가중 평균 (추가 매수 시 재계산)
    total_quantity INTEGER NOT NULL,
    
    -- 손절선 (단계별 상향)
    fixed_stop_price NUMERIC(12, 0) NOT NULL,
    
    -- 이벤트 플래그
    profit_5_executed BOOLEAN NOT NULL DEFAULT FALSE,
    profit_10_executed BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- TS (Trailing Stop)
    ts_activated BOOLEAN NOT NULL DEFAULT FALSE,
    ts_base_price NUMERIC(12, 0),  -- 매수 후 최고가 추적
    ts_stop_price NUMERIC(12, 0),  -- 현재 TS 청산선
    ts_active_multiplier NUMERIC(3, 1),  -- 현재 ATR 배수 (4.0, 3.0, 2.5, 2.0)
    
    -- 상태
    status position_status NOT NULL DEFAULT 'OPEN',
    
    -- 비중 한도 추적
    actual_capital_invested NUMERIC(15, 0) NOT NULL,  -- 실제 투입 자본
    
    -- 실시간 가격 (★ PRD Patch #5, V7.1.0d, 2026-04-27)
    current_price NUMERIC(12, 0),                 -- WebSocket 0B / kt00018 / ka10001 갱신
    current_price_at TIMESTAMPTZ,                 -- 마지막 갱신 시각
    pnl_amount NUMERIC(15, 0),                    -- (current_price - weighted_avg_price) × total_quantity
    pnl_pct NUMERIC(8, 6),                        -- (current_price / weighted_avg_price - 1)
    
    -- 청산 정보 (CLOSED 시)
    closed_at TIMESTAMPTZ,
    final_pnl NUMERIC(15, 0),
    final_pnl_pct NUMERIC(8, 4),
    close_reason VARCHAR(50),  -- STOP_LOSS, TS_EXIT, MANUAL_FULL_EXIT, AUTO_EXIT
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 제약
    CONSTRAINT position_qty_valid CHECK (total_quantity >= 0),
    CONSTRAINT position_avg_valid CHECK (weighted_avg_price > 0),
    CONSTRAINT position_closed_consistency CHECK (
        (status = 'CLOSED' AND total_quantity = 0) OR
        (status != 'CLOSED' AND total_quantity > 0)
    )
);

CREATE INDEX idx_positions_stock ON positions(stock_code);
CREATE INDEX idx_positions_status ON positions(status);
CREATE INDEX idx_positions_source ON positions(source);
CREATE INDEX idx_positions_tracked ON positions(tracked_stock_id) 
    WHERE tracked_stock_id IS NOT NULL;
CREATE INDEX idx_positions_active ON positions(stock_code, status) 
    WHERE status != 'CLOSED';

COMMENT ON TABLE positions IS '보유 포지션 (시스템 + 수동 통합 관리)';
COMMENT ON COLUMN positions.weighted_avg_price IS '추가 매수 시 가중 평균 재계산. 매도 시 변경 없음';
COMMENT ON COLUMN positions.ts_base_price IS '매수 후 최고가 (실시간 갱신)';
COMMENT ON COLUMN positions.actual_capital_invested IS '한도 계산용 실제 투입 자본';
COMMENT ON COLUMN positions.current_price IS 'PRD Patch #5: 실시간 시세. WebSocket 0B(<1s) > kt00018(5s) > ka10001(재시작)';
COMMENT ON COLUMN positions.pnl_amount IS 'PRD Patch #5: 평가 손익 (current_price 기반)';
```

**핵심 비즈니스 룰**:
```yaml
평단가 (§6):
  매수 시: weighted_avg_price 재계산 + 이벤트 리셋
  매도 시: weighted_avg_price 유지

이벤트 리셋 (추가 매수 시):
  profit_5_executed = FALSE
  profit_10_executed = FALSE
  fixed_stop_price = new_avg × 0.95 (단계 1 복귀)
  ts_base_price 유지

소스 분리 (NFR3):
  SYSTEM_A/B/MANUAL 각각 별도 레코드
  같은 종목이라도 source 다르면 다른 포지션

실시간 가격 갱신 (★ PRD Patch #5):
  1순위: WebSocket 0B 채널 (실시간, < 1초, NFR1 보장)
  2순위: kt00018 계좌평가잔고 (5초 폴링, WebSocket 끊김 시)
  3순위: ka10001 주식기본정보 (재시작 직후 단발)
  pnl_amount/pnl_pct는 갱신 트리거에서 함께 계산
```

### 2.4 v71_orders (주문 이력) — ★ PRD Patch #5 신규 (V7.1.0d, 2026-04-27)

> **명명 결정**: V7.0의 `src.database.models.Order` (orders 테이블)와 같은
> Base metadata를 공유하기 때문에 V7.1 테이블은 `v71_orders` + Python 클래스
> `V71Order`로 격리. PRD §1.4 V71 접두사 (충돌 시) + 헌법 §3 충돌 금지 정합.
> V7.0 정리 완료 후 단순 `orders/Order`로 통합 검토 가능 (PRD §3.2 P1.X 이후).

```sql
-- 주문 방향 ENUM
CREATE TYPE order_direction AS ENUM (
    'BUY',
    'SELL'
);

-- 주문 상태 ENUM
CREATE TYPE order_state AS ENUM (
    'SUBMITTED',  -- 키움 접수 완료, 체결 대기
    'PARTIAL',    -- 부분 체결
    'FILLED',     -- 전량 체결
    'CANCELLED',  -- 취소됨
    'REJECTED'    -- 키움 거부
);

-- 매매 구분 ENUM (키움 trde_tp 매핑)
CREATE TYPE order_trade_type AS ENUM (
    'LIMIT',           -- 0: 지정가
    'MARKET',          -- 3: 시장가
    'CONDITIONAL',     -- 5: 조건부지정가
    'AFTER_HOURS',     -- 81: 시간외종가
    'BEST_LIMIT',      -- 6: 최유리지정가
    'PRIORITY_LIMIT'   -- 7: 최우선지정가
);

CREATE TABLE v71_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- 키움 매핑 (★ V7.1 자체 매핑 키)
    kiwoom_order_no VARCHAR(20) NOT NULL UNIQUE,    -- 키움 ord_no (응답 시 발급)
    kiwoom_orig_order_no VARCHAR(20),                -- 정정/취소 시 원주문번호

    -- 연결 (NULL 가능 -- 시점별 다름)
    position_id UUID REFERENCES positions(id),
    box_id UUID REFERENCES support_boxes(id),
    tracked_stock_id UUID REFERENCES tracked_stocks(id),

    -- 주문 내용
    stock_code VARCHAR(10) NOT NULL,
    direction order_direction NOT NULL,
    trade_type order_trade_type NOT NULL,
    quantity INTEGER NOT NULL,
    price NUMERIC(12, 0),                            -- NULL이면 시장가
    exchange VARCHAR(10) NOT NULL DEFAULT 'KRX',     -- V7.1은 KRX 전용

    -- 상태
    state order_state NOT NULL DEFAULT 'SUBMITTED',
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    filled_avg_price NUMERIC(12, 2),

    -- 거부/취소 사유
    reject_reason TEXT,
    cancel_reason VARCHAR(100),

    -- 재시도 (PRD §3.3 5초 × 3회)
    retry_attempt INTEGER NOT NULL DEFAULT 1,

    -- 타임스탬프
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,

    -- 키움 raw 페이로드 (감사용)
    kiwoom_raw_request JSONB,
    kiwoom_raw_response JSONB,

    -- 제약
    CONSTRAINT order_qty_positive CHECK (quantity > 0),
    CONSTRAINT order_filled_consistency CHECK (filled_quantity <= quantity),
    CONSTRAINT order_price_required CHECK (
        (trade_type = 'MARKET' AND price IS NULL) OR
        (trade_type != 'MARKET' AND price IS NOT NULL AND price > 0)
    )
);

CREATE UNIQUE INDEX idx_v71_orders_kiwoom_no ON v71_orders(kiwoom_order_no);
CREATE INDEX idx_v71_orders_position ON v71_orders(position_id) WHERE position_id IS NOT NULL;
CREATE INDEX idx_v71_orders_box ON v71_orders(box_id) WHERE box_id IS NOT NULL;
CREATE INDEX idx_v71_orders_stock ON v71_orders(stock_code, submitted_at DESC);
CREATE INDEX idx_v71_orders_state_pending ON v71_orders(state) WHERE state IN ('SUBMITTED', 'PARTIAL');

COMMENT ON TABLE v71_orders IS 'PRD Patch #5: V7.1 키움 주문 추적. 키움 API에 client_order_id 필드 없음 → 자체 매핑 필수. V7.0 orders와 격리 (PRD §1.4 V71 접두사)';
COMMENT ON COLUMN v71_orders.kiwoom_order_no IS 'PRD Patch #5: 키움 ord_no UNIQUE. 모든 후속 추적의 키';
COMMENT ON COLUMN v71_orders.kiwoom_orig_order_no IS 'PRD Patch #5: 정정/취소 주문 시 원주문 추적';
COMMENT ON COLUMN v71_orders.kiwoom_raw_request IS 'PRD Patch #5: 키움 요청 원문 보존 (감사 + 디버깅)';
```

**핵심 비즈니스 룰**:
```yaml
주문 생명 주기:
  SUBMITTED → PARTIAL → FILLED  (정상)
  SUBMITTED → CANCELLED          (취소)
  SUBMITTED → REJECTED           (키움 거부)

발주 흐름 (OrderManager 표준):
  1. 키움 API 호출 (kt10000 매수 / kt10001 매도)
  2. 응답에서 ord_no 받자마자 INSERT (kiwoom_order_no UNIQUE)
  3. WebSocket 00 (주문체결) 이벤트로 state 갱신
  4. 5초 × 3회 재시도 (PRD §3.3, retry_attempt 증가)

정정/취소 (kt10002/kt10003):
  새 row INSERT (kiwoom_orig_order_no = 원주문 ord_no)
  원주문은 CANCELLED 또는 부분 체결 후 잔량 취소

재시작 복구 (Reconciler):
  ka10075 미체결 조회 → orders 테이블 IN ('SUBMITTED', 'PARTIAL') 비교
  Case A~E 처리 (PRD §13)

UI 사용:
  GET /api/v71/orders — 미체결만 idx_orders_state_pending 활용
  GET /api/v71/orders/{id} — kiwoom_raw_* 포함 (감사)
```

### 2.5 trade_events (거래 이벤트)

```sql
-- 이벤트 타입 ENUM
CREATE TYPE trade_event_type AS ENUM (
    -- 매수
    'BUY_EXECUTED',          -- 시스템 매수 체결
    'PYRAMID_BUY',           -- 다층 박스 추가 매수
    'MANUAL_BUY',            -- 수동 매수 감지
    'MANUAL_PYRAMID_BUY',    -- 수동 추가 매수 (시나리오 A)
    
    -- 매도
    'PROFIT_TAKE_5',         -- +5% 부분 익절
    'PROFIT_TAKE_10',        -- +10% 부분 익절
    'STOP_LOSS',             -- 손절 (-5% / -2% / +4%)
    'TS_EXIT',               -- 트레일링 스탑 청산
    'MANUAL_PARTIAL_EXIT',   -- 수동 부분 매도 (시나리오 B)
    'MANUAL_FULL_EXIT',      -- 수동 전량 매도
    'AUTO_EXIT',             -- 자동 이탈 (-20%, 거래정지 등)
    
    -- 주문
    'ORDER_SENT',            -- 주문 발송
    'ORDER_FILLED',          -- 주문 체결
    'ORDER_PARTIAL_FILLED',  -- 부분 체결
    'ORDER_CANCELLED',       -- 주문 취소
    'ORDER_FAILED',          -- 주문 실패
    
    -- 시스템 이벤트
    'POSITION_RECONCILED',   -- 정합성 확인 후 변경
    'EVENT_RESET',           -- 이벤트 리셋 (추가 매수 시)
    'STOP_UPDATED',          -- 손절선 갱신
    'TS_ACTIVATED',          -- TS 활성화
    'TS_VALIDATED'           -- TS 청산선 유효화
);

CREATE TABLE trade_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 연결
    position_id UUID REFERENCES positions(id),
    tracked_stock_id UUID REFERENCES tracked_stocks(id),
    box_id UUID REFERENCES support_boxes(id),
    
    -- 이벤트
    event_type trade_event_type NOT NULL,
    
    -- 거래 정보
    stock_code VARCHAR(10) NOT NULL,
    price NUMERIC(12, 0),
    quantity INTEGER,
    
    -- 주문 추적
    order_id VARCHAR(50),         -- 키움 API 주문 ID
    client_order_id VARCHAR(50),  -- 시스템 자체 주문 ID
    attempt INTEGER,              -- 재시도 횟수
    
    -- 손익 (전량/부분 청산 시)
    pnl_amount NUMERIC(15, 0),
    pnl_pct NUMERIC(8, 4),
    
    -- 평단가 변동 (추가 매수 시)
    avg_price_before NUMERIC(12, 0),
    avg_price_after NUMERIC(12, 0),
    
    -- 메타데이터 (JSONB로 유연한 저장)
    payload JSONB,
    
    -- 사유 / 에러
    reason VARCHAR(200),
    error_message TEXT,
    
    -- 타임스탬프
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_events_position ON trade_events(position_id);
CREATE INDEX idx_events_tracked_stock ON trade_events(tracked_stock_id);
CREATE INDEX idx_events_type ON trade_events(event_type);
CREATE INDEX idx_events_occurred ON trade_events(occurred_at DESC);
CREATE INDEX idx_events_stock_time ON trade_events(stock_code, occurred_at DESC);

COMMENT ON TABLE trade_events IS '모든 거래 이벤트 (audit trail)';
COMMENT ON COLUMN trade_events.payload IS '이벤트별 추가 정보 JSONB';
```

**payload 예시**:
```json
// PROFIT_TAKE_5
{
  "ts_activated": true,
  "ts_base_price": 18900,
  "remaining_qty": 70,
  "position_status_after": "PARTIAL_CLOSED"
}

// MANUAL_PYRAMID_BUY (시나리오 A)
{
  "scenario": "A",
  "before": {
    "qty": 100,
    "avg_price": 180000,
    "profit_5_executed": true
  },
  "after": {
    "qty": 150,
    "avg_price": 181667,
    "profit_5_executed": false
  },
  "events_reset": true
}

// AUTO_EXIT
{
  "exit_reason": "BOX_DROP_20",
  "current_price": 14200,
  "lowest_box_lower": 17000,
  "drop_pct": -16.47,
  "boxes_invalidated": 3
}

// ORDER_FAILED
{
  "order_type": "MARKET",
  "attempt": 4,
  "error_code": "INSUFFICIENT_BALANCE",
  "kiwoom_response": {...}
}
```

---

## §3. 이벤트 및 모니터링 테이블

### 3.1 system_events (시스템 이벤트)

```sql
-- 시스템 이벤트 타입
CREATE TYPE system_event_type AS ENUM (
    'STARTUP',                  -- 시스템 시작
    'SHUTDOWN',                 -- 시스템 종료
    'WEBSOCKET_CONNECTED',      -- WebSocket 연결
    'WEBSOCKET_DISCONNECTED',   -- WebSocket 끊김
    'WEBSOCKET_RECONNECTED',    -- WebSocket 재연결 성공
    'API_AUTH_REFRESHED',       -- 키움 OAuth 토큰 갱신
    'API_ERROR',                -- 키움 API 에러
    'DB_CONNECTION_LOST',       -- DB 연결 끊김
    'TELEGRAM_API_FAILED',      -- 텔레그램 API 실패
    'CIRCUIT_BREAKER_OPEN',     -- 알림 Circuit Breaker
    'CIRCUIT_BREAKER_CLOSED',
    'HEALTH_CHECK',             -- 정기 헬스 체크
    'CONFIG_CHANGED',           -- 설정 변경
    'FEATURE_FLAG_CHANGED'      -- Feature Flag 변경
);

CREATE TABLE system_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type system_event_type NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'INFO',  -- INFO, WARNING, ERROR, CRITICAL
    
    -- 메시지
    message TEXT NOT NULL,
    component VARCHAR(50),  -- 발생 모듈 (api.websocket, core.box_manager 등)
    
    -- 메타데이터
    payload JSONB,
    
    -- 타임스탬프
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sys_events_type ON system_events(event_type);
CREATE INDEX idx_sys_events_severity ON system_events(severity);
CREATE INDEX idx_sys_events_time ON system_events(occurred_at DESC);

COMMENT ON TABLE system_events IS '시스템 레벨 이벤트 로그';
```

### 3.2 system_restarts (재시작 이력)

```sql
-- 재시작 사유 ENUM
CREATE TYPE restart_reason AS ENUM (
    'KNOWN_DEPLOY',  -- 계획된 배포
    'MANUAL',        -- 수동 재시작
    'CRASH',         -- 비정상 종료
    'OOM',           -- 메모리 부족
    'AUTO_RECOVERY', -- 자동 복구
    'UNKNOWN'        -- 사유 불명
);

CREATE TABLE system_restarts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 재시작 정보
    restart_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recovery_started_at TIMESTAMPTZ,
    recovery_completed_at TIMESTAMPTZ,
    recovery_duration_seconds INTEGER,
    
    -- 사유
    reason restart_reason NOT NULL DEFAULT 'UNKNOWN',
    reason_detail TEXT,
    
    -- 정합성 확인 결과
    reconciliation_summary JSONB,
    -- 예: { "case_a": 5, "case_b": 1, "case_c": 0, "case_d": 0, "case_e": 0 }
    
    -- 미완료 주문 처리
    cancelled_orders_count INTEGER DEFAULT 0,
    
    -- 시세 재구독 결과
    resubscribed_stocks_count INTEGER DEFAULT 0,
    
    -- 안전 모드 해제 여부
    safe_mode_released BOOLEAN NOT NULL DEFAULT FALSE,
    
    -- 알림 발송 여부
    notification_sent BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX idx_restarts_time ON system_restarts(restart_at DESC);

COMMENT ON TABLE system_restarts IS '시스템 재시작 이력 (빈도 모니터링)';
```

**재시작 빈도 검사 쿼리**:
```sql
-- 최근 1시간 내 재시작 횟수
SELECT COUNT(*) 
FROM system_restarts 
WHERE restart_at >= NOW() - INTERVAL '1 hour';

-- 결과:
--   1: 정상
--   2: 경고 알림
--   3: CRITICAL 알림
--   5+: ERROR + 반복 CRITICAL
```

### 3.3 vi_events (VI 이력)

```sql
-- VI 상태 ENUM
CREATE TYPE vi_state AS ENUM (
    'TRIGGERED',  -- VI 발동
    'RESUMED'     -- VI 해제
);

CREATE TABLE vi_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 종목 정보
    stock_code VARCHAR(10) NOT NULL,
    
    -- VI 정보
    state vi_state NOT NULL,
    trigger_price NUMERIC(12, 0),  -- VI 발동 가격
    resume_at TIMESTAMPTZ,         -- VI 해제 예정 시각
    
    -- 처리 결과
    handled BOOLEAN NOT NULL DEFAULT FALSE,
    actions_taken JSONB,  -- 시스템이 취한 조치
    
    -- 타임스탬프
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_vi_stock ON vi_events(stock_code);
CREATE INDEX idx_vi_time ON vi_events(occurred_at DESC);
CREATE INDEX idx_vi_unhandled ON vi_events(handled, occurred_at) WHERE handled = FALSE;

COMMENT ON TABLE vi_events IS 'VI 발동/해제 이력';
```

**actions_taken 예시**:
```json
{
  "single_price_attempted": true,
  "single_price_filled": false,
  "post_resume_gap_pct": 4.5,
  "buy_abandoned": true,
  "abandoned_reason": "GAP_OVER_3PCT"
}
```

### 3.4 notifications (알림)

```sql
-- 알림 등급 ENUM
CREATE TYPE notification_severity AS ENUM (
    'CRITICAL',
    'HIGH',
    'MEDIUM',
    'LOW'
);

-- 알림 채널 ENUM
CREATE TYPE notification_channel AS ENUM (
    'TELEGRAM',
    'WEB',
    'BOTH'
);

-- 알림 상태 ENUM
CREATE TYPE notification_status AS ENUM (
    'PENDING',     -- 큐 대기
    'SENT',        -- 발송 완료
    'FAILED',      -- 발송 실패
    'SUPPRESSED',  -- 빈도 제한으로 억제
    'EXPIRED'      -- 만료 (MEDIUM/LOW만)
);

CREATE TABLE notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 알림 메타
    severity notification_severity NOT NULL,
    channel notification_channel NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    
    -- 종목 정보 (이벤트 관련 시)
    stock_code VARCHAR(10),
    
    -- 메시지
    title VARCHAR(200),
    message TEXT NOT NULL,
    payload JSONB,
    
    -- 상태
    status notification_status NOT NULL DEFAULT 'PENDING',
    
    -- 발송 추적
    sent_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    failure_reason VARCHAR(200),
    retry_count INTEGER NOT NULL DEFAULT 0,
    
    -- 빈도 제한
    rate_limit_key VARCHAR(100),  -- event_type + stock_code 조합
    
    -- 우선순위 (큐 정렬용)
    priority INTEGER NOT NULL,  -- CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ  -- MEDIUM/LOW의 경우 5분 후 만료
);

CREATE INDEX idx_notif_status ON notifications(status, priority, created_at);
CREATE INDEX idx_notif_pending ON notifications(priority, created_at) 
    WHERE status = 'PENDING';
CREATE INDEX idx_notif_rate_limit ON notifications(rate_limit_key, created_at) 
    WHERE rate_limit_key IS NOT NULL;
CREATE INDEX idx_notif_stock ON notifications(stock_code, created_at DESC);

COMMENT ON TABLE notifications IS '알림 큐 + 발송 이력';
```

**우선순위 큐 사용**:
```sql
-- 발송할 다음 알림 가져오기
SELECT * FROM notifications 
WHERE status = 'PENDING' 
ORDER BY priority ASC, created_at ASC 
LIMIT 1 
FOR UPDATE SKIP LOCKED;  -- 동시성 제어
```

---

## §4. 리포트 테이블

### 4.1 daily_reports (On-Demand 리포트)

```sql
-- 리포트 상태 ENUM
CREATE TYPE report_status AS ENUM (
    'PENDING',       -- 생성 요청 대기
    'GENERATING',    -- AI 생성 중
    'COMPLETED',     -- 생성 완료
    'FAILED'         -- 실패
);

CREATE TABLE daily_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 종목 정보
    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,
    
    -- 추적 연결 (선택)
    tracked_stock_id UUID REFERENCES tracked_stocks(id),
    
    -- 요청 정보
    requested_by UUID REFERENCES users(id),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 생성 정보
    generation_started_at TIMESTAMPTZ,
    generation_completed_at TIMESTAMPTZ,
    generation_duration_seconds INTEGER,
    
    -- AI 모델 정보
    model_version VARCHAR(50) NOT NULL DEFAULT 'claude-opus-4-7',
    prompt_tokens INTEGER,
    completion_tokens INTEGER,
    
    -- 상태
    status report_status NOT NULL DEFAULT 'PENDING',
    
    -- 리포트 내용
    -- PART 1: 이야기 (서사)
    narrative_part TEXT,
    
    -- PART 2: 객관 팩트
    facts_part TEXT,
    
    -- 데이터 소스
    data_sources JSONB,
    -- 예: { "kiwoom": [...], "dart": [...], "naver_news": [...] }
    
    -- 다운로드 링크
    pdf_path VARCHAR(500),
    excel_path VARCHAR(500),
    
    -- 사용자 메모 (생성 후 추가 가능)
    user_notes TEXT,
    
    -- 에러
    error_message TEXT,

    -- 소프트 삭제 (★ PRD Patch #5, V7.1.0d, 2026-04-27)
    is_hidden BOOLEAN NOT NULL DEFAULT FALSE,
    hidden_at TIMESTAMPTZ,
    hidden_reason VARCHAR(50),

    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_reports_stock ON daily_reports(stock_code);
CREATE INDEX idx_reports_status ON daily_reports(status);
CREATE INDEX idx_reports_user ON daily_reports(requested_by);
CREATE INDEX idx_reports_time ON daily_reports(requested_at DESC);
-- ★ PRD Patch #5: 정상(숨기지 않은) 리포트만 빠르게 조회
CREATE INDEX idx_reports_visible ON daily_reports(created_at DESC)
    WHERE is_hidden = FALSE;

COMMENT ON TABLE daily_reports IS 'On-Demand 종목 리포트 (Claude Opus 4.7). PRD Patch #5: 영구 보존, soft delete (is_hidden)';
COMMENT ON COLUMN daily_reports.narrative_part IS 'PART 1: 종목의 이야기 (출발→성장→현재→미래)';
COMMENT ON COLUMN daily_reports.facts_part IS 'PART 2: 객관 팩트 (사업/공급망/재무/공시 등)';
COMMENT ON COLUMN daily_reports.is_hidden IS 'PRD Patch #5: 소프트 삭제 플래그. DELETE 호출 시 true로 설정 (영구 보존, 목록에서만 숨김)';
COMMENT ON COLUMN daily_reports.hidden_reason IS 'PRD Patch #5: 숨김 사유 (USER_REQUEST / DUPLICATE / OUTDATED 등)';
```

**소프트 삭제 흐름 (PRD Patch #5)**:
```yaml
DELETE /api/v71/reports/{id}:
  UPDATE daily_reports
    SET is_hidden = TRUE,
        hidden_at = NOW(),
        hidden_reason = 'USER_REQUEST'
    WHERE id = $1;
  → HTTP 204 No Content

POST /api/v71/reports/{id}/restore:
  UPDATE daily_reports
    SET is_hidden = FALSE,
        hidden_at = NULL,
        hidden_reason = NULL
    WHERE id = $1;
  → HTTP 200 OK + 갱신된 리소스

GET /api/v71/reports?include_hidden=false (기본):
  WHERE is_hidden = FALSE  → idx_reports_visible 활용

GET /api/v71/reports?include_hidden=true:
  is_hidden 조건 없음 (전체)
```

**data_sources 예시**:
```json
{
  "kiwoom": {
    "current_price": 18000,
    "fetched_at": "2026-04-25T14:30:00Z",
    "1y_high": 22000,
    "1y_low": 14500
  },
  "dart": [
    {
      "filing_id": "20260201000123",
      "filing_type": "분기보고서",
      "filed_at": "2026-02-01"
    }
  ],
  "naver_news": [
    {
      "title": "...",
      "url": "...",
      "published_at": "..."
    }
  ]
}
```

### 4.2 monthly_reviews (월 1회 리뷰)

```sql
CREATE TABLE monthly_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 리뷰 기간
    review_month DATE NOT NULL,  -- 2026-04-01 같은 월 첫째날
    
    -- 통계 (전체 현황)
    tracked_count INTEGER NOT NULL DEFAULT 0,
    box_set_count INTEGER NOT NULL DEFAULT 0,
    position_open_count INTEGER NOT NULL DEFAULT 0,
    position_partial_count INTEGER NOT NULL DEFAULT 0,
    
    -- 주의 필요
    box_drop_alerts JSONB,           -- 박스 하단 큰 이탈 종목들
    long_stagnant_alerts JSONB,      -- 장기 정체 (60일+)
    expiring_boxes JSONB,            -- 30일 만료 임박
    
    -- 손익 통계
    total_pnl_amount NUMERIC(15, 0),
    total_pnl_pct NUMERIC(8, 4),
    win_count INTEGER,
    loss_count INTEGER,
    
    -- 전체 종목 목록 (JSONB)
    full_stock_list JSONB,
    
    -- 발송 추적
    sent_at TIMESTAMPTZ,
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 한 달에 1개만
    CONSTRAINT monthly_reviews_unique UNIQUE (review_month)
);

CREATE INDEX idx_monthly_reviews_month ON monthly_reviews(review_month DESC);

COMMENT ON TABLE monthly_reviews IS '매월 1일 자동 생성되는 추적 리뷰';
```

---

## §5. 사용자 및 보안 테이블

### 5.1 users (사용자)

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    
    -- 인증
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,  -- bcrypt
    
    -- 2FA (Google Authenticator)
    totp_secret VARCHAR(100),
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    backup_codes JSONB,  -- 백업 코드 (해시)
    
    -- 텔레그램
    telegram_chat_id VARCHAR(50) UNIQUE,
    telegram_username VARCHAR(50),
    
    -- 권한 (1인 시스템이지만 확장성)
    role VARCHAR(20) NOT NULL DEFAULT 'OWNER',  -- OWNER (확장: ADMIN, VIEWER)
    
    -- 활성화
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- 마지막 로그인
    last_login_at TIMESTAMPTZ,
    last_login_ip INET,
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_username ON users(username);
CREATE INDEX idx_users_telegram ON users(telegram_chat_id);

COMMENT ON TABLE users IS '사용자 (1인 시스템이지만 확장 고려)';
```

### 5.2 user_sessions (세션)

```sql
CREATE TABLE user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    
    -- 토큰 (해시 저장)
    access_token_hash VARCHAR(255) NOT NULL,
    refresh_token_hash VARCHAR(255) NOT NULL,
    
    -- 세션 정보
    ip_address INET,
    user_agent TEXT,
    
    -- 만료
    access_expires_at TIMESTAMPTZ NOT NULL,    -- 1시간
    refresh_expires_at TIMESTAMPTZ NOT NULL,   -- 24시간
    
    -- 비활성 자동 로그아웃 (30분)
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 폐기
    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sessions_user ON user_sessions(user_id);
CREATE INDEX idx_sessions_active ON user_sessions(user_id, revoked) 
    WHERE revoked = FALSE;
CREATE INDEX idx_sessions_expired ON user_sessions(refresh_expires_at);

COMMENT ON TABLE user_sessions IS 'JWT 세션 (1h access + 24h refresh)';
```

### 5.3 audit_logs (감사 로그)

```sql
-- 감사 액션 ENUM
CREATE TYPE audit_action AS ENUM (
    'LOGIN',
    'LOGIN_FAILED',
    'LOGOUT',
    'PASSWORD_CHANGED',
    'TOTP_ENABLED',
    'TOTP_DISABLED',
    'NEW_IP_DETECTED',
    'BOX_CREATED',
    'BOX_MODIFIED',
    'BOX_DELETED',
    'TRACKING_REGISTERED',
    'TRACKING_REMOVED',
    'SETTINGS_CHANGED',
    'REPORT_REQUESTED',
    'API_KEY_ROTATED'
);

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),
    
    -- 액션
    action audit_action NOT NULL,
    
    -- 컨텍스트
    target_type VARCHAR(50),  -- 'tracked_stock', 'support_box' 등
    target_id UUID,
    
    -- 변경 내용
    before_state JSONB,
    after_state JSONB,
    
    -- 환경
    ip_address INET,
    user_agent TEXT,
    
    -- 결과
    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,
    
    -- 타임스탬프
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_user ON audit_logs(user_id);
CREATE INDEX idx_audit_action ON audit_logs(action);
CREATE INDEX idx_audit_time ON audit_logs(occurred_at DESC);
CREATE INDEX idx_audit_target ON audit_logs(target_type, target_id);

COMMENT ON TABLE audit_logs IS '보안 감사 로그 (모든 사용자 액션)';
```

### 5.4 user_settings (사용자 설정)

```sql
CREATE TABLE user_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    
    -- 자본 정보
    total_capital NUMERIC(15, 0),  -- 총 자본 (한도 계산용)
    
    -- 알림 설정
    notify_critical BOOLEAN NOT NULL DEFAULT TRUE,    -- 강제 ON
    notify_high BOOLEAN NOT NULL DEFAULT TRUE,
    notify_medium BOOLEAN NOT NULL DEFAULT TRUE,
    notify_low BOOLEAN NOT NULL DEFAULT TRUE,
    
    -- 알림 시간 제한
    quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    quiet_hours_start TIME,
    quiet_hours_end TIME,
    
    -- UI 설정
    theme VARCHAR(20) NOT NULL DEFAULT 'dark',
    language VARCHAR(5) NOT NULL DEFAULT 'ko',
    
    -- 추가 설정 (JSONB로 유연성)
    preferences JSONB DEFAULT '{}'::jsonb,
    
    -- 타임스탬프
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE user_settings IS '사용자 설정 (1:1 관계)';
COMMENT ON COLUMN user_settings.notify_critical IS '강제 ON (변경 불가, 안전장치)';
```

**제약 (애플리케이션 레벨)**:
```python
# notify_critical은 항상 TRUE
# UPDATE 시 검증
def update_user_settings(user_id, settings):
    if 'notify_critical' in settings and settings['notify_critical'] == False:
        raise ValueError("CRITICAL 알림은 OFF할 수 없습니다 (안전장치)")
```

---

## §6. 마스터 데이터 테이블

### 6.1 market_calendar (장 일정)

```sql
-- 장 상태 ENUM
CREATE TYPE market_day_type AS ENUM (
    'TRADING',          -- 정상 거래일
    'HOLIDAY',          -- 공휴일
    'HALF_DAY',         -- 단축 거래 (연말 등)
    'EMERGENCY_CLOSED'  -- 임시 휴장
);

CREATE TABLE market_calendar (
    trading_date DATE PRIMARY KEY,
    day_type market_day_type NOT NULL,
    
    -- 거래 시간
    market_open_time TIME,    -- 09:00
    market_close_time TIME,   -- 15:30 (정상) / 13:00 (반장)
    
    -- 메모
    note VARCHAR(200),
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_calendar_type ON market_calendar(day_type);

COMMENT ON TABLE market_calendar IS '한국 시장 일정 (수동 또는 외부 데이터로 관리)';
```

**초기 데이터 예시**:
```sql
INSERT INTO market_calendar (trading_date, day_type, market_open_time, market_close_time, note)
VALUES
    ('2026-01-01', 'HOLIDAY', NULL, NULL, '신정'),
    ('2026-01-02', 'TRADING', '09:00', '15:30', NULL),
    ('2026-02-09', 'HOLIDAY', NULL, NULL, '설 연휴'),
    ('2026-12-30', 'HALF_DAY', '09:00', '13:00', '연말 단축거래');
```

### 6.2 stocks (종목 마스터, 선택)

```sql
CREATE TABLE stocks (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    market VARCHAR(20),  -- KOSPI, KOSDAQ, KONEX
    sector VARCHAR(100),
    industry VARCHAR(100),
    
    -- 상태
    is_listed BOOLEAN NOT NULL DEFAULT TRUE,
    is_managed BOOLEAN NOT NULL DEFAULT FALSE,        -- 관리종목
    is_warning BOOLEAN NOT NULL DEFAULT FALSE,        -- 투자 주의
    is_alert BOOLEAN NOT NULL DEFAULT FALSE,          -- 투자 경고
    is_danger BOOLEAN NOT NULL DEFAULT FALSE,         -- 투자 위험
    
    -- 캐싱 정보 (검색 최적화)
    name_normalized VARCHAR(100),  -- 검색용 (영문 변환 등)
    
    -- 메타
    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- 타임스탬프
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_stocks_name ON stocks USING gin (name gin_trgm_ops);
CREATE INDEX idx_stocks_market ON stocks(market);
CREATE INDEX idx_stocks_status ON stocks(is_listed, is_managed, is_alert);

COMMENT ON TABLE stocks IS '종목 마스터 (선택, 검색/캐싱용)';
```

**용도**:
```yaml
선택 사항:
  키움 API에서 매번 종목명 조회 가능
  검색 빠르게 하려면 캐싱 권장
  
업데이트:
  매일 장 마감 후 키움 API에서 동기화
  관리종목/위험 종목 등 상태 변경 감지
```

---

## §7. 인덱스 및 제약

### 7.1 핵심 인덱스 요약

```sql
-- 추적 종목
CREATE INDEX idx_tracked_stocks_code ON tracked_stocks(stock_code);
CREATE INDEX idx_tracked_stocks_status ON tracked_stocks(status);
CREATE INDEX idx_tracked_stocks_active ON tracked_stocks(stock_code, path_type) 
    WHERE status != 'EXITED';

-- 박스
CREATE INDEX idx_boxes_active ON support_boxes(tracked_stock_id, status) 
    WHERE status = 'WAITING';

-- 포지션 (가장 자주 조회)
CREATE INDEX idx_positions_active ON positions(stock_code, status) 
    WHERE status != 'CLOSED';

-- 이벤트 (시계열 조회)
CREATE INDEX idx_events_stock_time ON trade_events(stock_code, occurred_at DESC);

-- 알림 큐 (우선순위 정렬)
CREATE INDEX idx_notif_pending ON notifications(priority, created_at) 
    WHERE status = 'PENDING';
```

### 7.2 외래 키 정책

```yaml
ON DELETE CASCADE:
  - tracked_stocks → support_boxes
  - users → user_sessions, user_settings
  - users → audit_logs

ON DELETE SET NULL:
  - tracked_stocks → positions (MANUAL 케이스 보호)
  - support_boxes → positions

ON DELETE RESTRICT:
  - 거래 이벤트는 보존 (positions → trade_events는 NO ACTION)
```

### 7.3 체크 제약

```sql
-- 박스 가격
CONSTRAINT box_price_valid CHECK (upper_price > lower_price)

-- 비중
CONSTRAINT box_size_valid CHECK (position_size_pct > 0 AND position_size_pct <= 100)

-- 손절폭
CONSTRAINT box_stop_loss_valid CHECK (stop_loss_pct < 0)

-- 포지션 일관성
CONSTRAINT position_closed_consistency CHECK (
    (status = 'CLOSED' AND total_quantity = 0) OR
    (status != 'CLOSED' AND total_quantity > 0)
)

-- 같은 종목 + 같은 경로 활성 추적은 1개만
CONSTRAINT tracked_stocks_unique_active 
    EXCLUDE USING gist (stock_code WITH =, path_type WITH =) 
    WHERE (status != 'EXITED')
```

---

## §8. 마이그레이션 전략

### 8.1 V7.0 → V7.1 마이그레이션

자세한 내용은 `05_MIGRATION_PLAN.md` 참조. 여기는 데이터 모델 관점 요약.

```yaml
Phase 1: V7.0 기존 테이블 분석
  V7.0이 사용한 테이블 식별
  변경 없이 유지할 것
  V7.1로 확장할 것
  완전 폐기할 것

Phase 2: 신규 테이블 생성
  V7.1 전용:
    - support_boxes (신규)
    - vi_events (신규)
    - system_restarts (신규)
    - daily_reports (신규)
    - monthly_reviews (신규)
    - notifications (V7.0 알림 시스템과 통합 또는 별도)
    - audit_logs (보안 강화)
    - user_settings (신규)
    - market_calendar (신규)

Phase 3: 기존 테이블 확장
  tracked_stocks:
    - V7.0에 비슷한 테이블 있었는지 확인
    - 있으면 컬럼 추가 (path_type, vi_recovered_today 등)
    - 없으면 신규 생성
  
  positions:
    - V7.0의 포지션 관련 테이블 확장
    - source ENUM 추가 (SYSTEM_A, SYSTEM_B, MANUAL)
    - 손절선/TS 필드 추가
  
  trade_events:
    - V7.0의 거래 이벤트 테이블 확장
    - event_type ENUM에 V7.1 항목 추가

Phase 4: 데이터 이전
  V7.0의 활성 데이터:
    추적 중 종목 → V7.1 tracked_stocks (TRACKING 상태)
    포지션 보유 → V7.1 positions
    거래 이력 → V7.1 trade_events
  
  V7.0의 V6/V7 신호 시스템 데이터:
    영구 보존 (이력)
    또는 별도 archive 테이블로 이전

Phase 5: V7.0 사용 안 하는 테이블 처리
  파괴적 삭제 안 함
  status 필드로 ARCHIVED 표시
  6개월 후 별도 백업 후 삭제 (운영 결정)
```

### 8.2 마이그레이션 파일 구조

```
src/database/migrations/
├── v71/
│   ├── 001_create_tracked_stocks.sql       (UP + DOWN)
│   ├── 002_create_support_boxes.sql
│   ├── 003_extend_positions.sql
│   ├── 004_create_trade_events.sql
│   ├── 005_create_system_events.sql
│   ├── 006_create_system_restarts.sql
│   ├── 007_create_vi_events.sql
│   ├── 008_create_notifications.sql
│   ├── 009_create_daily_reports.sql
│   ├── 010_create_monthly_reviews.sql
│   ├── 011_create_users.sql
│   ├── 012_create_user_sessions.sql
│   ├── 013_create_audit_logs.sql
│   ├── 014_create_user_settings.sql
│   ├── 015_create_market_calendar.sql
│   ├── 016_create_stocks.sql
│   └── 999_indexes_and_constraints.sql
```

### 8.3 UP/DOWN 양방향 필수

```sql
-- 001_create_tracked_stocks.up.sql
CREATE TYPE tracked_status AS ENUM (...);
CREATE TYPE path_type AS ENUM (...);
CREATE TABLE tracked_stocks (...);
CREATE INDEX idx_tracked_stocks_code ON tracked_stocks(stock_code);
-- ...

-- 001_create_tracked_stocks.down.sql
DROP INDEX IF EXISTS idx_tracked_stocks_code;
DROP TABLE IF EXISTS tracked_stocks;
DROP TYPE IF EXISTS path_type;
DROP TYPE IF EXISTS tracked_status;
```

**하네스 4 (Schema Migration Validator)가 강제**:
- DOWN 마이그레이션 없으면 빌드 차단
- DROP COLUMN 직접 사용 차단 (deprecation 절차 강제)

### 8.4 마이그레이션 안전 룰

```yaml
허용:
  - 새 테이블 추가
  - 새 컬럼 추가 (NULL 허용 또는 DEFAULT 값)
  - 새 인덱스 추가
  - ENUM에 새 값 추가
  - 새 제약 추가 (기존 데이터와 호환 시)

금지 (deprecation 절차 필요):
  - DROP COLUMN
  - DROP TABLE
  - 컬럼 이름 변경
  - 컬럼 타입 호환 안 되게 변경
  - NOT NULL 추가 (기존 NULL 데이터 있으면)
  - ENUM 값 제거

deprecation 절차:
  Phase 1: 컬럼/테이블 deprecated 마킹 (코멘트)
  Phase 2: 코드에서 사용 중단 (1~2 릴리스)
  Phase 3: 실제 삭제 (별도 마이그레이션)
```

---

## §9. 데이터 보존 정책

### 9.1 영구 보존

```yaml
대상:
  - tracked_stocks (모든 상태, EXITED 포함)
  - support_boxes (INVALIDATED, CANCELLED 포함)
  - positions (CLOSED 포함)
  - trade_events
  - audit_logs
  - daily_reports
  - monthly_reviews

이유:
  - 거래 이력 분석
  - 패턴 학습
  - 감사 (audit)
  - 사용자가 과거 검토 가능
```

### 9.2 자동 정리 가능

```yaml
대상:
  - notifications (1년 이상 SENT/EXPIRED)
  - system_events (1년 이상 INFO 레벨)
  - vi_events (3년 이상)

방법:
  pgcron 또는 애플리케이션 스케줄러
  배치 삭제 또는 별도 archive 테이블 이전
```

### 9.3 백업 정책

```yaml
Supabase 자동 백업:
  - 매일 자동 백업
  - Point-in-time recovery (7일)

추가 백업 (권장):
  - 월 1회 전체 dump (별도 저장소)
  - 분기별 외부 클라우드 복제

복구 시나리오:
  - 데이터 손상: PITR (분 단위 복구)
  - 운영 실수: 일일 백업으로 복구
  - 재해: 외부 백업 복원
```

---

## 부록 A: 주요 쿼리 패턴

### A.1 활성 추적 종목 조회

```sql
-- 모든 활성 추적 (대시보드)
SELECT * FROM tracked_stocks 
WHERE status != 'EXITED' 
ORDER BY status, last_status_changed_at DESC;

-- 박스 진입 임박 종목
SELECT ts.*, sb.* 
FROM tracked_stocks ts
JOIN support_boxes sb ON sb.tracked_stock_id = ts.id
WHERE ts.status = 'BOX_SET' 
  AND sb.status = 'WAITING';
```

### A.2 종목당 한도 사용률

```sql
-- 종목별 실제 투입 자본 합계
SELECT 
    stock_code,
    SUM(actual_capital_invested) AS total_invested,
    SUM(actual_capital_invested) / (SELECT total_capital FROM user_settings LIMIT 1) * 100 AS pct_used
FROM positions 
WHERE status != 'CLOSED'
GROUP BY stock_code
HAVING SUM(actual_capital_invested) / (SELECT total_capital FROM user_settings LIMIT 1) * 100 > 25;
-- 25% 초과 종목 (한도 30% 임박)
```

### A.3 일일 거래 요약

```sql
-- 오늘 거래
SELECT 
    event_type,
    COUNT(*) AS count,
    SUM(pnl_amount) AS total_pnl
FROM trade_events
WHERE occurred_at::date = CURRENT_DATE
  AND event_type IN ('PROFIT_TAKE_5', 'PROFIT_TAKE_10', 'STOP_LOSS', 'TS_EXIT')
GROUP BY event_type;
```

### A.4 박스 만료 임박 검사

```sql
-- 30일 이상 정체 + 미진입 박스
SELECT 
    sb.*, 
    ts.stock_code, 
    ts.stock_name,
    EXTRACT(EPOCH FROM (NOW() - sb.created_at)) / 86400 AS days_since_created
FROM support_boxes sb
JOIN tracked_stocks ts ON ts.id = sb.tracked_stock_id
WHERE sb.status = 'WAITING'
  AND sb.created_at < NOW() - INTERVAL '30 days'
  AND (sb.last_reminder_at IS NULL OR sb.last_reminder_at < NOW() - INTERVAL '30 days')
ORDER BY sb.created_at ASC;
```

### A.5 정합성 확인 쿼리

```sql
-- 시스템 DB의 종목별 보유 수량 합계
SELECT 
    stock_code,
    SUM(CASE WHEN source LIKE 'SYSTEM_%' THEN total_quantity ELSE 0 END) AS system_qty,
    SUM(CASE WHEN source = 'MANUAL' THEN total_quantity ELSE 0 END) AS manual_qty,
    SUM(total_quantity) AS total_qty
FROM positions
WHERE status != 'CLOSED'
GROUP BY stock_code;

-- 키움 API 잔고와 비교 (애플리케이션에서)
```

---

## 부록 B: ER 다이어그램 (텍스트)

```
+------------------+       +------------------+       +------------------+
|   users          |       | tracked_stocks   |       | support_boxes    |
+------------------+       +------------------+       +------------------+
| id (PK)          |       | id (PK)          |<----->| tracked_stock_id |
| username         |       | stock_code       |       | box_tier         |
| password_hash    |       | stock_name       |       | upper_price      |
| totp_secret      |       | path_type        |       | lower_price      |
| telegram_chat_id |       | status           |       | position_size_pct|
+------------------+       +------------------+       | strategy_type    |
        |                          |                  | status           |
        |                          |                  +------------------+
        |                          |                          |
        |                          |                          |
        v                          v                          v
+------------------+       +------------------+       +------------------+
| user_sessions    |       | positions        |<----->| trade_events     |
+------------------+       +------------------+       +------------------+
| user_id (FK)     |       | id (PK)          |       | position_id (FK) |
| access_token_hash|       | source           |       | event_type       |
| refresh_token... |       | weighted_avg_... |       | price            |
+------------------+       | total_quantity   |       | quantity         |
                           | fixed_stop_price |       | payload          |
                           | profit_5_executed|       +------------------+
                           | ts_activated     |
                           | status           |
                           +------------------+

+------------------+       +------------------+       +------------------+
| daily_reports    |       | system_events    |       | vi_events        |
+------------------+       +------------------+       +------------------+
| stock_code       |       | event_type       |       | stock_code       |
| narrative_part   |       | severity         |       | state            |
| facts_part       |       | message          |       | trigger_price    |
| status           |       | payload          |       | actions_taken    |
| pdf_path         |       +------------------+       +------------------+
+------------------+

+------------------+       +------------------+       +------------------+
| notifications    |       | system_restarts  |       | audit_logs       |
+------------------+       +------------------+       +------------------+
| severity         |       | restart_at       |       | user_id          |
| event_type       |       | recovery_dur     |       | action           |
| message          |       | reason           |       | before_state     |
| status           |       | reconciliation_..|       | after_state      |
| priority         |       +------------------+       +------------------+
+------------------+
```

---

## 부록 C: 미정 사항

```yaml
C.1 정확한 V7.0 테이블 이름:
  - V7.0 코드 분석 시 확정
  - 마이그레이션 시 1:1 매핑

C.2 Supabase Row Level Security (RLS):
  - 1인 시스템이라 단순화
  - 다중 사용자 확장 시 RLS 정책 추가

C.3 알림 큐 vs Redis:
  - 현재는 PostgreSQL 큐 (notifications 테이블)
  - 부하 증가 시 Redis로 전환 검토

C.4 timeseries 데이터 (시세 봉):
  - 본 스키마에 미포함
  - 필요 시 TimescaleDB 도입 검토
  - 또는 키움 API 매번 조회 (캐싱만 메모리)

C.5 백업 자동화:
  - Supabase 기능 활용
  - 별도 백업 스케줄러 필요 시 결정
```

---

*이 문서는 V7.1 데이터 모델의 단일 진실 원천입니다.*  
*변경 시 마이그레이션 파일 작성 + 하네스 4 통과 필수.*

*최종 업데이트: 2026-04-25*
*02_TRADING_RULES.md의 모든 거래 룰을 데이터 모델로 표현*
