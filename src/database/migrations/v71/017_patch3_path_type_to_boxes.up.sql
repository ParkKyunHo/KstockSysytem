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
