-- 001_extend_lp_pool_snapshots.sql
-- Extends lp_pool_snapshots with market activity fields and sources

BEGIN;

ALTER TABLE lp_pool_snapshots
  ADD COLUMN IF NOT EXISTS trades_24h INTEGER DEFAULT 0 NOT NULL,
  ADD COLUMN IF NOT EXISTS buy_24h_usd NUMERIC DEFAULT 0 NOT NULL,
  ADD COLUMN IF NOT EXISTS sell_24h_usd NUMERIC DEFAULT 0 NOT NULL,
  ADD COLUMN IF NOT EXISTS net_flow_24h_usd NUMERIC DEFAULT 0 NOT NULL,
  ADD COLUMN IF NOT EXISTS price_source TEXT,
  ADD COLUMN IF NOT EXISTS volume_source TEXT,
  ADD COLUMN IF NOT EXISTS market_address TEXT,
  ADD COLUMN IF NOT EXISTS dex_protocol TEXT;

CREATE INDEX IF NOT EXISTS idx_lp_pool_snapshots_pool_net_created
  ON lp_pool_snapshots (pool_address, network, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lp_pool_snapshots_market_created
  ON lp_pool_snapshots (market_address, created_at DESC);

COMMIT;


