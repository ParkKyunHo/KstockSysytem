-- V7.1 migration 000 -- PostgreSQL extensions.
-- Spec: docs/v71/03_DATA_MODEL.md §1.3
--
-- All required by V7.1:
--   uuid-ossp  -- UUID v4 primary keys (every table)
--   pgcrypto   -- bcrypt password hashing (users.password_hash)
--   pg_trgm    -- trigram search on stocks.name (gin index)
--   btree_gist -- gist EXCLUDE constraint on tracked_stocks active row

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gist";
