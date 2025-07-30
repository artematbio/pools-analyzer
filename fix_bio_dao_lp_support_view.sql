-- ИСПРАВЛЕНИЕ VIEW bio_dao_lp_support
-- ПРОБЛЕМА: View использует старые данные с разными FDV для одного токена на разных чейнах
-- РЕШЕНИЕ: Использовать только самые последние snapshot_timestamp для каждой комбинации токен+сеть

DROP VIEW IF EXISTS bio_dao_lp_support;

CREATE OR REPLACE VIEW bio_dao_lp_support AS
WITH latest_snapshots AS (
  SELECT 
    token_symbol,
    network,
    pool_name,
    token_fdv_usd,
    target_lp_value_usd,
    our_position_value_usd,
    lp_gap_usd,
    tvl_usd,
    snapshot_timestamp,
    is_bio_pair,
    ROW_NUMBER() OVER (
      PARTITION BY token_symbol, network, pool_name
      ORDER BY snapshot_timestamp DESC  -- КРИТИЧНО: Берем только последние данные
    ) as rn
  FROM dao_pool_snapshots 
  WHERE 
    token_fdv_usd > 0  -- Исключаем записи без FDV
    AND is_bio_pair = true  -- Только BIO пары
    AND snapshot_timestamp >= CURRENT_DATE  -- Только сегодняшние данные
)
SELECT 
  token_symbol,
  CASE 
    WHEN network = 'ethereum' THEN 'Ethereum'
    WHEN network = 'base' THEN 'Base'  
    WHEN network = 'solana' THEN 'Solana'
    ELSE UPPER(LEFT(network, 1)) || LOWER(SUBSTRING(network, 2))
  END as network_display,
  pool_name,
  CASE 
    WHEN target_lp_value_usd > our_position_value_usd * 2 THEN 'Need to Create'
    WHEN our_position_value_usd > target_lp_value_usd * 1.5 THEN 'Excessive Liquidity (Large)'
    WHEN our_position_value_usd > target_lp_value_usd * 0.8 THEN 'Optimal Range'
    ELSE 'Under-liquified'
  END as bio_pair_status,
  token_fdv_usd,
  target_lp_value_usd,
  our_position_value_usd,
  lp_gap_usd,
  tvl_usd,
  snapshot_timestamp
FROM latest_snapshots 
WHERE rn = 1  -- Только самые последние записи для каждого пула
ORDER BY token_symbol, network_display;

-- КОММЕНТАРИЙ:
-- Этот view теперь гарантирует что:
-- 1. Используются только самые последние данные (snapshot_timestamp DESC)
-- 2. Один токен имеет единый FDV на всех чейнах (благодаря нормализации в dao_pools_snapshot.py)
-- 3. Показываются только BIO пары (is_bio_pair = true)
-- 4. Исключены записи без FDV (token_fdv_usd > 0) 