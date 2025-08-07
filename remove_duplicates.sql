-- УДАЛЕНИЕ ДУБЛЕЙ ИЗ ТАБЛИЦ POSITIONS И POOLS
-- Оставляем только последние записи по времени создания

-- 1. Удаляем дубли из lp_position_snapshots (оставляем последние записи)
DELETE FROM lp_position_snapshots 
WHERE id NOT IN (
    SELECT DISTINCT ON (position_mint, network) id
    FROM lp_position_snapshots 
    ORDER BY position_mint, network, created_at DESC
);

-- 2. Удаляем дубли из lp_pool_snapshots (оставляем последние записи)  
DELETE FROM lp_pool_snapshots
WHERE id NOT IN (
    SELECT DISTINCT ON (pool_address, network) id
    FROM lp_pool_snapshots
    ORDER BY pool_address, network, created_at DESC
);

-- 3. Удаляем старые записи с TVL = 0 если есть новые с TVL > 0
DELETE FROM lp_pool_snapshots old
WHERE old.tvl_usd = 0 
  AND EXISTS (
    SELECT 1 FROM lp_pool_snapshots new
    WHERE new.pool_address = old.pool_address 
      AND new.network = old.network
      AND new.tvl_usd > 0
      AND new.created_at > old.created_at
  );

-- ПРОВЕРКА РЕЗУЛЬТАТОВ:
SELECT 
    network,
    COUNT(*) as total_positions,
    COUNT(DISTINCT position_mint) as unique_positions
FROM lp_position_snapshots 
GROUP BY network
ORDER BY network;

SELECT 
    network,
    COUNT(*) as total_pools,
    COUNT(DISTINCT pool_address) as unique_pools,
    SUM(CASE WHEN tvl_usd > 0 THEN 1 ELSE 0 END) as pools_with_tvl
FROM lp_pool_snapshots 
GROUP BY network
ORDER BY network;
