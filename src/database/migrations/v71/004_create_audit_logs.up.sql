-- V7.1 migration 004 -- audit_logs.
-- Spec: docs/v71/03_DATA_MODEL.md §5.3

DO $$ BEGIN
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
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id),

    action audit_action NOT NULL,

    target_type VARCHAR(50),
    target_id UUID,

    before_state JSONB,
    after_state JSONB,

    ip_address INET,
    user_agent TEXT,

    success BOOLEAN NOT NULL DEFAULT TRUE,
    error_message TEXT,

    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_audit_user ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_logs(action);
CREATE INDEX IF NOT EXISTS idx_audit_time ON audit_logs(occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_target ON audit_logs(target_type, target_id);

COMMENT ON TABLE audit_logs IS '보안 감사 로그 (모든 사용자 액션)';
