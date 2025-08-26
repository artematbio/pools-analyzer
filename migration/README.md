# Migrations for pools-analyzer (Supabase/Postgres)

Order of execution:
- 001_extend_lp_pool_snapshots.sql
- 002_create_lp_pool_activities.sql
- 003_views_latest_snapshots.sql
- 004_create_bio_dao_lp_support_m.sql
- 005_add_indexes_constraints.sql
- 006_add_position_extensions.sql
- 007_backfill_market_addresses.sql

Apply using Supabase SQL editor or psql in order.
After 004, ensure scheduler refreshes mview after snapshots.
