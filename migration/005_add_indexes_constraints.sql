-- 005_add_indexes_constraints.sql
-- Data quality and performance constraints

BEGIN;

-- Enforce non-negative numeric metrics where applicable
ALTER TABLE lp_position_snapshots
  ALTER COLUMN position_value_usd SET DEFAULT 0,
  ALTER COLUMN fees_usd SET DEFAULT 0;

-- Optional checks (uncomment if columns exist and types are numeric)
-- ALTER TABLE lp_position_snapshots ADD CONSTRAINT chk_pos_value_nonneg CHECK (position_value_usd >= 0);
-- ALTER TABLE lp_position_snapshots ADD CONSTRAINT chk_pos_fees_nonneg CHECK (fees_usd >= 0);

-- Helpful indexes for latest queries
CREATE INDEX IF NOT EXISTS idx_pos_snap_latest ON lp_position_snapshots (position_mint, network, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pool_snap_latest ON lp_pool_snapshots (pool_address, network, created_at DESC);

COMMIT;


