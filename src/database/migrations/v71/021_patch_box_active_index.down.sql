-- V7.1 migration 021 DOWN -- Restore the 008 2-column idx_boxes_active.

BEGIN;

DROP INDEX IF EXISTS idx_boxes_active;

CREATE INDEX IF NOT EXISTS idx_boxes_active
    ON support_boxes(tracked_stock_id, status)
    WHERE status = 'WAITING';

COMMIT;
