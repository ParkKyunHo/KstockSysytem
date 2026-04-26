-- V7.1 migration 002 -- user_sessions (JWT 1h access + 24h refresh).
-- Spec: docs/v71/03_DATA_MODEL.md §5.2

CREATE TABLE IF NOT EXISTS user_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    access_token_hash VARCHAR(255) NOT NULL,
    refresh_token_hash VARCHAR(255) NOT NULL,

    ip_address INET,
    user_agent TEXT,

    access_expires_at TIMESTAMPTZ NOT NULL,
    refresh_expires_at TIMESTAMPTZ NOT NULL,
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    revoked BOOLEAN NOT NULL DEFAULT FALSE,
    revoked_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON user_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_active ON user_sessions(user_id, revoked)
    WHERE revoked = FALSE;
CREATE INDEX IF NOT EXISTS idx_sessions_expired ON user_sessions(refresh_expires_at);

COMMENT ON TABLE user_sessions IS 'JWT 세션 (1h access + 24h refresh)';
