-- V7.1 migration 018 -- PRD Patch #5 (V7.1.0d, 2026-04-27):
-- Create the ``orders`` table to track Kiwoom order submissions.
--
-- Spec source: docs/v71/03_DATA_MODEL.md §2.4 (orders) +
--              docs/v71/09_API_SPEC.md §13 (주문 API) +
--              docs/v71/13_APPENDIX.md §6.2.Z +
--              docs/v71/KIWOOM_API_ANALYSIS.md (1,366 라인).
--
-- Background: Kiwoom REST API has no ``client_order_id`` field; V7.1 must
-- maintain its own mapping via ``orders.kiwoom_order_no`` (UNIQUE) and
-- ``orders.kiwoom_orig_order_no`` (정정/취소 시 원주문 추적).

BEGIN;

-- 1) ENUM types -----------------------------------------------------

CREATE TYPE order_direction AS ENUM (
    'BUY',
    'SELL'
);

CREATE TYPE order_state AS ENUM (
    'SUBMITTED',  -- 키움 접수 완료, 체결 대기
    'PARTIAL',    -- 부분 체결
    'FILLED',     -- 전량 체결
    'CANCELLED',  -- 취소됨
    'REJECTED'    -- 키움 거부
);

CREATE TYPE order_trade_type AS ENUM (
    'LIMIT',           -- 키움 trde_tp=0
    'MARKET',          -- 키움 trde_tp=3
    'CONDITIONAL',     -- 키움 trde_tp=5
    'AFTER_HOURS',     -- 키움 trde_tp=81
    'BEST_LIMIT',      -- 키움 trde_tp=6
    'PRIORITY_LIMIT'   -- 키움 trde_tp=7
);

-- 2) Table ----------------------------------------------------------

CREATE TABLE v71_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Kiwoom mapping (★ V7.1 자체 매핑 키)
    kiwoom_order_no VARCHAR(20) NOT NULL UNIQUE,
    kiwoom_orig_order_no VARCHAR(20),

    -- Linkage (NULL 가능 -- 시점별 다름)
    position_id UUID REFERENCES positions(id),
    box_id UUID REFERENCES support_boxes(id),
    tracked_stock_id UUID REFERENCES tracked_stocks(id),

    -- Order content
    stock_code VARCHAR(10) NOT NULL,
    direction order_direction NOT NULL,
    trade_type order_trade_type NOT NULL,
    quantity INTEGER NOT NULL,
    price NUMERIC(12, 0),
    exchange VARCHAR(10) NOT NULL DEFAULT 'KRX',

    -- State
    state order_state NOT NULL DEFAULT 'SUBMITTED',
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    filled_avg_price NUMERIC(12, 2),

    -- Reject / cancel reasons
    reject_reason TEXT,
    cancel_reason VARCHAR(100),

    -- Retry tracking (PRD §3.3 5초 × 3회)
    retry_attempt INTEGER NOT NULL DEFAULT 1,

    -- Timestamps
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,

    -- Kiwoom raw payload (audit + debugging)
    kiwoom_raw_request JSONB,
    kiwoom_raw_response JSONB,

    -- Constraints
    CONSTRAINT order_qty_positive CHECK (quantity > 0),
    CONSTRAINT order_filled_consistency CHECK (filled_quantity <= quantity),
    CONSTRAINT order_price_required CHECK (
        (trade_type = 'MARKET' AND price IS NULL) OR
        (trade_type != 'MARKET' AND price IS NOT NULL AND price > 0)
    )
);

-- 3) Indexes --------------------------------------------------------

CREATE UNIQUE INDEX idx_v71_orders_kiwoom_no ON v71_orders(kiwoom_order_no);
CREATE INDEX idx_v71_orders_position ON v71_orders(position_id) WHERE position_id IS NOT NULL;
CREATE INDEX idx_v71_orders_box ON v71_orders(box_id) WHERE box_id IS NOT NULL;
CREATE INDEX idx_v71_orders_stock ON v71_orders(stock_code, submitted_at DESC);
CREATE INDEX idx_v71_orders_state_pending ON v71_orders(state) WHERE state IN ('SUBMITTED', 'PARTIAL');

-- 4) Comments -------------------------------------------------------

COMMENT ON TABLE v71_orders IS 'PRD Patch #5: V7.1 키움 주문 추적. 키움 API에 client_order_id 필드 없음 → 자체 매핑 필수. 명명: V7.0 orders와 격리 (PRD §1.4 V71 접두사 + 헌법 §3 충돌 금지)';
COMMENT ON COLUMN v71_orders.kiwoom_order_no IS 'PRD Patch #5: 키움 ord_no UNIQUE. 모든 후속 추적의 키';
COMMENT ON COLUMN v71_orders.kiwoom_orig_order_no IS 'PRD Patch #5: 정정/취소 주문 시 원주문 추적';
COMMENT ON COLUMN v71_orders.kiwoom_raw_request IS 'PRD Patch #5: 키움 요청 원문 보존 (감사 + 디버깅). 토큰/API 키 미포함';
COMMENT ON COLUMN v71_orders.kiwoom_raw_response IS 'PRD Patch #5: 키움 응답 원문 보존';

COMMIT;
