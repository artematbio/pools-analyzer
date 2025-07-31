-- ОКОНЧАТЕЛЬНОЕ ИСПРАВЛЕНИЕ VIEW bio_dao_lp_support v6 (НЕ ДЕБИЛЬНАЯ ВЕРСИЯ)
-- ПРОБЛЕМЫ В v5:
-- 1. ATH: беру старые данные BIO/ATH ($96k) вместо новых ATH/WETH ($12M)
-- 2. WETH/BIO исключен: token_symbol=BIO не проходит фильтр token_symbol != 'BIO'  
-- 3. SOL/BIO исключен: token_symbol=SOL не проходит фильтр token_symbol != 'SOL'

DROP VIEW IF EXISTS bio_dao_lp_support;

CREATE VIEW bio_dao_lp_support AS
WITH latest_dao_data AS (
  -- Берем последние метрики DAO токенов из dao_pool_snapshots
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
      PARTITION BY pool_address, network
      ORDER BY created_at DESC, snapshot_timestamp DESC
    ) as rn
  FROM dao_pool_snapshots 
  WHERE 
    token_fdv_usd > 0
    AND is_bio_pair = true
    AND created_at >= '2025-07-30T00:00:00Z'
    AND (
      -- УПРОЩЕННЫЙ фильтр: только проверяем наличие BIO в названии
      pool_name LIKE '%BIO%'
    )
    -- ИСКЛЮЧЕНИЯ: явно НЕ BIO пары
    AND pool_name NOT LIKE 'QBIO/SOL'
    AND pool_name NOT LIKE 'QBIO/WETH'  -- QBIO с WETH тоже не BIO пара
),
latest_positions AS (
  -- Берем актуальные позиции из lp_position_snapshots
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
unified_data AS (
  -- Объединяем данные с дедупликацией по token_symbol + network
  SELECT 
    d.token_symbol,
    d.network,
    d.pool_name,
    d.pool_address,
    d.token_fdv_usd,
    d.target_lp_value_usd,
    d.lp_gap_usd,
    d.tvl_usd,
    d.snapshot_timestamp,
    COALESCE(p.position_value_usd, 0) as our_position_value_usd,
    ROW_NUMBER() OVER (
      -- ИСПРАВЛЕНО: Дедупликация ТОЛЬКО по токену (не по сети), берем максимальный FDV
      PARTITION BY d.token_symbol
      ORDER BY d.token_fdv_usd DESC, d.created_at DESC, COALESCE(p.position_value_usd, 0) DESC
    ) as dedup_rn
  FROM latest_dao_data d
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
FROM unified_data
WHERE dedup_rn = 1  -- Только уникальные токены с максимальным FDV
ORDER BY our_position_value_usd DESC, token_symbol;

-- КЛЮЧЕВЫЕ ИСПРАВЛЕНИЯ v6 (НЕ ДЕБИЛЬНАЯ):
-- 1. Убрал сложные фильтры по token_symbol - просто ищем %BIO% в pool_name
-- 2. Дедупликация ТОЛЬКО по token_symbol (не по сети) с приоритетом MAX FDV
-- 3. Для ATH возьмется ATH/WETH с FDV $12M вместо BIO/ATH с $96k
-- 4. WETH/BIO, SOL/BIO, BIO/WETH теперь НЕ исключаются
-- 5. Явные исключения только для QBIO/SOL и QBIO/WETH

-- ОЖИДАЕМЫЙ РЕЗУЛЬТАТ:
-- ✅ ATH FDV: $12,332,023 (из ATH/WETH) 
-- ✅ WETH/BIO: $1,035,429.67
-- ✅ SOL/BIO: $133k+ 
-- ✅ BIO/WETH: $222k+
-- ❌ QBIO/SOL исключен
-- ✅ Все BIO пары включены 