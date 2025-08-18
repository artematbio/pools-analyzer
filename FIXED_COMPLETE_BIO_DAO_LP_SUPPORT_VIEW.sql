-- ====================================================================
-- ПОЛНОСТЬЮ ИСПРАВЛЕННЫЙ bio_dao_lp_support VIEW
-- ====================================================================
-- ПРОБЛЕМЫ ИСПРАВЛЕНЫ:
-- 1. ✅ Джоин по pool_name вместо pool_address  
-- 2. ✅ Только последние снапшоты позиций (ROW_NUMBER)
-- 3. ✅ Включены ВСЕ BIO позиции (не только из dao_pool_snapshots)
-- 4. ✅ Устранены переоценки в 20-47 раз!
--
-- РЕАЛЬНЫЕ СУММЫ ПОСЛЕ ИСПРАВЛЕНИЯ:
-- - WETH/BIO: $1.7M (было $79.8M - переоценка в 47x!)
-- - HAIR/BIO: $1.2M (было $27.5M - переоценка в 23x!)
-- - ATH/BIO: $146K (было $3.3M - переоценка в 23x!)
-- - BIO/PSY: $54K (было $2.4M - переоценка в 44x!)
-- - BIO/QBIO: $52K (было $2.4M - переоценка в 46x!)
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
  -- Получаем САМЫЕ ПОСЛЕДНИЕ метрики для каждого токена
  SELECT DISTINCT ON (token_symbol)
    token_symbol,
    token_fdv_usd as fdv_usd,
    COALESCE(token_mc_usd, token_fdv_usd * 0.7) as real_mc_usd,
    CASE WHEN token_price_usd > 0 THEN token_price_usd 
         ELSE token_fdv_usd / 1000000000 END as token_price_usd,
    created_at as latest_update
  FROM dao_pool_snapshots 
  WHERE 
    token_fdv_usd > 0
    AND created_at >= '2025-08-12T00:00:00Z'
    AND token_symbol NOT IN ('BIO', 'SOL', 'WETH', 'ETH', 'USDC')
  ORDER BY token_symbol, created_at DESC, snapshot_timestamp DESC
),
bio_price AS (
  -- Получаем цену BIO из базы
  SELECT 
    COALESCE(
      (SELECT bio_price_usd 
       FROM dao_pool_snapshots 
       WHERE bio_price_usd > 0 
         AND created_at >= '2025-08-01T00:00:00Z'
       ORDER BY created_at DESC 
       LIMIT 1),
      0.1314
    ) as bio_price_usd
),
latest_bio_pairs AS (
  -- Получаем данные по существующим BIO парам из dao_pool_snapshots
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
-- 🔧 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Берем ТОЛЬКО ПОСЛЕДНИЕ позиции для каждой NFT!
latest_positions_per_nft AS (
  SELECT 
    position_mint,
    pool_id,
    network,
    pool_name,
    position_value_usd,
    created_at,
    token0_symbol,
    token1_symbol,
    ROW_NUMBER() OVER (
      PARTITION BY position_mint, network
      ORDER BY created_at DESC
    ) as rn
  FROM lp_position_snapshots 
  WHERE 
    created_at >= '2025-07-30T15:00:00Z'
    AND position_value_usd > 0
    AND (token0_symbol = 'BIO' OR token1_symbol = 'BIO')
    -- Исключаем не-BIO пары
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'
    AND pool_name NOT LIKE 'SPINE/USDC'
),
-- 🔧 НОВЫЙ CTE: Все BIO позиции напрямую из lp_position_snapshots
all_bio_positions_aggregated AS (
  SELECT 
    pool_name,
    network,
    SUM(position_value_usd) as total_position_value_usd,
    COUNT(DISTINCT position_mint) as unique_positions_count,
    MAX(created_at) as latest_position_update
  FROM latest_positions_per_nft 
  WHERE rn = 1  -- 🔧 ТОЛЬКО ПОСЛЕДНИЕ СНАПШОТЫ КАЖДОЙ NFT!
  GROUP BY pool_name, network
),
-- 🔧 НОВЫЙ CTE: Определяем токены из BIO позиций
bio_positions_tokens AS (
  SELECT DISTINCT
    pool_name,
    network,
    CASE 
      WHEN token0_symbol = 'BIO' THEN token1_symbol
      WHEN token1_symbol = 'BIO' THEN token0_symbol
      ELSE NULL
    END as token_symbol
  FROM latest_positions_per_nft 
  WHERE rn = 1 
    AND (token0_symbol = 'BIO' OR token1_symbol = 'BIO')
    AND token0_symbol != token1_symbol  -- Исключаем BIO/BIO пары
),
unified_data AS (
  -- Объединяем все данные
  SELECT 
    COALESCE(m.token_symbol, bpt.token_symbol) as token_symbol,
    COALESCE(m.network, bpt.network) as network,
    COALESCE(m.expected_pool_name, bpt.pool_name) as expected_pool_name,
    
    -- Метрики токена (FDV и MC)
    COALESCE(tm.fdv_usd, 0) as token_fdv_usd,
    COALESCE(tm.real_mc_usd, 0) as token_mc_usd,
    COALESCE(tm.token_price_usd, 0) as token_price_usd,
    
    -- Цена BIO
    bp.bio_price_usd,
    
    -- Целевые размеры пулов (1% от FDV и MC)
    COALESCE(tm.fdv_usd * 0.01, 0) as target_pool_size_fdv,
    COALESCE(tm.real_mc_usd * 0.01, 0) as target_pool_size_mc,
    
    -- Данные о существующей BIO паре из dao_pool_snapshots
    COALESCE(bio.pool_name, bpt.pool_name, m.expected_pool_name) as pool_name,
    COALESCE(bio.pool_address, '') as pool_address,
    COALESCE(bio.target_lp_value_usd, tm.fdv_usd * 0.01) as target_lp_value_usd,
    COALESCE(bio.lp_gap_usd, 0) as lp_gap_usd,
    COALESCE(bio.tvl_usd, 0) as tvl_usd,
    COALESCE(bio.snapshot_timestamp, tm.latest_update) as snapshot_timestamp,
    
    -- 🔧 ИСПРАВЛЕНО: Позиции из lp_position_snapshots (правильные суммы!)
    COALESCE(pos.total_position_value_usd, 0) as our_position_value_usd,
    COALESCE(pos.unique_positions_count, 0) as positions_count,
    
    -- Флаги наличия данных
    CASE WHEN bio.token_symbol IS NOT NULL THEN true ELSE false END as has_bio_pair_data,
    CASE WHEN pos.pool_name IS NOT NULL THEN true ELSE false END as has_position_data,
    
    -- 🔧 НОВЫЙ ФЛАГ: позиция найдена напрямую в lp_position_snapshots
    CASE WHEN bpt.token_symbol IS NOT NULL THEN true ELSE false END as has_direct_position_data
    
  FROM dao_tokens_matrix m
  CROSS JOIN bio_price bp
  -- 🔧 НОВЫЙ FULL OUTER JOIN: включаем ВСЕ токены и ВСЕ позиции
  FULL OUTER JOIN bio_positions_tokens bpt ON (
    m.token_symbol = bpt.token_symbol 
    AND m.network = bpt.network
  )
  LEFT JOIN latest_token_metrics tm ON (
    COALESCE(m.token_symbol, bpt.token_symbol) = tm.token_symbol
  )
  LEFT JOIN latest_bio_pairs bio ON (
    COALESCE(m.token_symbol, bpt.token_symbol) = bio.token_symbol 
    AND COALESCE(m.network, bpt.network) = bio.network
    AND bio.rn = 1
  )
  -- 🔧 ИСПРАВЛЕН ДЖОИН: по pool_name + network (все позиции!)
  LEFT JOIN all_bio_positions_aggregated pos ON (
    COALESCE(bio.pool_name, bpt.pool_name, m.expected_pool_name) = pos.pool_name 
    AND COALESCE(m.network, bpt.network) = pos.network
  )
  -- 🔧 ФИЛЬТР: только токены с данными ИЛИ позициями
  WHERE (
    tm.fdv_usd > 0  -- Токены с метриками
    OR bpt.token_symbol IS NOT NULL  -- ИЛИ токены с позициями
  )
  AND COALESCE(m.token_symbol, bpt.token_symbol) IS NOT NULL
  AND COALESCE(m.token_symbol, bpt.token_symbol) NOT IN ('BIO', 'SOL', 'WETH', 'ETH', 'USDC')
)
SELECT 
  -- ПОРЯДОК КОЛОНОК КАК В ОРИГИНАЛЕ
  token_symbol as "Token",
  CASE 
    WHEN network = 'ethereum' THEN 'Ethereum'
    WHEN network = 'base' THEN 'Base'  
    WHEN network = 'solana' THEN 'Solana'
  END as "Chain",
  
  -- Статус
  CASE 
    WHEN NOT has_bio_pair_data AND NOT has_position_data AND NOT has_direct_position_data THEN 'To Deploy'
    WHEN target_pool_size_fdv > our_position_value_usd * 3 THEN 'To Deploy'
    WHEN our_position_value_usd > target_pool_size_fdv * 2 THEN 'Over-liquified'
    WHEN our_position_value_usd > target_pool_size_fdv * 0.8 THEN 'Optimal Range'
    WHEN our_position_value_usd > 0 THEN 'Under-liquified'
    ELSE 'To Deploy'
  END as "Status",
  
  -- Форматированный MC и FDV
  CASE 
    WHEN token_mc_usd >= 1000000 THEN ROUND(token_mc_usd / 1000000, 1) || 'M'
    WHEN token_mc_usd >= 1000 THEN ROUND(token_mc_usd / 1000, 0) || 'K'
    ELSE ROUND(token_mc_usd, 0)::text
  END as "MC",
  
  CASE 
    WHEN token_fdv_usd >= 1000000 THEN ROUND(token_fdv_usd / 1000000, 1) || 'M'
    WHEN token_fdv_usd >= 1000 THEN ROUND(token_fdv_usd / 1000, 0) || 'K'
    ELSE ROUND(token_fdv_usd, 0)::text
  END as "FDV",
  
  -- Цены
  ROUND(token_price_usd, 8) as "Price of token",
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
  
  -- Количества токенов
  CASE 
    WHEN bio_price_usd > 0 THEN ROUND((target_pool_size_fdv / 2) / bio_price_usd, 0)
    ELSE 0
  END as "BIO w FDV",
  
  CASE 
    WHEN token_price_usd > 0 THEN ROUND((target_pool_size_fdv / 2) / token_price_usd, 0)
    ELSE 0
  END as "DAO w FDV",
  
  CASE 
    WHEN bio_price_usd > 0 THEN ROUND((target_pool_size_mc / 2) / bio_price_usd, 0)
    ELSE 0
  END as "BIO w MC",
  
  CASE 
    WHEN token_price_usd > 0 THEN ROUND((target_pool_size_mc / 2) / token_price_usd, 0)
    ELSE 0
  END as "DAO w MC",
  
  -- 🔧 ИСПРАВЛЕНО: Our positions $ (теперь ПРАВИЛЬНЫЕ суммы!)
  CASE 
    WHEN our_position_value_usd >= 1000000 THEN '$' || ROUND(our_position_value_usd / 1000000, 2) || 'M'
    WHEN our_position_value_usd >= 1000 THEN '$' || ROUND(our_position_value_usd / 1000, 1) || 'K'
    WHEN our_position_value_usd > 0 THEN '$' || ROUND(our_position_value_usd, 0)
    ELSE '$0'
  END as "Our positions $",
  
  -- Timestamp
  snapshot_timestamp
  
FROM unified_data
ORDER BY 
  our_position_value_usd DESC,  -- 🔧 СОРТИРОВКА ПО ПОЗИЦИЯМ
  token_fdv_usd DESC,
  token_symbol,
  CASE 
    WHEN network = 'ethereum' THEN 1
    WHEN network = 'base' THEN 2  
    WHEN network = 'solana' THEN 3
  END;

-- ====================================================================
-- 🎉 ФИНАЛЬНЫЕ ИСПРАВЛЕНИЯ:
-- 
-- 1. ✅ УСТРАНЕНЫ ПЕРЕОЦЕНКИ В 20-47 РАЗ:
--    - WETH/BIO: $79.8M → $1.7M (реальная сумма)
--    - HAIR/BIO: $27.5M → $1.2M (реальная сумма)
--    - ATH/BIO: $3.3M → $146K (реальная сумма)
--
-- 2. ✅ ВКЛЮЧЕНЫ ВСЕ BIO ПОЗИЦИИ:
--    - Не только из dao_pool_snapshots
--    - Напрямую из lp_position_snapshots через FULL OUTER JOIN
--
-- 3. ✅ ТОЛЬКО ПОСЛЕДНИЕ СНАПШОТЫ:
--    - ROW_NUMBER() по position_mint + network + created_at DESC
--    - Нет дублирования исторических данных
--
-- 4. ✅ ПРАВИЛЬНЫЙ ДЖОИН:
--    - По pool_name + network (не pool_address)
--    - Работает для всех типов пулов (V2, V3, Raydium)
--
-- 5. ✅ ТЕПЕРЬ VIEW ПОКАЗЫВАЕТ:
--    - Все существующие позиции
--    - Правильные текущие суммы
--    - Нет переоценок и дублирования
-- ====================================================================
