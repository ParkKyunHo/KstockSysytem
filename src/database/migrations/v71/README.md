# V7.1 database migrations

Spec: `docs/v71/03_DATA_MODEL.md`

## Apply order (FK-aware)

```
000_extensions.up.sql           uuid-ossp, pgcrypto, pg_trgm, btree_gist
001_create_users
002_create_user_sessions        FK -> users
003_create_user_settings        FK -> users
004_create_audit_logs           FK -> users
005_create_market_calendar
006_create_stocks
007_create_tracked_stocks       gist EXCLUDE constraint (one active row per
                                stock+path)
008_create_support_boxes        FK -> tracked_stocks
009_create_positions            FK -> tracked_stocks, support_boxes
010_create_trade_events         FK -> positions, tracked_stocks, support_boxes
011_create_system_events
012_create_system_restarts
013_create_vi_events
014_create_notifications
015_create_daily_reports        FK -> tracked_stocks, users
016_create_monthly_reviews
```

## DOWN order

Reverse of UP. Each migration ships a paired `*.down.sql` that drops
indexes, then table, then ENUM types in reverse dependency order.

## Idempotency

`UP` files use `CREATE ... IF NOT EXISTS` (tables, indexes) and
`DO $$ BEGIN CREATE TYPE ... EXCEPTION WHEN duplicate_object THEN null; END $$`
(ENUMs, since PostgreSQL has no `CREATE TYPE IF NOT EXISTS`). Re-running
an `UP` against a partially-applied database is safe.

`DOWN` files use `DROP ... IF EXISTS` for the same reason.

## Apply tooling (TBD in P2.5 / Phase 5)

These are raw SQL files. The runner (likely Alembic with raw SQL
operations, or Supabase CLI) is decided in P2.5 once the operational
target is fixed (managed Supabase vs local PostgreSQL).

For ad-hoc verification:

```bash
# psql against the V7.1 dev database (after creating it)
for f in 000*.up.sql 001*.up.sql 002*.up.sql ... 016*.up.sql; do
    psql "$DATABASE_URL" -f "src/database/migrations/v71/$f"
done

# Roll back
for f in 016*.down.sql ... 000*.down.sql; do
    psql "$DATABASE_URL" -f "src/database/migrations/v71/$f"
done
```

## Hardness 4 (Schema Migration Validator)

Enforces the UP/DOWN pairing: every `*.up.sql` must have a matching
`*.down.sql`. Run via `python scripts/harness/schema_migration_validator.py`
or it is invoked automatically by `pre-commit` and the run-all script.
