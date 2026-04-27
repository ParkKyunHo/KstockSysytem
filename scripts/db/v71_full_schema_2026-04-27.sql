-- V7.1 migration 000 -- PostgreSQL extensions.
-- Spec: docs/v71/03_DATA_MODEL.md §1.3
--
-- All required by V7.1:
--   uuid-ossp  -- UUID v4 primary keys (every table)
--   pgcrypto   -- bcrypt password hashing (users.password_hash)
--   pg_trgm    -- trigram search on stocks.name (gin index)
--   btree_gist -- gist EXCLUDE constraint on tracked_stocks active row

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";
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
-- V7.1 migration 006 -- stocks (master, optional cache).
-- Spec: docs/v71/03_DATA_MODEL.md §6.2

CREATE TABLE IF NOT EXISTS stocks (
    code VARCHAR(10) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    market VARCHAR(20),
    sector VARCHAR(100),
    industry VARCHAR(100),

    is_listed BOOLEAN NOT NULL DEFAULT TRUE,
    is_managed BOOLEAN NOT NULL DEFAULT FALSE,
    is_warning BOOLEAN NOT NULL DEFAULT FALSE,
    is_alert BOOLEAN NOT NULL DEFAULT FALSE,
    is_danger BOOLEAN NOT NULL DEFAULT FALSE,

    name_normalized VARCHAR(100),

    last_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_stocks_name ON stocks USING gin (name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_stocks_market ON stocks(market);
CREATE INDEX IF NOT EXISTS idx_stocks_status ON stocks(is_listed, is_managed, is_alert);

COMMENT ON TABLE stocks IS '종목 마스터 (선택, 검색/캐싱용)';
-- V7.1 migration 007 -- tracked_stocks (dual-path PATH_A/PATH_B support).
-- Spec: docs/v71/03_DATA_MODEL.md §2.1

DO $$ BEGIN
    CREATE TYPE tracked_status AS ENUM (
        'TRACKING',
        'BOX_SET',
        'POSITION_OPEN',
        'POSITION_PARTIAL',
        'EXITED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE path_type AS ENUM (
        'PATH_A',
        'PATH_B'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS tracked_stocks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,
    market VARCHAR(20),

    path_type path_type NOT NULL,

    status tracked_status NOT NULL DEFAULT 'TRACKING',

    user_memo TEXT,
    source VARCHAR(50),

    vi_recovered_today BOOLEAN NOT NULL DEFAULT FALSE,
    vi_recovered_at TIMESTAMPTZ,

    auto_exit_reason VARCHAR(50),
    auto_exit_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_status_changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- One active row per (stock_code, path_type). EXITED rows excluded
    -- so historical exits are preserved indefinitely.
    CONSTRAINT tracked_stocks_unique_active
        EXCLUDE USING gist (stock_code WITH =, path_type WITH =)
        WHERE (status != 'EXITED')
);

CREATE INDEX IF NOT EXISTS idx_tracked_stocks_code ON tracked_stocks(stock_code);
CREATE INDEX IF NOT EXISTS idx_tracked_stocks_status ON tracked_stocks(status);
CREATE INDEX IF NOT EXISTS idx_tracked_stocks_path ON tracked_stocks(path_type);
CREATE INDEX IF NOT EXISTS idx_tracked_stocks_active ON tracked_stocks(stock_code, path_type)
    WHERE status != 'EXITED';

COMMENT ON TABLE tracked_stocks IS '추적 종목 (이중 경로 지원: PATH_A 단타 + PATH_B 중기)';
COMMENT ON COLUMN tracked_stocks.path_type IS '경로 A: 3분봉 단타, 경로 B: 일봉 중기';
COMMENT ON COLUMN tracked_stocks.vi_recovered_today IS 'VI 발동 후 당일 신규 진입 금지 플래그';
-- V7.1 migration 008 -- support_boxes (user-defined entry zones).
-- Spec: docs/v71/03_DATA_MODEL.md §2.2

DO $$ BEGIN
    CREATE TYPE box_status AS ENUM (
        'WAITING',
        'TRIGGERED',
        'INVALIDATED',
        'CANCELLED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE strategy_type AS ENUM (
        'PULLBACK',
        'BREAKOUT'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS support_boxes (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    tracked_stock_id UUID NOT NULL REFERENCES tracked_stocks(id) ON DELETE CASCADE,

    box_tier INTEGER NOT NULL,
    upper_price NUMERIC(12, 0) NOT NULL,
    lower_price NUMERIC(12, 0) NOT NULL,

    position_size_pct NUMERIC(5, 2) NOT NULL,
    stop_loss_pct NUMERIC(8, 6) NOT NULL DEFAULT -0.05,

    strategy_type strategy_type NOT NULL,

    status box_status NOT NULL DEFAULT 'WAITING',

    memo TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    modified_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    triggered_at TIMESTAMPTZ,
    invalidated_at TIMESTAMPTZ,
    last_reminder_at TIMESTAMPTZ,

    invalidation_reason VARCHAR(100),

    CONSTRAINT box_price_valid CHECK (upper_price > lower_price),
    CONSTRAINT box_size_valid CHECK (position_size_pct > 0 AND position_size_pct <= 100),
    CONSTRAINT box_stop_loss_valid CHECK (stop_loss_pct < 0)
);

CREATE INDEX IF NOT EXISTS idx_boxes_tracked_stock ON support_boxes(tracked_stock_id);
CREATE INDEX IF NOT EXISTS idx_boxes_status ON support_boxes(status);
CREATE INDEX IF NOT EXISTS idx_boxes_active ON support_boxes(tracked_stock_id, status)
    WHERE status = 'WAITING';
CREATE INDEX IF NOT EXISTS idx_boxes_pending_reminder ON support_boxes(created_at, last_reminder_at)
    WHERE status = 'WAITING';

COMMENT ON TABLE support_boxes IS '사용자 정의 박스 (매수 계획)';
COMMENT ON COLUMN support_boxes.box_tier IS '박스 층 (1차, 2차, ...). 다층 박스 시 진입 순서 자유';
COMMENT ON COLUMN support_boxes.position_size_pct IS '총 자본 대비 투입 비중 %';
COMMENT ON COLUMN support_boxes.stop_loss_pct IS '음수로 저장 (-0.05 = -5%)';
-- V7.1 migration 009 -- positions (system + manual unified).
-- Spec: docs/v71/03_DATA_MODEL.md §2.3

DO $$ BEGIN
    CREATE TYPE position_source AS ENUM (
        'SYSTEM_A',
        'SYSTEM_B',
        'MANUAL'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

DO $$ BEGIN
    CREATE TYPE position_status AS ENUM (
        'OPEN',
        'PARTIAL_CLOSED',
        'CLOSED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    source position_source NOT NULL,

    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,

    tracked_stock_id UUID REFERENCES tracked_stocks(id),
    triggered_box_id UUID REFERENCES support_boxes(id),

    initial_avg_price NUMERIC(12, 0) NOT NULL,
    weighted_avg_price NUMERIC(12, 0) NOT NULL,
    total_quantity INTEGER NOT NULL,

    fixed_stop_price NUMERIC(12, 0) NOT NULL,

    profit_5_executed BOOLEAN NOT NULL DEFAULT FALSE,
    profit_10_executed BOOLEAN NOT NULL DEFAULT FALSE,

    ts_activated BOOLEAN NOT NULL DEFAULT FALSE,
    ts_base_price NUMERIC(12, 0),
    ts_stop_price NUMERIC(12, 0),
    ts_active_multiplier NUMERIC(3, 1),

    status position_status NOT NULL DEFAULT 'OPEN',

    actual_capital_invested NUMERIC(15, 0) NOT NULL,

    closed_at TIMESTAMPTZ,
    final_pnl NUMERIC(15, 0),
    final_pnl_pct NUMERIC(8, 4),
    close_reason VARCHAR(50),

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT position_qty_valid CHECK (total_quantity >= 0),
    CONSTRAINT position_avg_valid CHECK (weighted_avg_price > 0),
    CONSTRAINT position_closed_consistency CHECK (
        (status = 'CLOSED' AND total_quantity = 0) OR
        (status != 'CLOSED' AND total_quantity > 0)
    )
);

CREATE INDEX IF NOT EXISTS idx_positions_stock ON positions(stock_code);
CREATE INDEX IF NOT EXISTS idx_positions_status ON positions(status);
CREATE INDEX IF NOT EXISTS idx_positions_source ON positions(source);
CREATE INDEX IF NOT EXISTS idx_positions_tracked ON positions(tracked_stock_id)
    WHERE tracked_stock_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_positions_active ON positions(stock_code, status)
    WHERE status != 'CLOSED';

COMMENT ON TABLE positions IS '보유 포지션 (시스템 + 수동 통합 관리)';
COMMENT ON COLUMN positions.weighted_avg_price IS '추가 매수 시 가중 평균 재계산. 매도 시 변경 없음';
COMMENT ON COLUMN positions.ts_base_price IS '매수 후 최고가 (실시간 갱신)';
COMMENT ON COLUMN positions.actual_capital_invested IS '한도 계산용 실제 투입 자본';
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
-- V7.1 migration 015 -- daily_reports (on-demand Claude Opus 4.7 reports).
-- Spec: docs/v71/03_DATA_MODEL.md §4.1

DO $$ BEGIN
    CREATE TYPE report_status AS ENUM (
        'PENDING',
        'GENERATING',
        'COMPLETED',
        'FAILED'
    );
EXCEPTION WHEN duplicate_object THEN null; END $$;

CREATE TABLE IF NOT EXISTS daily_reports (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    stock_code VARCHAR(10) NOT NULL,
    stock_name VARCHAR(100) NOT NULL,

    tracked_stock_id UUID REFERENCES tracked_stocks(id),

    requested_by UUID REFERENCES users(id),
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    generation_started_at TIMESTAMPTZ,
    generation_completed_at TIMESTAMPTZ,
    generation_duration_seconds INTEGER,

    model_version VARCHAR(50) NOT NULL DEFAULT 'claude-opus-4-7',
    prompt_tokens INTEGER,
    completion_tokens INTEGER,

    status report_status NOT NULL DEFAULT 'PENDING',

    narrative_part TEXT,
    facts_part TEXT,

    data_sources JSONB,

    pdf_path VARCHAR(500),
    excel_path VARCHAR(500),

    user_notes TEXT,

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_reports_stock ON daily_reports(stock_code);
CREATE INDEX IF NOT EXISTS idx_reports_status ON daily_reports(status);
CREATE INDEX IF NOT EXISTS idx_reports_user ON daily_reports(requested_by);
CREATE INDEX IF NOT EXISTS idx_reports_time ON daily_reports(requested_at DESC);

COMMENT ON TABLE daily_reports IS 'On-Demand 종목 리포트 (Claude Opus 4.7)';
COMMENT ON COLUMN daily_reports.narrative_part IS 'PART 1: 종목의 이야기 (출발->성장->현재->미래)';
COMMENT ON COLUMN daily_reports.facts_part IS 'PART 2: 객관 팩트 (사업/공급망/재무/공시 등)';
-- V7.1 migration 016 -- monthly_reviews (auto-generated 1st of each month).
-- Spec: docs/v71/03_DATA_MODEL.md §4.2

CREATE TABLE IF NOT EXISTS monthly_reviews (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    review_month DATE NOT NULL,

    tracked_count INTEGER NOT NULL DEFAULT 0,
    box_set_count INTEGER NOT NULL DEFAULT 0,
    position_open_count INTEGER NOT NULL DEFAULT 0,
    position_partial_count INTEGER NOT NULL DEFAULT 0,

    box_drop_alerts JSONB,
    long_stagnant_alerts JSONB,
    expiring_boxes JSONB,

    total_pnl_amount NUMERIC(15, 0),
    total_pnl_pct NUMERIC(8, 4),
    win_count INTEGER,
    loss_count INTEGER,

    full_stock_list JSONB,

    sent_at TIMESTAMPTZ,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT monthly_reviews_unique UNIQUE (review_month)
);

CREATE INDEX IF NOT EXISTS idx_monthly_reviews_month ON monthly_reviews(review_month DESC);

COMMENT ON TABLE monthly_reviews IS '매월 1일 자동 생성되는 추적 리뷰';
-- V7.1 migration 017 -- PRD Patch #3 (2026-04-25):
-- Move ``path_type`` from tracked_stocks to support_boxes so that the
-- same listed stock can host both PATH_A and PATH_B boxes simultaneously.
--
-- Spec source: docs/v71/01_PRD_MAIN.md §Patch #3 + 03_DATA_MODEL.md +
--              09_API_SPEC.md §3 / §4 (path_type 박스 단위 명시).
--
-- Order of operations matters: migrate data first, then drop the old
-- column / unique constraint. This keeps the downgrade path safe.

BEGIN;

-- 1) Add path_type to support_boxes (nullable initially so backfill can run).
ALTER TABLE support_boxes
    ADD COLUMN IF NOT EXISTS path_type path_type;

-- 2) Backfill from the parent tracked_stocks row.
UPDATE support_boxes sb
   SET path_type = ts.path_type
  FROM tracked_stocks ts
 WHERE sb.tracked_stock_id = ts.id
   AND sb.path_type IS NULL;

-- 3) Lock the column down.
ALTER TABLE support_boxes
    ALTER COLUMN path_type SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_boxes_path ON support_boxes(path_type);

-- 4) tracked_stocks no longer carries path_type. Drop dependent indexes
-- and the gist EXCLUDE constraint first.
DROP INDEX IF EXISTS idx_tracked_stocks_active;
DROP INDEX IF EXISTS idx_tracked_stocks_path;

ALTER TABLE tracked_stocks
    DROP CONSTRAINT IF EXISTS tracked_stocks_unique_active;

ALTER TABLE tracked_stocks
    DROP COLUMN IF EXISTS path_type;

-- 5) New uniqueness rule: at most one active row per stock_code
-- (path is per box now). Historical EXITED rows preserved.
ALTER TABLE tracked_stocks
    ADD CONSTRAINT tracked_stocks_unique_active
    EXCLUDE USING gist (stock_code WITH =) WHERE (status != 'EXITED');

