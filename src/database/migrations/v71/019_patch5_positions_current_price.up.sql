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
