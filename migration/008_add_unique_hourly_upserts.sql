-- 008_add_unique_hourly_upserts.sql
-- Ensure idempotent hourly UPSERT windows for pools and positions

BEGIN;

-- Pools: enforce unique per hour per (pool_address or pool_id, network)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'uniq_lp_pool_snapshots_hour'
  ) THEN
    CREATE UNIQUE INDEX uniq_lp_pool_snapshots_hour
      ON lp_pool_snapshots (
        COALESCE(pool_id, pool_address),
        network,
        date_trunc('hour', created_at)
      );
  END IF;
END $$;

-- Positions: enforce unique per hour per (position_mint, network)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes WHERE schemaname = 'public' AND indexname = 'uniq_lp_position_snapshots_hour'
  ) THEN
    CREATE UNIQUE INDEX uniq_lp_position_snapshots_hour
      ON lp_position_snapshots (
        position_mint,
        network,
        date_trunc('hour', created_at)
      );
  END IF;
END $$;

COMMIT;