CREATE INDEX IF NOT EXISTS idx_tracked_stocks_active
    ON tracked_stocks(stock_code) WHERE status != 'EXITED';

COMMIT;
-- V7.1 migration 018 -- PRD Patch #5 (V7.1.0d, 2026-04-27):
-- Create the ``orders`` table to track Kiwoom order submissions.
--
-- Spec source: docs/v71/03_DATA_MODEL.md §2.4 (orders) +
--              docs/v71/09_API_SPEC.md §13 (주문 API) +
--              docs/v71/13_APPENDIX.md §6.2.Z +
--              docs/v71/KIWOOM_API_ANALYSIS.md (1,366 라인).
--
-- Background: Kiwoom REST API has no ``client_order_id`` field; V7.1 must
-- maintain its own mapping via ``orders.kiwoom_order_no`` (UNIQUE) and
-- ``orders.kiwoom_orig_order_no`` (정정/취소 시 원주문 추적).

BEGIN;

-- 1) ENUM types -----------------------------------------------------

CREATE TYPE order_direction AS ENUM (
    'BUY',
    'SELL'
);

CREATE TYPE order_state AS ENUM (
    'SUBMITTED',  -- 키움 접수 완료, 체결 대기
    'PARTIAL',    -- 부분 체결
    'FILLED',     -- 전량 체결
    'CANCELLED',  -- 취소됨
    'REJECTED'    -- 키움 거부
);

