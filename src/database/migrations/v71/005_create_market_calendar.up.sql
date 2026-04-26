-- V7.1 migration 005 -- market_calendar.
-- Spec: docs/v71/03_DATA_MODEL.md §6.1

DO $$ BEGIN
    CREATE TYPE market_day_type AS ENUM (
        'TRADING',
        'HOLIDAY',
        'HALF_DAY',
        'EMERGENCY_CLOSED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS market_calendar (
    trading_date DATE PRIMARY KEY,
    day_type market_day_type NOT NULL,

    market_open_time TIME,
    market_close_time TIME,

    note VARCHAR(200),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_calendar_type ON market_calendar(day_type);

COMMENT ON TABLE market_calendar IS '한국 시장 일정 (수동 또는 외부 데이터로 관리)';
