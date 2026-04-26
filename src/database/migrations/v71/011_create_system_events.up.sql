-- V7.1 migration 011 -- system_events.
-- Spec: docs/v71/03_DATA_MODEL.md §3.1

DO $$ BEGIN
    CREATE TYPE system_event_type AS ENUM (
        'STARTUP',
        'SHUTDOWN',
        'WEBSOCKET_CONNECTED',
        'WEBSOCKET_DISCONNECTED',
        'WEBSOCKET_RECONNECTED',
        'API_AUTH_REFRESHED',
        'API_ERROR',
        'DB_CONNECTION_LOST',
        'TELEGRAM_API_FAILED',
        'CIRCUIT_BREAKER_OPEN',
        'CIRCUIT_BREAKER_CLOSED',
        'HEALTH_CHECK',
        'CONFIG_CHANGED',
        'FEATURE_FLAG_CHANGED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS system_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    event_type system_event_type NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'INFO',

    message TEXT NOT NULL,
    component VARCHAR(50),

    payload JSONB,

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sys_events_type ON system_events(event_type);
CREATE INDEX IF NOT EXISTS idx_sys_events_severity ON system_events(severity);
CREATE INDEX IF NOT EXISTS idx_sys_events_time ON system_events(occurred_at DESC);

COMMENT ON TABLE system_events IS '시스템 레벨 이벤트 로그';
