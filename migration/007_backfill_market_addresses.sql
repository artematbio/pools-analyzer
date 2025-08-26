-- 007_backfill_market_addresses.sql
-- Backfill market_address where possible (Solana example)
-- NOTE: Update logic according to your mapping source; this is a placeholder.

BEGIN;

-- Example: copy from lp_pool_snapshots into lp_position_snapshots by (pool_id/network)
UPDATE lp_position_snapshots p
SET market_address = s.market_address
FROM lp_pool_snapshots s
WHERE p.market_address IS NULL
  AND p.network = s.network
  AND p.pool_id = s.pool_id;

COMMIT;


