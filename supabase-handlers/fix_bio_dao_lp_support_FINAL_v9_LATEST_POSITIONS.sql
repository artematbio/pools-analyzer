-- ИСПРАВЛЕНИЕ VIEW bio_dao_lp_support v9 - ТОЛЬКО ПОСЛЕДНИЕ ПОЗИЦИИ
-- ПРОБЛЕМА В v8: SUM() суммирует ВСЕ исторические записи позиций вместо последних
-- 
-- НОВАЯ ЛОГИКА: 
-- 1. Берем ТОЛЬКО ПОСЛЕДНЮЮ запись каждой position_mint
-- 2. ЗАТЕМ суммируем эти последние значения по пулам
-- 3. Избегаем дублирования исторических snapshot'ов

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
  -- BIO пары с глобальным максимальным FDV
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
  -- 🔧 ИСПРАВЛЕНИЕ: Берем ТОЛЬКО ПОСЛЕДНЮЮ запись каждой position_mint
  SELECT 
    pool_id as pool_address,
    network,
    pool_name,
    position_mint,
    position_value_usd,
    created_at,
    ROW_NUMBER() OVER (
      PARTITION BY position_mint  -- Группируем по уникальной позиции
      ORDER BY created_at DESC   -- Берем самую свежую запись
    ) as rn
  FROM lp_position_snapshots 
  WHERE 
    created_at >= '2025-07-30T15:00:00Z'
    AND position_value_usd > 0
    AND pool_name LIKE '%BIO%'
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
),
aggregated_positions AS (
  -- Теперь агрегируем только последние записи каждой позиции
  SELECT 
    pool_address,
    network,
    pool_name,
    COUNT(*) as unique_positions_count,  -- Считаем уникальные позиции
    SUM(position_value_usd) as total_position_value_usd,  -- Суммируем ТОЛЬКО последние значения
    MAX(created_at) as latest_created_at
  FROM latest_positions 
  WHERE rn = 1  -- Только последние записи каждой position_mint
  GROUP BY pool_address, network, pool_name
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
    COALESCE(p.total_position_value_usd, 0) as our_position_value_usd,  -- Сумма только последних записей
    COALESCE(p.unique_positions_count, 0) as positions_count,  -- Количество уникальных позиций
    ROW_NUMBER() OVER (
      PARTITION BY d.token_symbol
      ORDER BY d.token_fdv_usd DESC, COALESCE(p.total_position_value_usd, 0) DESC, d.created_at DESC
    ) as dedup_rn
  FROM bio_pairs_data d
  LEFT JOIN aggregated_positions p ON (
    d.pool_address = p.pool_address 
    AND d.network = p.network
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
  our_position_value_usd,  -- Теперь содержит сумму ТОЛЬКО последних записей позиций
  positions_count,  -- Количество уникальных позиций в пуле
  lp_gap_usd,
  tvl_usd,
  snapshot_timestamp
FROM final_data
WHERE dedup_rn = 1
ORDER BY our_position_value_usd DESC, token_symbol;

-- КЛЮЧЕВЫЕ ИСПРАВЛЕНИЯ v9:
-- 1. latest_positions CTE: ROW_NUMBER() OVER (PARTITION BY position_mint ORDER BY created_at DESC)
-- 2. Берем WHERE rn = 1 для получения только последних записей каждой позиции
-- 3. ЗАТЕМ агрегируем эти последние записи по пулам
-- 4. Избегаем суммирования исторических snapshot'ов одной позиции
-- 5. SOL/BIO покажет корректную сумму последних значений позиций, не исторических 