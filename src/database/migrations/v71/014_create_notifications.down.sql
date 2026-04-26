DROP INDEX IF EXISTS idx_notif_stock;
DROP INDEX IF EXISTS idx_notif_rate_limit;
DROP INDEX IF EXISTS idx_notif_pending;
DROP INDEX IF EXISTS idx_notif_status;
DROP TABLE IF EXISTS notifications;
DROP TYPE IF EXISTS notification_status;
DROP TYPE IF EXISTS notification_channel;
DROP TYPE IF EXISTS notification_severity;
