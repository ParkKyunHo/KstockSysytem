-- V7.1 migration 013 -- vi_events (Volatility Interruption history).
-- Spec: docs/v71/03_DATA_MODEL.md §3.3

DO $$ BEGIN
    CREATE TYPE vi_state AS ENUM (
        'TRIGGERED',
        'RESUMED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS vi_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    stock_code VARCHAR(10) NOT NULL,

    state vi_state NOT NULL,
    trigger_price NUMERIC(12, 0),
    resume_at TIMESTAMPTZ,

    handled BOOLEAN NOT NULL DEFAULT FALSE,
    actions_taken JSONB,

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vi_stock ON vi_events(stock_code);
CREATE INDEX IF NOT EXISTS idx_vi_time ON vi_events(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_vi_unhandled ON vi_events(handled, occurred_at) WHERE handled = FALSE;

COMMENT ON TABLE vi_events IS 'VI 발동/해제 이력';
