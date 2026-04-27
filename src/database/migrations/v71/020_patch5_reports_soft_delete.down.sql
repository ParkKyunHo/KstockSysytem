-- V7.1 migration 020 DOWN -- PRD Patch #5 rollback.
--
-- WARNING: rollback drops the is_hidden flag and any soft-delete history.
-- Reports that were hidden by users will reappear in the visible list.
-- The hidden_at / hidden_reason metadata is permanently lost.

BEGIN;

DROP INDEX IF EXISTS idx_reports_visible;

ALTER TABLE daily_reports DROP COLUMN IF EXISTS hidden_reason;
ALTER TABLE daily_reports DROP COLUMN IF EXISTS hidden_at;
ALTER TABLE daily_reports DROP COLUMN IF EXISTS is_hidden;

COMMIT;
