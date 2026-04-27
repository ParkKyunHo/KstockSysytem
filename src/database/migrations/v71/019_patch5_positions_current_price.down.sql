-- V7.1 migration 019 DOWN -- PRD Patch #5 rollback.
-- Removes live-price columns from positions.
-- Real-time valuation will be lost; the frontend falls back to mock prices
-- if this is rolled back during an active trading day.

BEGIN;

ALTER TABLE positions DROP COLUMN IF EXISTS pnl_pct;
ALTER TABLE positions DROP COLUMN IF EXISTS pnl_amount;
ALTER TABLE positions DROP COLUMN IF EXISTS current_price_at;
ALTER TABLE positions DROP COLUMN IF EXISTS current_price;

COMMIT;
