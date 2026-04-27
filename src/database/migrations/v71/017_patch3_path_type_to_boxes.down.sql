-- V7.1 migration 017 -- DOWN.
-- Reverse PRD Patch #3 by moving path_type back to tracked_stocks.

BEGIN;

ALTER TABLE tracked_stocks
    ADD COLUMN IF NOT EXISTS path_type path_type;

UPDATE tracked_stocks ts
   SET path_type = sb.path_type
  FROM (
      SELECT DISTINCT ON (tracked_stock_id) tracked_stock_id, path_type
        FROM support_boxes
       ORDER BY tracked_stock_id, created_at
  ) sb
 WHERE ts.id = sb.tracked_stock_id
   AND ts.path_type IS NULL;

UPDATE tracked_stocks SET path_type = 'PATH_A' WHERE path_type IS NULL;

ALTER TABLE tracked_stocks
    ALTER COLUMN path_type SET NOT NULL;

DROP INDEX IF EXISTS idx_tracked_stocks_active;
ALTER TABLE tracked_stocks DROP CONSTRAINT IF EXISTS tracked_stocks_unique_active;

ALTER TABLE tracked_stocks
    ADD CONSTRAINT tracked_stocks_unique_active
    EXCLUDE USING gist (stock_code WITH =, path_type WITH =) WHERE (status != 'EXITED');

CREATE INDEX IF NOT EXISTS idx_tracked_stocks_path ON tracked_stocks(path_type);
CREATE INDEX IF NOT EXISTS idx_tracked_stocks_active
    ON tracked_stocks(stock_code, path_type) WHERE status != 'EXITED';

DROP INDEX IF EXISTS idx_boxes_path;
ALTER TABLE support_boxes DROP COLUMN IF EXISTS path_type;

COMMIT;
