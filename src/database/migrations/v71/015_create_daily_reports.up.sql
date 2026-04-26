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
