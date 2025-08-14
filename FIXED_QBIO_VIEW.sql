-- ====================================================================
-- ИСПРАВЛЕНИЕ ДЛЯ QBIO В VIEW bio_dao_lp_support
-- ====================================================================
-- ПРОБЛЕМА: latest_token_metrics берет самые свежие записи (даже с FDV=0)
-- РЕШЕНИЕ: Изменить CTE чтобы брать последние записи с ВАЛИДНЫМИ данными
-- ====================================================================

DROP VIEW IF EXISTS bio_dao_lp_support;

CREATE VIEW bio_dao_lp_support AS
WITH dao_tokens_base AS (
  -- Список всех DAO токенов (исключаем BIO, SOL, WETH, ETH, USDC)
  SELECT DISTINCT 
    token_symbol
  FROM dao_pool_snapshots 
  WHERE 
    token_symbol NOT IN ('BIO', 'SOL', 'WETH', 'ETH', 'USDC')
    AND token_fdv_usd > 0
    AND created_at >= '2025-07-30T00:00:00Z'
),
dao_tokens_matrix AS (
  -- Создаем полную матрицу: каждый DAO токен на каждом чейне
  SELECT 
    d.token_symbol,
    n.network,
    -- Определяем ожидаемое название BIO пары
    CASE 
      WHEN n.network = 'solana' THEN 'BIO/' || d.token_symbol
      ELSE d.token_symbol || '/BIO'
    END as expected_pool_name
  FROM dao_tokens_base d
  CROSS JOIN (
    SELECT 'ethereum' as network 
    UNION SELECT 'base' as network 
    UNION SELECT 'solana' as network
  ) n
),
latest_token_metrics AS (
  -- 🔧 ИСПРАВЛЕНО: Получаем ПОСЛЕДНИЕ ВАЛИДНЫЕ метрики для каждого токена
  SELECT DISTINCT ON (token_symbol)
    token_symbol,
    token_fdv_usd as fdv_usd,
    COALESCE(token_mc_usd, token_fdv_usd) as real_mc_usd,
    token_price_usd,
    created_at as latest_update
  FROM dao_pool_snapshots 
  WHERE 
    token_symbol IN (SELECT token_symbol FROM dao_tokens_base)
    AND token_fdv_usd > 0  -- 🔧 ФИЛЬТРУЕМ ВАЛИДНЫЕ ДАННЫЕ НА УРОВНЕ CTE
    AND created_at >= '2025-07-30T00:00:00Z'
  ORDER BY token_symbol, created_at DESC
),
bio_price AS (
  -- Последняя цена BIO
  SELECT 
    token_price_usd as bio_price_usd
  FROM dao_pool_snapshots 
  WHERE 
    token_symbol = 'BIO' 
    AND token_price_usd > 0
    AND created_at >= '2025-07-30T00:00:00Z'
  ORDER BY created_at DESC 
  LIMIT 1
),
latest_bio_pairs AS (
  -- Последние данные о BIO парах для каждого токена и сети
  SELECT 
    CASE 
      WHEN token0_symbol = 'BIO' THEN token1_symbol
      WHEN token1_symbol = 'BIO' THEN token0_symbol
      ELSE NULL
    END as token_symbol,
    network,
    pool_name,
    pool_address,
    target_lp_value_usd,
    lp_gap_usd,
    tvl_usd,
    created_at as snapshot_timestamp,
    ROW_NUMBER() OVER (
      PARTITION BY 
        CASE 
          WHEN token0_symbol = 'BIO' THEN token1_symbol
          WHEN token1_symbol = 'BIO' THEN token0_symbol
        END,
        network 
      ORDER BY created_at DESC
    ) as rn
  FROM dao_pool_snapshots 
  WHERE 
    created_at >= '2025-07-30T00:00:00Z'
    AND (
      (token0_symbol = 'BIO' AND token1_symbol != 'BIO') OR
      (token1_symbol = 'BIO' AND token0_symbol != 'BIO')
    )
    AND pool_name NOT LIKE '%USDC%'
    AND pool_name NOT LIKE '%/USDC'
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
    AND pool_name NOT LIKE 'SPINE/USDC'
    AND pool_name NOT LIKE '%/WETH' 
    AND pool_name NOT LIKE '%/SOL'
    AND pool_name NOT LIKE 'WETH/%'
    AND pool_name NOT LIKE 'SOL/%'
),
aggregated_positions AS (
  -- Агрегируем позиции по pool_address и network
  SELECT 
    pool_address,
    network,
    SUM(position_value_usd) as total_position_value_usd,
    COUNT(DISTINCT position_mint) as unique_positions_count,
    MAX(created_at) as latest_position_update,
    ROW_NUMBER() OVER (PARTITION BY pool_address, network ORDER BY MAX(created_at) DESC) as rn
  FROM lp_position_snapshots 
  WHERE 
    created_at >= '2025-07-30T15:00:00Z'
    AND position_value_usd > 0
    AND (
      (token0_symbol = 'BIO' AND token1_symbol != 'BIO') OR
      (token1_symbol = 'BIO' AND token0_symbol != 'BIO')
    )
    AND pool_name NOT LIKE '%USDC%'
    AND pool_name NOT LIKE '%WETH%'
    AND pool_name NOT LIKE '%SOL%'
    AND pool_name NOT LIKE '%ETH%'
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
    AND pool_name NOT LIKE 'SPINE/USDC'
  GROUP BY pool_address, network
),
unified_data AS (
  -- Объединяем все данные
  SELECT 
    m.token_symbol,
    m.network,
    m.expected_pool_name,
    
    -- Метрики токена (FDV и РЕАЛЬНЫЕ MC из API!)
    COALESCE(tm.fdv_usd, 0) as token_fdv_usd,
    COALESCE(tm.real_mc_usd, 0) as token_mc_usd,
    COALESCE(tm.token_price_usd, 0) as token_price_usd,
    
    -- Цена BIO из базы
    bp.bio_price_usd,
    
    -- Целевые размеры пулов (1% от FDV и MC)
    COALESCE(tm.fdv_usd * 0.01, 0) as target_pool_size_fdv,
    COALESCE(tm.real_mc_usd * 0.01, 0) as target_pool_size_mc,
    
    -- Данные о существующей BIO паре
    COALESCE(bio.pool_name, m.expected_pool_name) as pool_name,
    COALESCE(bio.pool_address, '') as pool_address,
    COALESCE(bio.target_lp_value_usd, tm.fdv_usd * 0.01) as target_lp_value_usd,
    COALESCE(bio.lp_gap_usd, 0) as lp_gap_usd,
    COALESCE(bio.tvl_usd, 0) as tvl_usd,
    COALESCE(bio.snapshot_timestamp, tm.latest_update) as snapshot_timestamp,
    
    -- Данные о позициях
    COALESCE(pos.total_position_value_usd, 0) as our_position_value_usd,
    COALESCE(pos.unique_positions_count, 0) as positions_count,
    
    -- Флаги наличия данных
    CASE WHEN bio.token_symbol IS NOT NULL THEN true ELSE false END as has_bio_pair_data,
    CASE WHEN pos.pool_address IS NOT NULL THEN true ELSE false END as has_position_data
    
  FROM dao_tokens_matrix m
  CROSS JOIN bio_price bp
  LEFT JOIN latest_token_metrics tm ON (
    m.token_symbol = tm.token_symbol
  )
  LEFT JOIN latest_bio_pairs bio ON (
    m.token_symbol = bio.token_symbol 
    AND m.network = bio.network
    AND bio.rn = 1
  )
  LEFT JOIN aggregated_positions pos ON (
    bio.pool_address = pos.pool_address 
    AND bio.network = pos.network
    AND pos.rn = 1
  )
  -- 🔧 УБИРАЕМ ФИНАЛЬНЫЙ ФИЛЬТР - данные уже отфильтрованы в CTE
  -- WHERE tm.fdv_usd > 0  
)
SELECT 
  -- ПОРЯДОК КОЛОНОК КАК В CSV
  token_symbol as "Token",
  CASE 
    WHEN network = 'ethereum' THEN 'ETH'
    WHEN network = 'base' THEN 'BASE'  
    WHEN network = 'solana' THEN 'SOL'
  END as "Chain",
  
  CASE 
    WHEN our_position_value_usd >= target_lp_value_usd THEN 'Optimal Range'
    WHEN our_position_value_usd > 0 THEN 'Partial Support'
    ELSE 'No Support'
  END as "Status",
  
  -- Market Cap и FDV
  ROUND(token_mc_usd, 2) as "MC",
  ROUND(token_fdv_usd, 2) as "FDV",
  
  -- Цены
  ROUND(token_price_usd, 8) as "Price of token",
  ROUND(bio_price_usd, 4) as "Price of BIO",
  
  -- Целевые размеры пулов
  ROUND(target_pool_size_mc, 2) as "Target Pool Size $ (MC)",
  ROUND(target_pool_size_fdv, 2) as "Target Pool Size $ (FDV)",
  
  -- BIO количества
  ROUND(target_pool_size_fdv / (2 * bio_price_usd), 0) as "BIO w FDV",
  ROUND(token_fdv_usd / (token_price_usd * 2 * bio_price_usd), 0) as "DAO w FDV",
  ROUND(target_pool_size_mc / (2 * bio_price_usd), 0) as "BIO w MC", 
  ROUND(token_mc_usd / (token_price_usd * 2 * bio_price_usd), 0) as "DAO w MC",
  
  -- Наши позиции
  ROUND(our_position_value_usd, 2) as "Our positions $",
  
  snapshot_timestamp

FROM unified_data
ORDER BY token_fdv_usd DESC, network;
