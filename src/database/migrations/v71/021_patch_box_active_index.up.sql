-- V7.1 migration 021 -- Align idx_boxes_active with PRD 03_DATA_MODEL §2.2.
--
-- Spec: docs/v71/03_DATA_MODEL.md §2.2 line 356 (3-column partial index).
-- Reason: 008_create_support_boxes.up.sql line 53-54 created
--         idx_boxes_active(tracked_stock_id, status) (2 columns) but PRD
--         specifies (tracked_stock_id, path_type, status) (3 columns).
--         P-Wire-Box-1 (V71BoxManager DB-backed) hot path
--         ``list_waiting_for_tracked(tracked_stock_id, path_type)``
--         filters by path_type — without the 3-column index this falls
--         back to a wider scan once box rows accumulate.
--
-- Effect: index-only swap. No data change. PRD §0.1 mandates DOWN; this
--         restores the 008 definition.

BEGIN;

DROP INDEX IF EXISTS idx_boxes_active;

CREATE INDEX IF NOT EXISTS idx_boxes_active
    ON support_boxes(tracked_stock_id, path_type, status)
    WHERE status = 'WAITING';

COMMIT;