CREATE TYPE order_trade_type AS ENUM (
    'LIMIT',           -- 키움 trde_tp=0
    'MARKET',          -- 키움 trde_tp=3
    'CONDITIONAL',     -- 키움 trde_tp=5
    'AFTER_HOURS',     -- 키움 trde_tp=81
    'BEST_LIMIT',      -- 키움 trde_tp=6
    'PRIORITY_LIMIT'   -- 키움 trde_tp=7
);

-- 2) Table ----------------------------------------------------------

CREATE TABLE v71_orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),

    -- Kiwoom mapping (★ V7.1 자체 매핑 키)
    kiwoom_order_no VARCHAR(20) NOT NULL UNIQUE,
    kiwoom_orig_order_no VARCHAR(20),

    -- Linkage (NULL 가능 -- 시점별 다름)
    position_id UUID REFERENCES positions(id),
    box_id UUID REFERENCES support_boxes(id),
    tracked_stock_id UUID REFERENCES tracked_stocks(id),

    -- Order content
    stock_code VARCHAR(10) NOT NULL,
    direction order_direction NOT NULL,
    trade_type order_trade_type NOT NULL,
    quantity INTEGER NOT NULL,
    price NUMERIC(12, 0),
    exchange VARCHAR(10) NOT NULL DEFAULT 'KRX',

    -- State
    state order_state NOT NULL DEFAULT 'SUBMITTED',
    filled_quantity INTEGER NOT NULL DEFAULT 0,
    filled_avg_price NUMERIC(12, 2),

    -- Reject / cancel reasons
    reject_reason TEXT,
    cancel_reason VARCHAR(100),

    -- Retry tracking (PRD §3.3 5초 × 3회)
    retry_attempt INTEGER NOT NULL DEFAULT 1,

    -- Timestamps
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    filled_at TIMESTAMPTZ,
    cancelled_at TIMESTAMPTZ,
    rejected_at TIMESTAMPTZ,

    -- Kiwoom raw payload (audit + debugging)
    kiwoom_raw_request JSONB,
    kiwoom_raw_response JSONB,

    -- Constraints
    CONSTRAINT order_qty_positive CHECK (quantity > 0),
    CONSTRAINT order_filled_consistency CHECK (filled_quantity <= quantity),
    CONSTRAINT order_price_required CHECK (
        (trade_type = 'MARKET' AND price IS NULL) OR
        (trade_type != 'MARKET' AND price IS NOT NULL AND price > 0)
    )
);

