-- V7.1 migration 009 -- positions (system + manual unified).
-- Spec: docs/v71/03_DATA_MODEL.md §2.3

DO $$ BEGIN
    CREATE TYPE position_source AS ENUM (
        'SYSTEM_A',
        'SYSTEM_B',
        'MANUAL'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE position_status AS ENUM (
        'OPEN',
        'PARTIAL_CLOSED',
        'CLOSED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    source position_source NOT NULL,

    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,

    tracked_stock_id UUID REFERENCES tracked_stocks(id),
    triggered_box_id UUID REFERENCES support_boxes(id),

    initial_avg_price NUMERIC(12, 0) NOT NULL,
    weighted_avg_price NUMERIC(12, 0) NOT NULL,
    total_quantity INTEGER NOT NULL,

    fixed_stop_price NUMERIC(12, 0) NOT NULL,

    profit_5_executed BOOLEAN NOT NULL DEFAULT FALSE,
    profit_10_executed BOOLEAN NOT NULL DEFAULT FALSE,

    ts_activated BOOLEAN NOT NULL DEFAULT FALSE,
    ts_base_price NUMERIC(12, 0),
    ts_stop_price NUMERIC(12, 0),
    ts_active_multiplier NUMERIC(3, 1),

    status position_status NOT NULL DEFAULT 'OPEN',

    actual_capital_invested NUMERIC(15, 0) NOT NULL,

    closed_at TIMESTAMPTZ,
    final_pnl NUMERIC(15, 0),
    final_pnl_pct NUMERIC(8, 4),
    close_reason VARCHAR(50),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT position_qty_valid CHECK (total_quantity >= 0),
    CONSTRAINT position_avg_valid CHECK (weighted_avg_price > 0),
    CONSTRAINT position_closed_consistency CHECK (
        (status = 'CLOSED' AND total_quantity = 0) OR
        (status != 'CLOSED' AND total_quantity > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_positions_stock ON positions(stock_code);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_source ON positions(source);
CREATE INDEX IF NOT EXISTS idx_positions_tracked ON positions(tracked_stock_id)
    WHERE tracked_stock_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_positions_active ON positions(stock_code, status)
    WHERE status != 'CLOSED';

COMMENT ON TABLE positions IS '보유 포지션 (시스템 + 수동 통합 관리)';
COMMENT ON COLUMN positions.weighted_avg_price IS '추가 매수 시 가중 평균 재계산. 매도 시 변경 없음';
COMMENT ON COLUMN positions.ts_base_price IS '매수 후 최고가 (실시간 갱신)';
COMMENT ON COLUMN positions.actual_capital_invested IS '한도 계산용 실제 투입 자본';
