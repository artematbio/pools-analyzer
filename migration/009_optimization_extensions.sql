-- OPTIMIZATION STAGE: Schema extensions and views
-- This migration is idempotent and safe to run multiple times

-- 1) Extend lp_pool_snapshots with 24h trading metrics and metadata
ALTER TABLE IF EXISTS lp_pool_snapshots
  ADD COLUMN IF NOT EXISTS trades_24h INTEGER,
  ADD COLUMN IF NOT EXISTS buy_24h_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS sell_24h_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS net_flow_24h_usd NUMERIC,
  ADD COLUMN IF NOT EXISTS price_source TEXT,
  ADD COLUMN IF NOT EXISTS volume_source TEXT,
  ADD COLUMN IF NOT EXISTS market_address TEXT,
  ADD COLUMN IF NOT EXISTS dex_protocol TEXT;

-- Helpful composite indexes for last-per-key queries
CREATE INDEX IF NOT EXISTS idx_lp_pool_snapshots_pool_network_created_desc
  ON lp_pool_snapshots (pool_address, network, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_lp_pool_snapshots_market_created_desc
  ON lp_pool_snapshots (market_address, created_at DESC);

-- 2) Ensure token_price_history has required fields (market cap + source already present in create_token_price_history_table.sql)
ALTER TABLE IF EXISTS token_price_history
  ADD COLUMN IF NOT EXISTS source TEXT; -- alias for data_source if needed by apps

-- 3) Events table for real-time alerts
CREATE TABLE IF NOT EXISTS lp_pool_activities (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  network TEXT NOT NULL,
  pool_address TEXT,
  market_address TEXT,
  event_type TEXT NOT NULL, -- large_buy, large_sell, inactivity, volatility, etc.
  amount_usd NUMERIC,
  tx_hash TEXT,
  details JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_time ON lp_pool_activities(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_net ON lp_pool_activities(network);
CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_pool ON lp_pool_activities(pool_address);
CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_market ON lp_pool_activities(market_address);
CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_event ON lp_pool_activities(event_type);

-- 4) Latest-per-key helper views
-- Latest position per position_mint per network
CREATE OR REPLACE VIEW view_latest_lp_position_snapshots AS
WITH ranked AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY position_mint, network ORDER BY created_at DESC) AS rn
  FROM lp_position_snapshots
)
SELECT * FROM ranked WHERE rn = 1;

-- Latest pool snapshot per (pool_address, network)
CREATE OR REPLACE VIEW view_latest_lp_pool_snapshots AS
WITH ranked AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY pool_address, network ORDER BY created_at DESC) AS rn
  FROM lp_pool_snapshots
)
SELECT * FROM ranked WHERE rn = 1;

-- Latest DAO pool snapshot per (pool_address, network)
CREATE OR REPLACE VIEW view_latest_dao_pool_snapshots AS
WITH ranked AS (
  SELECT *,
         ROW_NUMBER() OVER (PARTITION BY pool_address, network ORDER BY created_at DESC) AS rn
  FROM dao_pool_snapshots
)
SELECT * FROM ranked WHERE rn = 1;

