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
