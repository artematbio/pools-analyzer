-- 002_create_lp_pool_activities.sql
-- Events / alerts table

BEGIN;

CREATE TABLE IF NOT EXISTS lp_pool_activities (
  id BIGSERIAL PRIMARY KEY,
  timestamp TIMESTAMPTZ NOT NULL DEFAULT now(),
  network TEXT NOT NULL,
  pool_address TEXT,
  market_address TEXT,
  event_type TEXT NOT NULL,
  amount_usd NUMERIC NOT NULL CHECK (amount_usd >= 0),
  tx_hash TEXT,
  details JSONB
);

CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_time
  ON lp_pool_activities (timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_lp_pool_activities_market
  ON lp_pool_activities (market_address, timestamp DESC);

COMMIT;


