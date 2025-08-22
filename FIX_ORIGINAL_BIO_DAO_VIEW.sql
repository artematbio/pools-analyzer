-- =====================================================
-- ИСПРАВЛЕНИЕ ОРИГИНАЛЬНОГО ПРЕДСТАВЛЕНИЯ bio_dao_lp_support
-- =====================================================
-- 
-- ЦЕЛЬ: Сохранить все оригинальные названия колонок,
-- но сделать our_position_value_usd NUMERIC для сортировки
-- 
-- ВАЖНО: Заменяет существующее представление!
-- =====================================================

-- Удаляем старое представление
DROP VIEW IF EXISTS bio_dao_lp_support;

-- Создаем новое с теми же названиями колонок, но правильными типами
CREATE VIEW bio_dao_lp_support AS
WITH latest_dao_snapshots AS (
    -- Последние снапшоты DAO пулов
    SELECT DISTINCT ON (pool_name, network) 
        *
    FROM dao_pool_snapshots
    ORDER BY pool_name, network, snapshot_timestamp DESC
),
our_positions_aggregated AS (
    -- Агрегируем позиции по pool_name + network
    SELECT 
        pool_name,
        network,
        SUM(COALESCE(CAST(position_value_usd AS NUMERIC), 0)) as total_position_value,
        SUM(COALESCE(CAST(fees_usd AS NUMERIC), 0)) as total_fees,
        COUNT(*) as positions_count
    FROM lp_position_snapshots 
    WHERE created_at >= CURRENT_DATE - INTERVAL '7 days'
    GROUP BY pool_name, network
)
SELECT 
    -- Сохраняем ВСЕ оригинальные названия колонок
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
    
    -- ✅ КЛЮЧЕВОЕ ИСПРАВЛЕНИЕ: our_position_value_usd как NUMERIC
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
    d.target_fdv_percentage

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
COMMENT ON VIEW bio_dao_lp_support IS 'Исправленное представление с NUMERIC колонкой our_position_value_usd для правильной сортировки';

-- =====================================================
-- ТЕСТ СОРТИРОВКИ
-- =====================================================

-- Проверяем сортировку по our_position_value_usd:
-- SELECT 
--     pool_name,
--     network,
--     our_position_value_usd,
--     target_lp_value_usd
-- FROM bio_dao_lp_support 
-- ORDER BY our_position_value_usd DESC
-- LIMIT 10;

