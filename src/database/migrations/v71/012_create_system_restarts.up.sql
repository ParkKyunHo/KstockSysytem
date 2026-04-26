-- V7.1 migration 012 -- system_restarts (frequency monitoring).
-- Spec: docs/v71/03_DATA_MODEL.md §3.2

DO $$ BEGIN
    CREATE TYPE restart_reason AS ENUM (
        'KNOWN_DEPLOY',
        'MANUAL',
        'CRASH',
        'OOM',
        'AUTO_RECOVERY',
        'UNKNOWN'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS system_restarts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    restart_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    recovery_started_at TIMESTAMPTZ,
    recovery_completed_at TIMESTAMPTZ,
    recovery_duration_seconds INTEGER,

    reason restart_reason NOT NULL DEFAULT 'UNKNOWN',
    reason_detail TEXT,

    reconciliation_summary JSONB,

    cancelled_orders_count INTEGER DEFAULT 0,
    resubscribed_stocks_count INTEGER DEFAULT 0,

    safe_mode_released BOOLEAN NOT NULL DEFAULT FALSE,
    notification_sent BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_restarts_time ON system_restarts(restart_at DESC);

COMMENT ON TABLE system_restarts IS '시스템 재시작 이력 (빈도 모니터링)';