-- 5) Materialized view with aggregates for Metabase-friendly analytics
DROP MATERIALIZED VIEW IF EXISTS bio_dao_lp_support_m;
CREATE MATERIALIZED VIEW bio_dao_lp_support_m AS
WITH latest_dao AS (
  SELECT DISTINCT ON (pool_name, network)
    pool_name,
    network,
    dex,
    token_symbol,
    token_address,
    tvl_usd,
    volume_24h_usd,
    token_fdv_usd,
    token_mc_usd,
    token_price_usd,
    bio_price_usd,
    our_position_value_usd,
    target_lp_value_usd,
    lp_gap_usd,
    price_change_24h_percent,
    price_change_7d_percent,
    tvl_change_7d_percent,
    is_bio_pair,
    snapshot_timestamp,
    created_at,
    fee_percent,
    target_fdv_percentage,
    pool_address
  FROM dao_pool_snapshots
  ORDER BY pool_name, network, snapshot_timestamp DESC
),
latest_pool AS (
  SELECT lp.pool_address,
         lp.network,
         lp.trades_24h,
         lp.buy_24h_usd,
         lp.sell_24h_usd,
         lp.net_flow_24h_usd,
         lp.market_address,
         lp.dex_protocol,
         lp.price_source,
         lp.volume_source
  FROM view_latest_lp_pool_snapshots lp
)
SELECT 
  d.pool_name,
  d.network,
  d.dex,
  d.token_symbol,
  d.token_address,
  COALESCE(d.tvl_usd, 0)::NUMERIC AS tvl_usd,
  COALESCE(d.volume_24h_usd, 0)::NUMERIC AS volume_24h_usd,
  COALESCE(d.token_fdv_usd, 0)::NUMERIC AS token_fdv_usd,
  COALESCE(d.token_mc_usd, 0)::NUMERIC AS token_mc_usd,
  COALESCE(d.token_price_usd, 0)::NUMERIC AS token_price_usd,
  COALESCE(d.bio_price_usd, 0)::NUMERIC AS bio_price_usd,
  COALESCE(d.our_position_value_usd, 0)::NUMERIC AS our_position_value_usd,
  COALESCE(d.target_lp_value_usd, 0)::NUMERIC AS target_lp_value_usd,
  COALESCE(d.lp_gap_usd, 0)::NUMERIC AS lp_gap_usd,
  COALESCE(d.price_change_24h_percent, 0)::NUMERIC AS price_change_24h_percent,
  COALESCE(d.price_change_7d_percent, 0)::NUMERIC AS price_change_7d_percent,
  COALESCE(d.tvl_change_7d_percent, 0)::NUMERIC AS tvl_change_7d_percent,
  d.is_bio_pair,
  d.snapshot_timestamp,
  d.created_at,
  d.fee_percent::NUMERIC AS fee_percent,
  d.target_fdv_percentage::NUMERIC AS target_fdv_percentage,
  -- 24h trading aggregates from latest pool snapshot
  p.trades_24h,
  p.buy_24h_usd,
  p.sell_24h_usd,
  p.net_flow_24h_usd,
  p.market_address,
  p.dex_protocol,
  p.price_source,
  p.volume_source
FROM latest_dao d
LEFT JOIN latest_pool p ON (
  d.pool_address = p.pool_address AND d.network = p.network
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_bio_dao_lp_support_m_pool_net ON bio_dao_lp_support_m(pool_name, network);

-- 6) Trading activity helper views (optional)
CREATE OR REPLACE VIEW view_trades_24h AS
SELECT 
  pool_address,
  network,
  created_at::date AS window_end_date,
  trades_24h,
  volume_24h_usd,
  buy_24h_usd,
  sell_24h_usd,
  net_flow_24h_usd,
  price_source,
  volume_source
FROM view_latest_lp_pool_snapshots;

-- 7) Recent activities view
CREATE OR REPLACE VIEW view_recent_activities AS
SELECT *
FROM lp_pool_activities
WHERE timestamp >= NOW() - INTERVAL '7 days'
ORDER BY timestamp DESC;

-- 8) Data freshness dashboard
CREATE OR REPLACE VIEW view_data_freshness AS
SELECT 'lp_position_snapshots' AS table_name, MAX(created_at) AS last_created_at FROM lp_position_snapshots
UNION ALL
SELECT 'lp_pool_snapshots', MAX(created_at) FROM lp_pool_snapshots
UNION ALL
SELECT 'dao_pool_snapshots', MAX(created_at) FROM dao_pool_snapshots
UNION ALL
SELECT 'token_price_history', MAX(last_updated) FROM token_price_history
UNION ALL
SELECT 'lp_pool_activities', MAX(created_at) FROM lp_pool_activities;

-- Notes:
-- - Apply this migration in Supabase SQL editor.
-- - For REFRESH of bio_dao_lp_support_m, schedule after dao_pools_snapshot completes.