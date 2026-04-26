-- V7.1 migration 008 -- support_boxes (user-defined entry zones).
-- Spec: docs/v71/03_DATA_MODEL.md §2.2

DO $$ BEGIN
    CREATE TYPE box_status AS ENUM (
        'WAITING',
        'TRIGGERED',
        'INVALIDATED',
        'CANCELLED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE strategy_type AS ENUM (
        'PULLBACK',
        'BREAKOUT'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS support_boxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tracked_stock_id UUID NOT NULL REFERENCES tracked_stocks(id) ON DELETE CASCADE,

    box_tier INTEGER NOT NULL,
    upper_price NUMERIC(12, 0) NOT NULL,
    lower_price NUMERIC(12, 0) NOT NULL,

    position_size_pct NUMERIC(5, 2) NOT NULL,
    stop_loss_pct NUMERIC(8, 6) NOT NULL DEFAULT -0.05,

    strategy_type strategy_type NOT NULL,

    status box_status NOT NULL DEFAULT 'WAITING',

    memo TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    last_reminder_at TIMESTAMPTZ,

    invalidation_reason VARCHAR(100),

    CONSTRAINT box_price_valid CHECK (upper_price > lower_price),
    CONSTRAINT box_size_valid CHECK (position_size_pct > 0 AND position_size_pct <= 100),
    CONSTRAINT box_stop_loss_valid CHECK (stop_loss_pct < 0)
);

CREATE INDEX IF NOT EXISTS idx_boxes_tracked_stock ON support_boxes(tracked_stock_id);
CREATE INDEX IF NOT EXISTS idx_boxes_status ON support_boxes(status);
CREATE INDEX IF NOT EXISTS idx_boxes_active ON support_boxes(tracked_stock_id, status)
    WHERE status = 'WAITING';
CREATE INDEX IF NOT EXISTS idx_boxes_pending_reminder ON support_boxes(created_at, last_reminder_at)
    WHERE status = 'WAITING';

COMMENT ON TABLE support_boxes IS '사용자 정의 박스 (매수 계획)';
COMMENT ON COLUMN support_boxes.box_tier IS '박스 층 (1차, 2차, ...). 다층 박스 시 진입 순서 자유';
COMMENT ON COLUMN support_boxes.position_size_pct IS '총 자본 대비 투입 비중 %';
COMMENT ON COLUMN support_boxes.stop_loss_pct IS '음수로 저장 (-0.05 = -5%)';
