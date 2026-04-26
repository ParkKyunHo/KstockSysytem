DROP INDEX IF EXISTS idx_tracked_stocks_active;
DROP INDEX IF EXISTS idx_tracked_stocks_path;
DROP INDEX IF EXISTS idx_tracked_stocks_status;
DROP INDEX IF EXISTS idx_tracked_stocks_code;
DROP TABLE IF EXISTS tracked_stocks;
DROP TYPE IF EXISTS path_type;
DROP TYPE IF EXISTS tracked_status;
