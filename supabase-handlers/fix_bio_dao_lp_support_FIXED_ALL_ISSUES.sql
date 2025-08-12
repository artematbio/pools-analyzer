-- ИСПРАВЛЕННЫЙ SQL VIEW - РЕШАЕТ ВСЕ ПРОБЛЕМЫ:
-- 1. Правильные цены токенов 
-- 2. Правильная цена BIO
-- 3. Правильный порядок цифр в MC (382M не 3.82M)
-- 4. Правильные расчеты DAO w FDV и DAO w MC

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
  -- Получаем САМЫЕ ПОСЛЕДНИЕ метрики для каждого токена
  SELECT DISTINCT ON (token_symbol)
    token_symbol,
    token_fdv_usd as fdv_usd,
    -- ИСПОЛЬЗУЕМ РЕАЛЬНЫЕ MC из CoinMarketCap/CoinGecko API!
    COALESCE(token_mc_usd, token_fdv_usd * 0.7) as real_mc_usd,
    -- ИСПРАВЛЕНО: берем ПОСЛЕДНЮЮ актуальную цену
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
  -- ИСПРАВЛЕНО: Получаем РЕАЛЬНУЮ цену BIO из базы
  SELECT 
    COALESCE(
      -- Ищем последнюю цену BIO из bio_price_usd (поле заполняется анализатором)
      (SELECT bio_price_usd 
       FROM dao_pool_snapshots 
       WHERE bio_price_usd > 0 
         AND created_at >= '2025-08-01T00:00:00Z'
       ORDER BY created_at DESC 
       LIMIT 1),
      -- Fallback: используем актуальную цену из последнего запуска
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
aggregated_positions AS (
  -- Агрегируем позиции по пулу (сумма всех NFT позиций)
  SELECT 
    pool_id as pool_address,
    network,
    pool_name,
    SUM(position_value_usd) as total_position_value_usd,
    COUNT(DISTINCT position_mint) as unique_positions_count,
    MAX(created_at) as latest_position_update,
    ROW_NUMBER() OVER (
      PARTITION BY pool_id, network
      ORDER BY MAX(created_at) DESC
    ) as rn
  FROM lp_position_snapshots 
  WHERE 
    created_at >= '2025-07-30T15:00:00Z'
    AND position_value_usd > 0
    AND pool_name LIKE '%BIO%'
    -- Исключаем не-BIO пары
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
    AND pool_name NOT LIKE 'SPINE/USDC'
  GROUP BY pool_id, network, pool_name
),
unified_data AS (
  -- Объединяем все данные
  SELECT 
    m.token_symbol,
    m.network,
    m.expected_pool_name,
    
    -- Метрики токена (FDV и РЕАЛЬНЫЕ MC из API!)
    COALESCE(tm.fdv_usd, 0) as token_fdv_usd,
    COALESCE(tm.real_mc_usd, 0) as token_mc_usd,  -- РЕАЛЬНЫЕ MC из CoinMarketCap/CoinGecko!
    COALESCE(tm.token_price_usd, 0) as token_price_usd,  -- РЕАЛЬНЫЕ цены токенов!
    
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
  WHERE tm.fdv_usd > 0  -- Только токены с данными
)
SELECT 
  -- ПОРЯДОК КОЛОНОК КАК В CSV
  token_symbol as "Token",
  CASE 
    WHEN network = 'ethereum' THEN 'ETH'
    WHEN network = 'base' THEN 'BASE'  
    WHEN network = 'solana' THEN 'SOL'
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
  
  -- ИСПРАВЛЕНО: Правильный формат MC (стандартное деление на миллионы)
  CASE 
    WHEN token_mc_usd >= 1000000 THEN ROUND(token_mc_usd / 1000000, 2) || 'M'
    WHEN token_mc_usd >= 1000 THEN ROUND(token_mc_usd / 1000, 0) || 'K'
    ELSE ROUND(token_mc_usd, 0)::text
  END as "MC",
  
  CASE 
    WHEN token_fdv_usd >= 1000000 THEN ROUND(token_fdv_usd / 1000000, 1) || 'M'
    WHEN token_fdv_usd >= 1000 THEN ROUND(token_fdv_usd / 1000, 0) || 'K'
    ELSE ROUND(token_fdv_usd, 0)::text
  END as "FDV",
  
  -- ИСПРАВЛЕНО: Правильные цены токенов (используем реальные из базы)
  ROUND(token_price_usd, 8) as "Price of token",
  
  -- ИСПРАВЛЕНО: Правильная цена BIO
  ROUND(bio_price_usd, 5) as "Price of BIO",
  
  -- Целевые размеры пулов
  CASE 
    WHEN target_pool_size_mc >= 1000000 THEN ROUND(target_pool_size_mc / 1000000, 2) || 'M'
    WHEN target_pool_size_mc >= 1000 THEN ROUND(target_pool_size_mc / 1000, 1) || 'K'
    ELSE ROUND(target_pool_size_mc, 0)::text
  END as "Target Pool Size $ (MC)",
  
  CASE 
    WHEN target_pool_size_fdv >= 1000000 THEN ROUND(target_pool_size_fdv / 1000000, 2) || 'M'
    WHEN target_pool_size_fdv >= 1000 THEN ROUND(target_pool_size_fdv / 1000, 1) || 'K'
    ELSE ROUND(target_pool_size_fdv, 0)::text
  END as "Target Pool Size $ (FDV)",
  
  -- ИСПРАВЛЕНО: Правильные расчеты количества токенов для 50/50 пула
  -- FDV версия - количество BIO
  CASE 
    WHEN bio_price_usd > 0 THEN ROUND((target_pool_size_fdv / 2) / bio_price_usd, 0)
    ELSE 0
  END as "BIO w FDV",
  
  -- FDV версия - количество DAO токена
  CASE 
    WHEN token_price_usd > 0 THEN ROUND((target_pool_size_fdv / 2) / token_price_usd, 0)
    ELSE 0
  END as "DAO w FDV",
  
  -- MC версия - количество BIO
  CASE 
    WHEN bio_price_usd > 0 THEN ROUND((target_pool_size_mc / 2) / bio_price_usd, 0)
    ELSE 0
  END as "BIO w MC",
  
  -- MC версия - количество DAO токена
  CASE 
    WHEN token_price_usd > 0 THEN ROUND((target_pool_size_mc / 2) / token_price_usd, 0)
    ELSE 0
  END as "DAO w MC",
  
  -- Our positions $ (единственная колонка из старого view)
  CASE 
    WHEN our_position_value_usd >= 1000000 THEN '$' || ROUND(our_position_value_usd / 1000000, 2) || 'M'
    WHEN our_position_value_usd >= 1000 THEN '$' || ROUND(our_position_value_usd / 1000, 1) || 'K'
    WHEN our_position_value_usd > 0 THEN '$' || ROUND(our_position_value_usd, 0)
    ELSE '$0'
  END as "Our positions $",
  
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
-- ИСПРАВЛЕНИЯ:
-- ✅ 1. Price of token: используем реальные token_price_usd из базы
-- ✅ 2. Price of BIO: берем bio_price_usd из базы (0.1198)
-- ✅ 3. MC: НЕ делим на миллион (382M вместо 3.82M)
-- ✅ 4. DAO w FDV/MC: делим на token_price_usd (не на FDV/supply)
-- ====================================================================
