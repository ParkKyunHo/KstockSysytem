-- V7.1 migration 010 -- trade_events (audit trail).
-- Spec: docs/v71/03_DATA_MODEL.md §2.4

DO $$ BEGIN
    CREATE TYPE trade_event_type AS ENUM (
        -- Buy
        'BUY_EXECUTED',
        'PYRAMID_BUY',
        'MANUAL_BUY',
        'MANUAL_PYRAMID_BUY',
        -- Sell
        'PROFIT_TAKE_5',
        'PROFIT_TAKE_10',
        'STOP_LOSS',
        'TS_EXIT',
        'MANUAL_PARTIAL_EXIT',
        'MANUAL_FULL_EXIT',
        'AUTO_EXIT',
        -- Order lifecycle
        'ORDER_SENT',
        'ORDER_FILLED',
        'ORDER_PARTIAL_FILLED',
        'ORDER_CANCELLED',
        'ORDER_FAILED',
        -- System
        'POSITION_RECONCILED',
        'EVENT_RESET',
        'STOP_UPDATED',
        'TS_ACTIVATED',
        'TS_VALIDATED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS trade_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    position_id UUID REFERENCES positions(id),
    tracked_stock_id UUID REFERENCES tracked_stocks(id),
    box_id UUID REFERENCES support_boxes(id),

    event_type trade_event_type NOT NULL,

    stock_code VARCHAR(10) NOT NULL,
    price NUMERIC(12, 0),
    quantity INTEGER,

    order_id VARCHAR(50),
    client_order_id VARCHAR(50),
    attempt INTEGER,

    pnl_amount NUMERIC(15, 0),
    pnl_pct NUMERIC(8, 4),

    avg_price_before NUMERIC(12, 0),
    avg_price_after NUMERIC(12, 0),

    payload JSONB,

    reason VARCHAR(200),
    error_message TEXT,

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_events_position ON trade_events(position_id);
CREATE INDEX IF NOT EXISTS idx_events_tracked_stock ON trade_events(tracked_stock_id);
CREATE INDEX IF NOT EXISTS idx_events_type ON trade_events(event_type);
CREATE INDEX IF NOT EXISTS idx_events_occurred ON trade_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_stock_time ON trade_events(stock_code, occurred_at DESC);

COMMENT ON TABLE trade_events IS '모든 거래 이벤트 (audit trail)';
COMMENT ON COLUMN trade_events.payload IS '이벤트별 추가 정보 JSONB';
