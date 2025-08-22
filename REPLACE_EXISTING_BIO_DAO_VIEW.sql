-- =====================================================
-- ЗАМЕНА СУЩЕСТВУЮЩЕГО ПРЕДСТАВЛЕНИЯ bio_dao_lp_support
-- =====================================================
-- 
-- ЦЕЛЬ: Заменить текущее представление bio_dao_lp_support
-- чтобы колонка our positions стала сортируемой (NUMERIC)
-- 
-- ВАЖНО: Это заменит существующее представление!
-- =====================================================

-- Сначала удаляем старое представление
DROP VIEW IF EXISTS bio_dao_lp_support;

-- Создаем новое представление с тем же именем, но исправленной структурой
CREATE VIEW bio_dao_lp_support AS
WITH latest_dao_snapshots AS (
    -- Берем последние снапшоты DAO пулов
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
our_positions_summary AS (
    -- Агрегируем наши позиции по пулам
    SELECT 
        pool_name,
        network,
        SUM(COALESCE(CAST(position_value_usd AS NUMERIC), 0)) as total_position_value,
        SUM(COALESCE(CAST(fees_usd AS NUMERIC), 0)) as total_fees,
        COUNT(*) as positions_count,
        STRING_AGG(COALESCE(position_mint, ''), ', ') as position_details
    FROM lp_position_snapshots 
    WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY pool_name, network
)
SELECT 
    -- Основная информация
    d.pool_name,
    d.network,
    d.dex,
    d.token_symbol,
    d.token_address,
    
    -- Финансовые метрики
    CAST(COALESCE(d.tvl_usd, 0) AS NUMERIC) as tvl_usd,
    CAST(COALESCE(d.volume_24h_usd, 0) AS NUMERIC) as volume_24h_usd,
    CAST(COALESCE(d.token_fdv_usd, 0) AS NUMERIC) as token_fdv_usd,
    CAST(COALESCE(d.token_mc_usd, 0) AS NUMERIC) as token_mc_usd,
    CAST(COALESCE(d.token_price_usd, 0) AS NUMERIC) as token_price_usd,
    CAST(COALESCE(d.bio_price_usd, 0) AS NUMERIC) as bio_price_usd,
    
    -- ✅ ИСПРАВЛЕННАЯ КОЛОНКА: our_position_value_usd теперь NUMERIC для сортировки
    COALESCE(CAST(p.total_position_value AS NUMERIC), 0) as our_position_value_usd,
    
    -- Target и gap анализ
    CAST(COALESCE(d.target_lp_value_usd, 0) AS NUMERIC) as target_lp_value_usd,
    CAST(COALESCE(d.lp_gap_usd, 0) AS NUMERIC) as lp_gap_usd,
    
    -- Процентные изменения
    CAST(COALESCE(d.price_change_24h_percent, 0) AS NUMERIC) as price_change_24h_percent,
    CAST(COALESCE(d.price_change_7d_percent, 0) AS NUMERIC) as price_change_7d_percent,
    CAST(COALESCE(d.tvl_change_7d_percent, 0) AS NUMERIC) as tvl_change_7d_percent,
    
    -- Флаги
    COALESCE(d.is_bio_pair, false) as is_bio_pair,
    
    -- Дополнительные поля для совместимости
    CAST(COALESCE(d.fee_percent, 0) AS NUMERIC) as fee_percent,
    CAST(COALESCE(d.target_fdv_percentage, 0) AS NUMERIC) as target_fdv_percentage,
    
    -- Расчетные поля
    CASE 
        WHEN COALESCE(d.target_lp_value_usd, 0) > 0 THEN 
            ROUND((COALESCE(p.total_position_value, 0) / CAST(d.target_lp_value_usd AS NUMERIC)) * 100, 2)
        ELSE 0 
    END as lp_coverage_percent,
    
    CASE 
        WHEN COALESCE(p.total_position_value, 0) > 0 THEN true 
        ELSE false 
    END as has_our_position,
    
    -- Дополнительные метрики позиций
    COALESCE(CAST(p.total_fees AS NUMERIC), 0) as our_fees_usd,
    COALESCE(p.positions_count, 0) as our_positions_count,
    
    -- Временные метки
    d.snapshot_timestamp,
    d.created_at,
    
    -- Детали позиций
    p.position_details

FROM latest_dao_snapshots d
LEFT JOIN our_positions_summary p ON (
    d.pool_name = p.pool_name 
    AND d.network = p.network
)
ORDER BY 
    d.network,
    COALESCE(CAST(p.total_position_value AS NUMERIC), 0) DESC,
    CAST(COALESCE(d.tvl_usd, 0) AS NUMERIC) DESC;

-- Добавляем комментарий
COMMENT ON VIEW bio_dao_lp_support IS 'Обновленное представление BIO DAO LP поддержки. Колонка our_position_value_usd теперь NUMERIC для правильной сортировки по сумме в долларах.';

-- =====================================================
-- ПРОВЕРОЧНЫЙ ЗАПРОС
-- =====================================================

-- Проверяем, что сортировка теперь работает правильно:
-- SELECT 
--     pool_name,
--     network,
--     our_position_value_usd,
--     target_lp_value_usd,
--     lp_coverage_percent
-- FROM bio_dao_lp_support 
-- ORDER BY our_position_value_usd DESC
-- LIMIT 10;

