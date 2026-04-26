-- V7.1 migration 014 -- notifications (priority queue + history).
-- Spec: docs/v71/03_DATA_MODEL.md §3.4

DO $$ BEGIN
    CREATE TYPE notification_severity AS ENUM (
        'CRITICAL',
        'HIGH',
        'MEDIUM',
        'LOW'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE notification_channel AS ENUM (
        'TELEGRAM',
        'WEB',
        'BOTH'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE notification_status AS ENUM (
        'PENDING',
        'SENT',
        'FAILED',
        'SUPPRESSED',
        'EXPIRED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    severity notification_severity NOT NULL,
    channel notification_channel NOT NULL,
    event_type VARCHAR(50) NOT NULL,

    stock_code VARCHAR(10),

    title VARCHAR(200),
    message TEXT NOT NULL,
    payload JSONB,

    status notification_status NOT NULL DEFAULT 'PENDING',

    sent_at TIMESTAMPTZ,
    failed_at TIMESTAMPTZ,
    failure_reason VARCHAR(200),
    retry_count INTEGER NOT NULL DEFAULT 0,

    rate_limit_key VARCHAR(100),

    -- CRITICAL=1, HIGH=2, MEDIUM=3, LOW=4 (lower = sent first)
    priority INTEGER NOT NULL,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_notif_status ON notifications(status, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_notif_pending ON notifications(priority, created_at)
    WHERE status = 'PENDING';
CREATE INDEX IF NOT EXISTS idx_notif_rate_limit ON notifications(rate_limit_key, created_at)
    WHERE rate_limit_key IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_notif_stock ON notifications(stock_code, created_at DESC);

COMMENT ON TABLE notifications IS '알림 큐 + 발송 이력';
