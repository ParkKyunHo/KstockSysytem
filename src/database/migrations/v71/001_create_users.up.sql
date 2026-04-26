-- V7.1 migration 001 -- users.
-- Spec: docs/v71/03_DATA_MODEL.md §5.1

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,

    totp_secret VARCHAR(100),
    totp_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    backup_codes JSONB,

    telegram_chat_id VARCHAR(50) UNIQUE,
    telegram_username VARCHAR(50),

    role VARCHAR(20) NOT NULL DEFAULT 'OWNER',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,

    last_login_at TIMESTAMPTZ,
    last_login_ip INET,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_telegram ON users(telegram_chat_id);

COMMENT ON TABLE users IS '사용자 (1인 시스템이지만 확장 고려)';
