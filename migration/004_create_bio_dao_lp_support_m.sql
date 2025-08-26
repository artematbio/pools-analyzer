-- 004_create_bio_dao_lp_support_m.sql
-- Materialized view for fast reporting with correct aggregation

BEGIN;

CREATE MATERIALIZED VIEW IF NOT EXISTS bio_dao_lp_support_m AS
  SELECT 
    s.network,
    s.pool_name,
    s.dex,
    COALESCE(SUM(COALESCE(lp.position_value_usd::numeric, 0)), 0)::NUMERIC AS our_positions_usd,
    COALESCE(SUM(COALESCE(lp.fees_usd::numeric, 0)), 0)::NUMERIC AS our_fees_usd,
    COUNT(lp.position_mint)::INT AS our_positions_count,
    s.tvl_usd::NUMERIC,
    s.volume_24h_usd::NUMERIC
  FROM view_latest_lp_pool_snapshots s
  LEFT JOIN view_latest_lp_position_snapshots lp
    ON lp.network = s.network AND COALESCE(lp.pool_id, lp.pool_address) = COALESCE(s.pool_id, s.pool_address)
  GROUP BY 1,2,3,6,7;

CREATE INDEX IF NOT EXISTS idx_bio_support_m_net ON bio_dao_lp_support_m (network);

COMMIT;

-- Scheduler action (pseudo-SQL): REFRESH MATERIALIZED VIEW CONCURRENTLY bio_dao_lp_support_m;


