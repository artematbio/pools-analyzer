-- SQL схема для дублирования данных пулов и позиций в Supabase
-- Выполнить в Supabase SQL Editor

-- Таблица снимков пулов (основные данные)
CREATE TABLE IF NOT EXISTS pool_snapshots (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    pool_id VARCHAR(255) NOT NULL,
    pool_name VARCHAR(255),
    token0_address VARCHAR(255),
    token0_symbol VARCHAR(50),
    token0_price DECIMAL(18, 8),
    token1_address VARCHAR(255),
    token1_symbol VARCHAR(50),
    token1_price DECIMAL(18, 8),
    current_price DECIMAL(18, 8),
    fee_rate DECIMAL(10, 6),
    tvl_usd DECIMAL(18, 2),
    volume_24h_usd DECIMAL(18, 2),
    total_positions INTEGER DEFAULT 0,
    in_range_positions INTEGER DEFAULT 0,
    out_of_range_positions INTEGER DEFAULT 0,
    total_value_usd DECIMAL(18, 2),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индексы для pool_snapshots
CREATE INDEX IF NOT EXISTS idx_pool_snapshots_pool_id ON pool_snapshots(pool_id);
CREATE INDEX IF NOT EXISTS idx_pool_snapshots_timestamp ON pool_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_pool_snapshots_pool_timestamp ON pool_snapshots(pool_id, timestamp);

-- Таблица объемов торгов пулов по дням
CREATE TABLE IF NOT EXISTS pool_volumes (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    pool_id VARCHAR(255) NOT NULL,
    pool_name VARCHAR(255),
    date DATE NOT NULL,
    volume_usd DECIMAL(18, 2),
    volume_base DECIMAL(18, 8),
    trades_count INTEGER DEFAULT 0,
    source VARCHAR(100),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индексы для pool_volumes
CREATE INDEX IF NOT EXISTS idx_pool_volumes_pool_id ON pool_volumes(pool_id);
CREATE INDEX IF NOT EXISTS idx_pool_volumes_date ON pool_volumes(date);
CREATE INDEX IF NOT EXISTS idx_pool_volumes_pool_date ON pool_volumes(pool_id, date);

-- Таблица снимков позиций
CREATE TABLE IF NOT EXISTS position_snapshots (
    id BIGINT PRIMARY KEY GENERATED ALWAYS AS IDENTITY,
    position_mint VARCHAR(255) NOT NULL,
    pool_id VARCHAR(255) NOT NULL,
    pool_name VARCHAR(255),
    token0_address VARCHAR(255),
    token0_symbol VARCHAR(50),
    token0_amount DECIMAL(18, 8),
    token1_address VARCHAR(255),
    token1_symbol VARCHAR(50),
    token1_amount DECIMAL(18, 8),
    position_value_usd DECIMAL(18, 2),
    fees_usd DECIMAL(18, 2),
    in_range BOOLEAN DEFAULT FALSE,
    tick_lower INTEGER,
    tick_upper INTEGER,
    current_price DECIMAL(18, 8),
    fee_tier DECIMAL(10, 6),
    liquidity_share_percent DECIMAL(8, 4),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Индексы для position_snapshots
CREATE INDEX IF NOT EXISTS idx_position_snapshots_position_mint ON position_snapshots(position_mint);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_pool_id ON position_snapshots(pool_id);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_timestamp ON position_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_position_snapshots_position_timestamp ON position_snapshots(position_mint, timestamp);

-- Комментарии к таблицам
COMMENT ON TABLE pool_snapshots IS 'Снимки данных пулов с TVL, объемом и позициями';
COMMENT ON TABLE pool_volumes IS 'Дневные объемы торгов пулов';
COMMENT ON TABLE position_snapshots IS 'Снимки позиций в пулах';

-- Политики безопасности (Row Level Security)
ALTER TABLE pool_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE pool_volumes ENABLE ROW LEVEL SECURITY;
ALTER TABLE position_snapshots ENABLE ROW LEVEL SECURITY;

-- Разрешить чтение всем аутентифицированным пользователям
CREATE POLICY IF NOT EXISTS "Allow read access for authenticated users" ON pool_snapshots
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY IF NOT EXISTS "Allow read access for authenticated users" ON pool_volumes
    FOR SELECT USING (auth.role() = 'authenticated');

CREATE POLICY IF NOT EXISTS "Allow read access for authenticated users" ON position_snapshots
    FOR SELECT USING (auth.role() = 'authenticated');

-- Разрешить запись только сервисной роли
CREATE POLICY IF NOT EXISTS "Allow insert for service role" ON pool_snapshots
    FOR INSERT WITH CHECK (auth.role() = 'service_role');

CREATE POLICY IF NOT EXISTS "Allow update for service role" ON pool_snapshots
    FOR UPDATE USING (auth.role() = 'service_role');

CREATE POLICY IF NOT EXISTS "Allow insert for service role" ON pool_volumes
    FOR INSERT WITH CHECK (auth.role() = 'service_role');

CREATE POLICY IF NOT EXISTS "Allow insert for service role" ON position_snapshots
    FOR INSERT WITH CHECK (auth.role() = 'service_role');

CREATE POLICY IF NOT EXISTS "Allow update for service role" ON position_snapshots
    FOR UPDATE USING (auth.role() = 'service_role');

-- Функции для получения статистики
CREATE OR REPLACE FUNCTION get_pool_stats(pool_id_param VARCHAR)
RETURNS TABLE (
    latest_tvl DECIMAL,
    latest_volume_24h DECIMAL,
    total_positions INTEGER,
    avg_volume_7d DECIMAL
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        (SELECT tvl_usd FROM pool_snapshots WHERE pool_id = pool_id_param ORDER BY timestamp DESC LIMIT 1) as latest_tvl,
        (SELECT volume_24h_usd FROM pool_snapshots WHERE pool_id = pool_id_param ORDER BY timestamp DESC LIMIT 1) as latest_volume_24h,
        (SELECT total_positions FROM pool_snapshots WHERE pool_id = pool_id_param ORDER BY timestamp DESC LIMIT 1) as total_positions,
        (SELECT AVG(volume_usd) FROM pool_volumes WHERE pool_id = pool_id_param AND date >= CURRENT_DATE - INTERVAL '7 days') as avg_volume_7d;
END;
$$ LANGUAGE plpgsql;

-- Функция для получения топ пулов по TVL
CREATE OR REPLACE FUNCTION get_top_pools_by_tvl(limit_param INTEGER DEFAULT 10)
RETURNS TABLE (
    pool_id VARCHAR,
    pool_name VARCHAR,
    tvl_usd DECIMAL,
    volume_24h_usd DECIMAL,
    total_positions INTEGER,
    latest_timestamp TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    WITH latest_snapshots AS (
        SELECT DISTINCT ON (ps.pool_id) 
            ps.pool_id,
            ps.pool_name,
            ps.tvl_usd,
            ps.volume_24h_usd,
            ps.total_positions,
            ps.timestamp
        FROM pool_snapshots ps
        ORDER BY ps.pool_id, ps.timestamp DESC
    )
    SELECT 
        ls.pool_id,
        ls.pool_name,
        ls.tvl_usd,
        ls.volume_24h_usd,
        ls.total_positions,
        ls.timestamp
    FROM latest_snapshots ls
    ORDER BY ls.tvl_usd DESC
    LIMIT limit_param;
END;
$$ LANGUAGE plpgsql; 