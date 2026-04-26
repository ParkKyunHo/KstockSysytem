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
