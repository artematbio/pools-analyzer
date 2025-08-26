-- 003_views_latest_snapshots.sql
-- Helper views to always get last snapshot per key

BEGIN;

CREATE OR REPLACE VIEW view_latest_lp_position_snapshots AS
  SELECT DISTINCT ON (position_mint, network) *
  FROM lp_position_snapshots
  ORDER BY position_mint, network, created_at DESC;

CREATE OR REPLACE VIEW view_latest_lp_pool_snapshots AS
  SELECT DISTINCT ON (COALESCE(pool_id, pool_address), network) *
  FROM lp_pool_snapshots
  ORDER BY COALESCE(pool_id, pool_address), network, created_at DESC;

CREATE OR REPLACE VIEW view_latest_dao_pool_snapshots AS
  SELECT DISTINCT ON (pool_name, network) *
  FROM dao_pool_snapshots
  ORDER BY pool_name, network, snapshot_timestamp DESC;

COMMIT;


