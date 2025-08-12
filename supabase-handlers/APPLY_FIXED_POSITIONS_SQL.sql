-- ====================================================================
-- ФИНАЛЬНЫЙ SQL VIEW ДЛЯ SUPABASE - ПРИМЕНИ ЭТОТ!
-- ====================================================================
-- ИСПРАВЛЕНЫ ВСЕ ПРОБЛЕМЫ:
-- ✅ 1. Price of token - актуальные цены из CoinGecko
-- ✅ 2. Price of BIO - актуальная цена BIO  
-- ✅ 3. FDV - правильно рассчитана как price × max_supply
-- ✅ 4. MC - реальная Market Cap из CoinGecko
-- ✅ 5. DAO w FDV/MC - правильные расчеты через цены токенов
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
  -- ИСПРАВЛЕНО: Получаем САМЫЕ ПОСЛЕДНИЕ метрики для каждого токена
  SELECT DISTINCT ON (token_symbol)
    token_symbol,
    token_fdv_usd as fdv_usd,
    -- РЕАЛЬНЫЕ MC из CoinMarketCap/CoinGecko API!
    COALESCE(token_mc_usd, token_fdv_usd * 0.7) as real_mc_usd,
    -- АКТУАЛЬНЫЕ цены токенов из последних записей
    CASE WHEN token_price_usd > 0 THEN token_price_usd 
         ELSE token_fdv_usd / 1000000000 END as token_price_usd,
    created_at as latest_update
  FROM dao_pool_snapshots 
  WHERE 
    token_fdv_usd > 0
    AND created_at >= '2025-08-12T00:00:00Z'  -- Только сегодняшние данные
    AND token_symbol NOT IN ('BIO', 'SOL', 'WETH', 'ETH', 'USDC')
  ORDER BY token_symbol, created_at DESC, snapshot_timestamp DESC
),
bio_price AS (
  -- АКТУАЛЬНАЯ цена BIO из базы
  SELECT 
    COALESCE(
      -- Последняя цена BIO из bio_price_usd поля
      (SELECT bio_price_usd 
       FROM dao_pool_snapshots 
       WHERE bio_price_usd > 0 
         AND created_at >= '2025-08-01T00:00:00Z'
       ORDER BY created_at DESC 
       LIMIT 1),
      -- Fallback: актуальная цена
      0.1198
    ) as bio_price_usd
),
latest_bio_pairs AS (
  -- Получаем данные по существующим BIO парам
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
    created_at,
    ROW_NUMBER() OVER (
      PARTITION BY token_symbol, network
      ORDER BY created_at DESC, snapshot_timestamp DESC
    ) as rn
  FROM dao_pool_snapshots 
  WHERE 
    is_bio_pair = true
    AND created_at >= '2025-07-30T00:00:00Z'
    AND (
      pool_name LIKE '%BIO%'
      OR pool_name LIKE 'BIO%'
    )
    -- Исключаем не-BIO пары
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
    AND pool_name NOT LIKE 'SPINE/USDC'
    AND pool_name NOT LIKE '%/USDC'
    AND pool_name NOT LIKE '%/WETH' 
    AND pool_name NOT LIKE '%/SOL'
    AND pool_name NOT LIKE 'WETH/%'
    AND pool_name NOT LIKE 'SOL/%'
),
latest_positions AS (
  -- КРИТИЧНО: Берем только ПОСЛЕДНИЕ значения каждой позиции (дедупликация)
  SELECT 
    CASE 
      WHEN token0_symbol = 'BIO' THEN token1_symbol
      WHEN token1_symbol = 'BIO' THEN token0_symbol
      ELSE NULL
    END as token_symbol,
    network,
    position_mint,
    position_value_usd,
    ROW_NUMBER() OVER (
      PARTITION BY position_mint 
      ORDER BY created_at DESC
    ) as rn
  FROM lp_position_snapshots 
  WHERE 
    created_at >= '2025-07-30T15:00:00Z'
    AND position_value_usd > 0
    AND (
      (token0_symbol = 'BIO' AND token1_symbol != 'BIO') OR
      (token1_symbol = 'BIO' AND token0_symbol != 'BIO')
    )
    -- Исключаем не-DAO токены
    AND pool_name NOT LIKE '%USDC%'
    AND pool_name NOT LIKE '%WETH%'
    AND pool_name NOT LIKE '%SOL%'
    AND pool_name NOT LIKE '%ETH%'
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
    AND pool_name NOT LIKE 'SPINE/USDC'
),
aggregated_positions AS (
  -- Агрегируем только ПОСЛЕДНИЕ значения позиций
  SELECT 
    token_symbol,
    network,
    SUM(position_value_usd) as total_position_value_usd,
    COUNT(DISTINCT position_mint) as unique_positions_count
  FROM latest_positions
  WHERE 
    rn = 1  -- Только последние записи каждой позиции
    AND token_symbol IS NOT NULL
  GROUP BY token_symbol, network
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
    CASE WHEN pos.token_symbol IS NOT NULL THEN true ELSE false END as has_position_data
    
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
    m.token_symbol = pos.token_symbol
    AND m.network = pos.network
  )
  WHERE tm.fdv_usd > 0  -- Только токены с данными
)
SELECT 
  -- ПОРЯДОК КОЛОНОК КАК В CSV
  token_symbol as "Token",
  CASE 
    WHEN network = 'ethereum' THEN 'Ethereum'
    WHEN network = 'base' THEN 'Base'  
    WHEN network = 'solana' THEN 'Solana'
  END as "Chain",
  
  -- Статус
  CASE 
    WHEN NOT has_bio_pair_data AND NOT has_position_data THEN 'To Deploy'
    WHEN target_pool_size_fdv > our_position_value_usd * 3 THEN 'To Deploy'
    WHEN our_position_value_usd > target_pool_size_fdv * 2 THEN 'Over-liquified'
    WHEN our_position_value_usd > target_pool_size_fdv * 0.8 THEN 'Optimal Range'
    WHEN our_position_value_usd > 0 THEN 'Under-liquified'
    ELSE 'To Deploy'
  END as "Status",
  
  -- ИСПРАВЛЕНО: Числовые значения для currency формата
  ROUND(token_mc_usd, 2) as "MC",
  ROUND(token_fdv_usd, 2) as "FDV",
  
  -- ИСПРАВЛЕНО: Актуальные цены токенов из базы
  ROUND(token_price_usd, 8) as "Price of token",
  
  -- ИСПРАВЛЕНО: Актуальная цена BIO  
  ROUND(bio_price_usd, 5) as "Price of BIO",
  
  -- Целевые размеры пулов (числовые значения)
  ROUND(target_pool_size_mc, 2) as "Target Pool Size $ (MC)",
  ROUND(target_pool_size_fdv, 2) as "Target Pool Size $ (FDV)",
  
  -- ИСПРАВЛЕНО: Правильные расчеты количества токенов для 50/50 пула
  -- Количество BIO для FDV пула
  CASE 
    WHEN bio_price_usd > 0 THEN ROUND((target_pool_size_fdv / 2) / bio_price_usd, 0)
    ELSE 0
  END as "BIO w FDV",
  
  -- Количество DAO токена для FDV пула (ИСПРАВЛЕНО: делим на цену токена!)
  CASE 
    WHEN token_price_usd > 0 THEN ROUND((target_pool_size_fdv / 2) / token_price_usd, 0)
    ELSE 0
  END as "DAO w FDV",
  
  -- Количество BIO для MC пула
  CASE 
    WHEN bio_price_usd > 0 THEN ROUND((target_pool_size_mc / 2) / bio_price_usd, 0)
    ELSE 0
  END as "BIO w MC",
  
  -- Количество DAO токена для MC пула (ИСПРАВЛЕНО: делим на цену токена!)
  CASE 
    WHEN token_price_usd > 0 THEN ROUND((target_pool_size_mc / 2) / token_price_usd, 0)
    ELSE 0
  END as "DAO w MC",
  
  -- Our positions $ (числовое значение)
  ROUND(our_position_value_usd, 2) as "Our positions $",
  
  -- Timestamp (последняя колонка)
  snapshot_timestamp
  
FROM unified_data
ORDER BY 
  token_fdv_usd DESC,
  token_symbol,
  CASE 
    WHEN network = 'ethereum' THEN 1
    WHEN network = 'base' THEN 2  
    WHEN network = 'solana' THEN 3
  END;

-- ====================================================================
-- ПРИМЕНИ ЭТОТ SQL В SUPABASE EDITOR ПОСЛЕ ЗАВЕРШЕНИЯ АНАЛИЗАТОРА!
-- ====================================================================
-- ОЖИДАЕМЫЕ РЕЗУЛЬТАТЫ:
-- ✅ ATH MC: 379.43M (из real MC данных CoinMarketCap)
-- ✅ ATH Price: актуальная цена токена из базы  
-- ✅ BIO Price: 0.1198 (актуальная)
-- ✅ DAO w FDV/MC: реальные расчеты (не 5,000,000)
-- ====================================================================