-- 3) Indexes --------------------------------------------------------

CREATE UNIQUE INDEX idx_v71_orders_kiwoom_no ON v71_orders(kiwoom_order_no);
CREATE INDEX idx_v71_orders_position ON v71_orders(position_id) WHERE position_id IS NOT NULL;
CREATE INDEX idx_v71_orders_box ON v71_orders(box_id) WHERE box_id IS NOT NULL;
CREATE INDEX idx_v71_orders_stock ON v71_orders(stock_code, submitted_at DESC);
CREATE INDEX idx_v71_orders_state_pending ON v71_orders(state) WHERE state IN ('SUBMITTED', 'PARTIAL');

-- 4) Comments -------------------------------------------------------

COMMENT ON TABLE v71_orders IS 'PRD Patch #5: V7.1 키움 주문 추적. 키움 API에 client_order_id 필드 없음 → 자체 매핑 필수. 명명: V7.0 orders와 격리 (PRD §1.4 V71 접두사 + 헌법 §3 충돌 금지)';
COMMENT ON COLUMN v71_orders.kiwoom_order_no IS 'PRD Patch #5: 키움 ord_no UNIQUE. 모든 후속 추적의 키';
COMMENT ON COLUMN v71_orders.kiwoom_orig_order_no IS 'PRD Patch #5: 정정/취소 주문 시 원주문 추적';
COMMENT ON COLUMN v71_orders.kiwoom_raw_request IS 'PRD Patch #5: 키움 요청 원문 보존 (감사 + 디버깅). 토큰/API 키 미포함';
COMMENT ON COLUMN v71_orders.kiwoom_raw_response IS 'PRD Patch #5: 키움 응답 원문 보존';

