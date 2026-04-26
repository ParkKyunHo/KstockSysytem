DROP INDEX IF EXISTS idx_positions_active;
DROP INDEX IF EXISTS idx_positions_tracked;
DROP INDEX IF EXISTS idx_positions_source;
DROP INDEX IF EXISTS idx_positions_status;
DROP INDEX IF EXISTS idx_positions_stock;
DROP TABLE IF EXISTS positions;
DROP TYPE IF EXISTS position_status;
DROP TYPE IF EXISTS position_source;
