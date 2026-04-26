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