COMMIT;
-- V7.1 migration 019 -- PRD Patch #5 (V7.1.0d, 2026-04-27):
-- Add live-price columns to ``positions`` so the API can return real-time
-- valuation directly (replacing the frontend's mock-price lookup).
--
-- Spec source: docs/v71/03_DATA_MODEL.md §2.3 (positions) +
--              docs/v71/09_API_SPEC.md §5.1 +
--              docs/v71/13_APPENDIX.md §6.2.Z (한계 1 해결).
--
-- Update policy:
--   1순위: WebSocket 0B (실시간, < 1초, NFR1)
--   2순위: kt00018 계좌평가잔고 (5초 폴링, WebSocket 끊김 시)
--   3순위: ka10001 주식기본정보 (재시작 직후 단발)
--
-- All 4 columns are nullable -- existing OPEN/PARTIAL_CLOSED rows continue
-- to be valid; the price feed will populate them on the next tick.
-- ALTER ADD COLUMN with NULL is metadata-only on PostgreSQL 11+.

BEGIN;

ALTER TABLE positions
    ADD COLUMN current_price NUMERIC(12, 0);

ALTER TABLE positions
    ADD COLUMN current_price_at TIMESTAMPTZ;

ALTER TABLE positions
    ADD COLUMN pnl_amount NUMERIC(15, 0);

ALTER TABLE positions
    ADD COLUMN pnl_pct NUMERIC(8, 6);

COMMENT ON COLUMN positions.current_price IS
    'PRD Patch #5: 실시간 시세. WebSocket 0B (<1s) > kt00018 (5s) > ka10001 (재시작)';
COMMENT ON COLUMN positions.current_price_at IS
    'PRD Patch #5: current_price 마지막 갱신 시각';
COMMENT ON COLUMN positions.pnl_amount IS
    'PRD Patch #5: 평가 손익 (current_price 기반). (current_price - weighted_avg_price) × total_quantity';
COMMENT ON COLUMN positions.pnl_pct IS
    'PRD Patch #5: 평가 손익률. (current_price / weighted_avg_price - 1)';

COMMIT;
-- V7.1 migration 020 -- PRD Patch #5 (V7.1.0d, 2026-04-27):
-- Soft-delete support for ``daily_reports``. Reports are permanent records
-- (audit + retrospective); UI delete becomes ``is_hidden = TRUE``.
--
-- Spec source: docs/v71/03_DATA_MODEL.md §4.1 (daily_reports) +
--              docs/v71/09_API_SPEC.md §8.7-8.8 (DELETE soft / restore) +
--              docs/v71/13_APPENDIX.md §6.2.Z (한계 2 해결).
--
-- Migration strategy follows 03_DATA_MODEL.md §0.1 (NOT NULL 추가는 3단계):
--   1) Add column NULL-allowed
--   2) UPDATE existing rows to FALSE
--   3) Tighten to NOT NULL + DEFAULT
--
-- Migration Strategy Agent (06_AGENTS_SPEC.md §3) verified WARNING-PASS.

