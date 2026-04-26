-- V7.1 migration 000 (DOWN) -- drop extensions only if no other db object uses them.
-- Use CASCADE manually outside of migrations if you really need to remove these.

DROP EXTENSION IF EXISTS "btree_gist";
DROP EXTENSION IF EXISTS "pg_trgm";
DROP EXTENSION IF EXISTS "pgcrypto";
DROP EXTENSION IF EXISTS "uuid-ossp";
