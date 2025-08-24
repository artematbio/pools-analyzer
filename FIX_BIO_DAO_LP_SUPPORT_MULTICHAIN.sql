-- =====================================================
-- ИСПРАВЛЕНИЕ bio_dao_lp_support ДЛЯ МУЛЬТИЧЕЙН ПОЗИЦИЙ
-- =====================================================
-- 
-- ПРОБЛЕМЫ ИСПРАВЛЯЕМЫЕ:
-- ❌ Неправильное количество позиций (191 вместо 3-4)
-- ❌ Неправильные суммы (суммируются все снапшоты, а не последние)
-- ❌ Лишние колонки с подчеркиваниями
-- 
-- РЕШЕНИЕ:
-- ✅ Брать ПОСЛЕДНИЕ снапшоты каждой позиции (DISTINCT ON position_mint)
-- ✅ Включить ВСЕ сети (Solana, Ethereum, Base) 
-- ✅ Оставить только нужные колонки как в оригинальном представлении
-- =====================================================

-- Удаляем проблемное представление v2
DROP VIEW IF EXISTS bio_dao_lp_support_v2;

-- Заменяем оригинальное представление правильной логикой
DROP VIEW IF EXISTS bio_dao_lp_support;

CREATE VIEW bio_dao_lp_support AS
WITH latest_dao_snapshots AS (
    -- Последние снапшоты DAO пулов для всех сетей
    SELECT DISTINCT ON (pool_name, network) 
        pool_name,
        network,
        dex,
        token_symbol,
        token_address,
        tvl_usd,
        volume_24h_usd,
        token_fdv_usd,
        token_mc_usd,
        token_price_usd,
        bio_price_usd,
        our_position_value_usd,
        target_lp_value_usd,
        lp_gap_usd,
        price_change_24h_percent,
        price_change_7d_percent,
        tvl_change_7d_percent,
        is_bio_pair,
        snapshot_timestamp,
        created_at,
        fee_percent,
        target_fdv_percentage
    FROM dao_pool_snapshots
    ORDER BY pool_name, network, snapshot_timestamp DESC
),
latest_position_snapshots AS (
    -- ✅ КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: Берем ПОСЛЕДНИЙ снапшот каждой позиции
    SELECT DISTINCT ON (position_mint, network, pool_name) 
        position_mint,
        network,
        pool_id,
        pool_name,
        position_value_usd,
        fees_usd,
        created_at
    FROM lp_position_snapshots
    WHERE created_at >= CURRENT_DATE - INTERVAL '3 days'  -- Свежие данные
    ORDER BY position_mint, network, pool_name, created_at DESC
),
our_positions_aggregated AS (
    -- Агрегируем УНИКАЛЬНЫЕ позиции по пулам
    SELECT 
        pool_name,
        network,
        SUM(COALESCE(CAST(position_value_usd AS NUMERIC), 0)) as total_position_value,
        SUM(COALESCE(CAST(fees_usd AS NUMERIC), 0)) as total_fees,
        COUNT(position_mint) as actual_positions_count  -- Теперь считаем реальные позиции
    FROM latest_position_snapshots
    GROUP BY pool_name, network
)
SELECT 
    -- ✅ ОРИГИНАЛЬНЫЕ КОЛОНКИ (без подчеркиваний в отображении)
    d.pool_name,
    d.network,
    d.dex,
    d.token_symbol,
    d.token_address,
    d.tvl_usd,
    d.volume_24h_usd,
    d.token_fdv_usd,
    d.token_mc_usd,
    d.token_price_usd,
    d.bio_price_usd,
    
    -- ✅ ИСПРАВЛЕННЫЕ ПОЗИЦИИ: Берем агрегированные значения из актуальных снапшотов
    COALESCE(CAST(p.total_position_value AS NUMERIC), 0) as our_position_value_usd,
    
    d.target_lp_value_usd,
    d.lp_gap_usd,
    d.price_change_24h_percent,
    d.price_change_7d_percent,
    d.tvl_change_7d_percent,
    d.is_bio_pair,
    d.snapshot_timestamp,
    d.created_at,
    d.fee_percent,
    d.target_fdv_percentage,
    
    -- ✅ ДОПОЛНИТЕЛЬНЫЕ ПОЛЯ ДЛЯ АНАЛИЗА
    COALESCE(CAST(p.total_fees AS NUMERIC), 0) as our_fees_usd,
    COALESCE(p.actual_positions_count, 0) as our_positions_count

FROM latest_dao_snapshots d
LEFT JOIN our_positions_aggregated p ON (
    d.pool_name = p.pool_name 
    AND d.network = p.network
)
ORDER BY 
    d.network,
    COALESCE(CAST(p.total_position_value AS NUMERIC), 0) DESC,
    CAST(COALESCE(d.tvl_usd, 0) AS NUMERIC) DESC;

-- Комментарий
COMMENT ON VIEW bio_dao_lp_support IS 'Мультичейн представление BIO DAO LP поддержки. Использует последние снапшоты позиций для корректного подсчета количества и сумм позиций.';

-- =====================================================
-- ПРОВЕРОЧНЫЕ ЗАПРОСЫ
-- =====================================================

-- Проверяем количество позиций по BIO/WETH (должно быть 3-4, не 191):
-- SELECT 
--     pool_name,
--     network,
--     our_position_value_usd,
--     our_positions_count,
--     our_fees_usd
-- FROM bio_dao_lp_support 
-- WHERE pool_name LIKE '%BIO%' AND pool_name LIKE '%WETH%'
-- ORDER BY our_position_value_usd DESC;

-- Проверяем общую сортировку:
-- SELECT 
--     pool_name,
--     network,
--     our_position_value_usd,
--     our_positions_count
-- FROM bio_dao_lp_support 
-- WHERE our_position_value_usd > 0
-- ORDER BY our_position_value_usd DESC
-- LIMIT 10;
