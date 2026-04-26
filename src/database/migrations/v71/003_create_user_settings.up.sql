-- V7.1 migration 003 -- user_settings (1:1 with users).
-- Spec: docs/v71/03_DATA_MODEL.md §5.4
-- Constraint enforced at app layer: notify_critical may NOT be set FALSE
-- (safety lock per PRD).

CREATE TABLE IF NOT EXISTS user_settings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,

    total_capital NUMERIC(15, 0),

    notify_critical BOOLEAN NOT NULL DEFAULT TRUE,
    notify_high BOOLEAN NOT NULL DEFAULT TRUE,
    notify_medium BOOLEAN NOT NULL DEFAULT TRUE,
    notify_low BOOLEAN NOT NULL DEFAULT TRUE,

    quiet_hours_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    quiet_hours_start TIME,
    quiet_hours_end TIME,

    theme VARCHAR(20) NOT NULL DEFAULT 'dark',
    language VARCHAR(5) NOT NULL DEFAULT 'ko',

    preferences JSONB DEFAULT '{}'::jsonb,

    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE user_settings IS '사용자 설정 (1:1 관계)';
COMMENT ON COLUMN user_settings.notify_critical IS '강제 ON (앱 레벨에서 변경 차단, 안전장치)';