BEGIN;

-- Step 1: Add NULL-allowed columns.
ALTER TABLE daily_reports
    ADD COLUMN is_hidden BOOLEAN;

ALTER TABLE daily_reports
    ADD COLUMN hidden_at TIMESTAMPTZ;

ALTER TABLE daily_reports
    ADD COLUMN hidden_reason VARCHAR(50);

-- Step 2: Backfill all existing reports as visible.
UPDATE daily_reports
   SET is_hidden = FALSE
 WHERE is_hidden IS NULL;

-- Step 3: Lock is_hidden down (NOT NULL + DEFAULT).
ALTER TABLE daily_reports
    ALTER COLUMN is_hidden SET NOT NULL;

ALTER TABLE daily_reports
    ALTER COLUMN is_hidden SET DEFAULT FALSE;

-- Step 4: Partial index for fast "visible reports" queries.
CREATE INDEX idx_reports_visible
    ON daily_reports(created_at DESC)
 WHERE is_hidden = FALSE;

-- Step 5: Comments.
COMMENT ON COLUMN daily_reports.is_hidden IS
    'PRD Patch #5: 소프트 삭제 플래그. DELETE 호출 시 true로 설정 (영구 보존, 목록에서만 숨김)';
COMMENT ON COLUMN daily_reports.hidden_at IS
    'PRD Patch #5: 숨김 처리 시각';
COMMENT ON COLUMN daily_reports.hidden_reason IS
    'PRD Patch #5: 숨김 사유 (USER_REQUEST / DUPLICATE / OUTDATED 등)';

COMMIT;
