-- V7.1 migration 018 DOWN -- PRD Patch #5 rollback.
-- Drops orders table + ENUM types in dependency-safe order.

BEGIN;

DROP TABLE IF EXISTS v71_orders;

DROP TYPE IF EXISTS order_trade_type;
DROP TYPE IF EXISTS order_state;
DROP TYPE IF EXISTS order_direction;

COMMIT;
