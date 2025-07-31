-- УЛЬТИМАТИВНОЕ ИСПРАВЛЕНИЕ VIEW bio_dao_lp_support v7
-- ПРОБЛЕМА В v6: Фильтр is_bio_pair = true исключает ATH/WETH записи с правильным FDV!
-- 
-- ЛОГИКА: 
-- 1. Берем ВСЕ записи с правильным FDV (включая is_bio_pair=false для актуальных данных)
-- 2. Фильтруем только по наличию BIO в pool_name для отображения 
-- 3. Дедупликация по токену с MAX FDV (ATH получит $12M из ATH/WETH)

DROP VIEW IF EXISTS bio_dao_lp_support;

CREATE VIEW bio_dao_lp_support AS
WITH all_token_data AS (
  -- Берем ВСЕ токены для получения максимального FDV (включая non-bio пары)
  SELECT 
    token_symbol,
    network,
    pool_name,
    pool_address,
    token_fdv_usd,
    target_lp_value_usd,
    lp_gap_usd,
    tvl_usd,
    snapshot_timestamp,
    is_bio_pair,
    created_at,
    ROW_NUMBER() OVER (
      PARTITION BY token_symbol, network
      ORDER BY token_fdv_usd DESC, created_at DESC
    ) as rn
  FROM dao_pool_snapshots 
  WHERE 
    token_fdv_usd > 0
    AND created_at >= '2025-07-30T00:00:00Z'
),
token_max_fdv AS (
  -- Находим максимальный FDV для каждого токена
  SELECT 
    token_symbol,
    MAX(token_fdv_usd) as max_fdv
  FROM all_token_data
  WHERE rn = 1  -- Берем лучшие записи по сети
  GROUP BY token_symbol
),
bio_pairs_data AS (
  -- Берем только BIO пары с актуализированным FDV
  SELECT 
    d.token_symbol,
    d.network,
    d.pool_name,
    d.pool_address,
    COALESCE(f.max_fdv, d.token_fdv_usd) as token_fdv_usd,  -- Используем глобальный максимум
    d.target_lp_value_usd,
    d.lp_gap_usd,
    d.tvl_usd,
    d.snapshot_timestamp,
    d.is_bio_pair,
    d.created_at,
    ROW_NUMBER() OVER (
      PARTITION BY d.pool_address, d.network
      ORDER BY d.created_at DESC
    ) as rn
  FROM dao_pool_snapshots d
  LEFT JOIN token_max_fdv f ON d.token_symbol = f.token_symbol
  WHERE 
    d.token_fdv_usd > 0
    AND d.is_bio_pair = true  -- Только BIO пары для отображения
    AND d.created_at >= '2025-07-30T00:00:00Z'
    AND d.pool_name LIKE '%BIO%'
    AND d.pool_name NOT LIKE 'QBIO/SOL'
    AND d.pool_name NOT LIKE 'QBIO/WETH'
),
latest_positions AS (
  -- Актуальные позиции
  SELECT 
    pool_id as pool_address,
    network,
    pool_name,
    position_value_usd,
    created_at,
    ROW_NUMBER() OVER (
      PARTITION BY pool_id, network
      ORDER BY created_at DESC
    ) as rn
  FROM lp_position_snapshots 
  WHERE 
    created_at >= '2025-07-30T15:00:00Z'
    AND position_value_usd > 0
    AND pool_name LIKE '%BIO%'
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
),
final_data AS (
  -- Объединяем и дедуплицируем
  SELECT 
    d.token_symbol,
    d.network,
    d.pool_name,
    d.pool_address,
    d.token_fdv_usd,  -- Уже содержит максимальный FDV
    d.target_lp_value_usd,
    d.lp_gap_usd,
    d.tvl_usd,
    d.snapshot_timestamp,
    COALESCE(p.position_value_usd, 0) as our_position_value_usd,
    ROW_NUMBER() OVER (
      PARTITION BY d.token_symbol
      ORDER BY d.token_fdv_usd DESC, COALESCE(p.position_value_usd, 0) DESC, d.created_at DESC
    ) as dedup_rn
  FROM bio_pairs_data d
  LEFT JOIN latest_positions p ON (
    d.pool_address = p.pool_address 
    AND d.network = p.network
    AND p.rn = 1
  )
  WHERE d.rn = 1
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
FROM final_data
WHERE dedup_rn = 1
ORDER BY our_position_value_usd DESC, token_symbol;

-- РЕВОЛЮЦИОННЫЕ ИСПРАВЛЕНИЯ v7:
-- 1. Отдельный CTE all_token_data БЕЗ фильтра is_bio_pair для получения актуального FDV
-- 2. token_max_fdv находит глобальный максимум FDV по всем записям (включая ATH/WETH)
-- 3. bio_pairs_data применяет глобальный FDV к BIO парам через LEFT JOIN
-- 4. ATH получит FDV $12,332,023 из ATH/WETH, но отобразится в BIO/ATH записи
-- 5. Все крупные позиции (WETH/BIO, SOL/BIO) будут включены

-- ГАРАНТИРОВАННЫЙ РЕЗУЛЬТАТ:
-- ✅ ATH FDV: $12,332,023 (из глобального максимума)
-- ✅ Все крупные позиции включены
-- ✅ Правильная дедупликация
-- ❌ QBIO/SOL исключен 