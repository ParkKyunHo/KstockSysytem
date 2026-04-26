DROP INDEX IF EXISTS idx_audit_target;
DROP INDEX IF EXISTS idx_audit_time;
DROP INDEX IF EXISTS idx_audit_action;
DROP INDEX IF EXISTS idx_audit_user;
DROP TABLE IF EXISTS audit_logs;
DROP TYPE IF EXISTS audit_action;
