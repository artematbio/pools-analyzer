-- =====================================================
-- ФИНАЛЬНАЯ ВЕРСИЯ: КОЛОНКА "OUR POSITIONS" ДЛЯ СОРТИРОВКИ
-- =====================================================
-- 
-- ИСПРАВЛЕНИЯ НА ОСНОВЕ РЕАЛЬНОЙ СТРУКТУРЫ ТАБЛИЦ:
-- ✅ dao_pool_snapshots: НЕТ pool_address, есть pool_name
-- ✅ lp_position_snapshots: есть pool_id, pool_name, НЕТ pool_address
-- ✅ JOIN по pool_name + network (основной ключ связи)
-- ✅ Все поля проверены по реальной структуре из dao_pools_snapshot.py
-- =====================================================

-- Создаем правильное представление с сортируемыми позициями
CREATE OR REPLACE VIEW bio_dao_lp_support_v2 AS
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
    -- Агрегируем наши позиции по пулам (JOIN по pool_name + network)
    SELECT 
        pool_name,
        network,
        SUM(COALESCE(CAST(position_value_usd AS NUMERIC), 0)) as total_position_value,
        SUM(COALESCE(CAST(fees_usd AS NUMERIC), 0)) as total_fees,
        COUNT(*) as positions_count,
        STRING_AGG(COALESCE(position_mint, ''), ', ') as position_details,
        STRING_AGG(COALESCE(pool_id, ''), ', ') as pool_ids
    FROM lp_position_snapshots 
    WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'  -- Только свежие данные
    GROUP BY pool_name, network
)
SELECT 
    -- Основная информация
    d.pool_name,
    d.network,
    d.dex,
    d.token_symbol,
    d.token_address,
    
    -- Финансовые метрики (как NUMERIC для сортировки)
    CAST(COALESCE(d.tvl_usd, 0) AS NUMERIC) as tvl_usd,
    CAST(COALESCE(d.volume_24h_usd, 0) AS NUMERIC) as volume_24h_usd,
    CAST(COALESCE(d.token_fdv_usd, 0) AS NUMERIC) as token_fdv_usd,
    CAST(COALESCE(d.token_mc_usd, 0) AS NUMERIC) as token_mc_usd,
    CAST(COALESCE(d.token_price_usd, 0) AS NUMERIC) as token_price_usd,
    CAST(COALESCE(d.bio_price_usd, 0) AS NUMERIC) as bio_price_usd,
    
    -- ✅ ГЛАВНОЕ ИСПРАВЛЕНИЕ: Наши позиции как NUMERIC для сортировки
    COALESCE(CAST(p.total_position_value AS NUMERIC), 0) as our_positions_usd,
    
    -- Дополнительные метрики позиций
    COALESCE(CAST(p.total_fees AS NUMERIC), 0) as our_fees_usd,
    COALESCE(p.positions_count, 0) as our_positions_count,
    
    -- Target и gap анализ
    CAST(COALESCE(d.target_lp_value_usd, 0) AS NUMERIC) as target_lp_usd,
    CAST(COALESCE(d.lp_gap_usd, 0) AS NUMERIC) as lp_gap_usd,
    
    -- Процентные изменения
    CAST(COALESCE(d.price_change_24h_percent, 0) AS NUMERIC) as price_change_24h_pct,
    CAST(COALESCE(d.price_change_7d_percent, 0) AS NUMERIC) as price_change_7d_pct,
    CAST(COALESCE(d.tvl_change_7d_percent, 0) AS NUMERIC) as tvl_change_7d_pct,
    
    -- Дополнительные поля из dao_pool_snapshots
    CAST(COALESCE(d.fee_percent, 0) AS NUMERIC) as fee_percent,
    CAST(COALESCE(d.target_fdv_percentage, 0) AS NUMERIC) as target_fdv_percentage,
    
    -- Флаги
    COALESCE(d.is_bio_pair, false) as is_bio_pair,
    CASE 
        WHEN COALESCE(p.total_position_value, 0) > 0 THEN true 
        ELSE false 
    END as has_our_position,
    
    -- Расчетные поля
    CASE 
        WHEN COALESCE(d.target_lp_value_usd, 0) > 0 THEN 
            ROUND((COALESCE(p.total_position_value, 0) / CAST(d.target_lp_value_usd AS NUMERIC)) * 100, 2)
        ELSE 0 
    END as lp_coverage_percent,
    
    -- Форматированная строка для отображения
    CASE 
        WHEN COALESCE(p.total_position_value, 0) = 0 THEN 'No position'
        WHEN COALESCE(p.total_position_value, 0) < 1000 THEN 
            '$' || ROUND(COALESCE(p.total_position_value, 0), 0)::TEXT
        WHEN COALESCE(p.total_position_value, 0) < 1000000 THEN 
            '$' || ROUND(COALESCE(p.total_position_value, 0) / 1000, 1)::TEXT || 'K'
        ELSE 
            '$' || ROUND(COALESCE(p.total_position_value, 0) / 1000000, 2)::TEXT || 'M'
    END as our_positions_formatted,
    
    -- Временные метки
    d.snapshot_timestamp,
    d.created_at,
    
    -- Детали позиций
    p.position_details,
    p.pool_ids

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
COMMENT ON VIEW bio_dao_lp_support_v2 IS 'Финальное представление BIO DAO LP поддержки с правильной структурой таблиц. JOIN по pool_name+network. Колонка our_positions_usd - NUMERIC для сортировки.';

-- =====================================================
-- ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ
-- =====================================================

-- 1. Сортировка по нашим позициям (по убыванию)
-- SELECT 
--     pool_name,
--     network,
--     our_positions_usd,
--     our_positions_formatted,
--     target_lp_usd,
--     lp_coverage_percent
-- FROM bio_dao_lp_support_v2 
-- WHERE has_our_position = true
-- ORDER BY our_positions_usd DESC;

-- 2. Топ пулы по TVL без наших позиций
-- SELECT 
--     pool_name,
--     network,
--     tvl_usd,
--     target_lp_usd,
--     our_positions_usd
-- FROM bio_dao_lp_support_v2 
-- WHERE has_our_position = false AND is_bio_pair = true
-- ORDER BY tvl_usd DESC
-- LIMIT 10;

-- 3. Анализ покрытия LP по сетям
-- SELECT 
--     network,
--     COUNT(*) as pools_count,
--     SUM(our_positions_usd) as total_our_positions,
--     SUM(target_lp_usd) as total_target,
--     ROUND(AVG(lp_coverage_percent), 2) as avg_coverage_pct
-- FROM bio_dao_lp_support_v2 
-- GROUP BY network
-- ORDER BY total_our_positions DESC;

