-- 006_add_position_extensions.sql
-- Optional enrichment for position snapshots

BEGIN;

ALTER TABLE lp_position_snapshots
  ADD COLUMN IF NOT EXISTS current_price NUMERIC,
  ADD COLUMN IF NOT EXISTS market_address TEXT,
  ADD COLUMN IF NOT EXISTS data_quality TEXT;

COMMIT;


