-- ОБНОВЛЕННЫЙ VIEW dao_tokens_dashboard С ИСТОРИЧЕСКИМИ ДАННЫМИ
-- Теперь использует token_price_history для 24h/7d изменений
-- JOIN между dao_pool_snapshots и token_price_history

DROP VIEW IF EXISTS dao_tokens_dashboard;

CREATE VIEW dao_tokens_dashboard AS
WITH latest_token_data AS (
  SELECT 
    token_symbol,
    MAX(token_price_usd) as price,
    MAX(token_fdv_usd) as fdv_usd,
    SUM(tvl_usd) as total_tvl_usd,  -- Суммируем TVL со всех пулов токена
    MAX(snapshot_timestamp) as last_updated
  FROM (
    SELECT 
      token_symbol,
      token_price_usd,
      token_fdv_usd,
      tvl_usd,
      snapshot_timestamp,
      ROW_NUMBER() OVER (
        PARTITION BY token_symbol, network, pool_address 
        ORDER BY snapshot_timestamp DESC
      ) as rn
    FROM dao_pool_snapshots 
    WHERE 
      token_fdv_usd > 0  -- ТОЛЬКО УСПЕШНЫЕ ЗАПИСИ (FDV > 0)
      AND token_symbol NOT IN ('SOL', 'ETH', 'BIO', 'WETH')  -- ИСКЛЮЧАЕМ БАЗОВЫЕ ТОКЕНЫ
  ) ranked
  WHERE rn = 1  -- Берем только последние записи для каждого пула
  GROUP BY token_symbol  -- Агрегируем данные по токену
)
SELECT 
  ltd.token_symbol as "Token",
  ROUND(ltd.price::numeric, 6) as "Price",
  ROUND((ltd.price * ltd.fdv_usd / NULLIF(ltd.price, 0))::numeric, 0) as "M-Cap",  -- Market Cap
  ROUND(ltd.fdv_usd::numeric, 0) as "FDV",
  
  -- ИСТОРИЧЕСКИЕ ИЗМЕНЕНИЯ из token_price_history
  COALESCE(ROUND(tph.price_change_24h_percent::numeric, 2), NULL) as "24h Δ",
  COALESCE(ROUND(tph.price_change_7d_percent::numeric, 2), NULL) as "7d Δ", 
  
  ROUND(ltd.total_tvl_usd::numeric, 0) as "TVL (all pools)",
  
  -- TVL изменения (пока NULL, можно добавить позже)
  NULL as "Liquidity Δ7d",
  
  CASE 
    WHEN ltd.total_tvl_usd > 0 THEN ROUND((ltd.fdv_usd / ltd.total_tvl_usd)::numeric, 2)
    ELSE NULL 
  END as "FDV/TVL",
  
  GREATEST(ltd.last_updated, tph.last_updated) as last_updated
  
FROM latest_token_data ltd
LEFT JOIN token_price_history tph ON (
  ltd.token_symbol = tph.token_symbol
  -- Берем лучшие исторические данные (независимо от сети)
  AND tph.last_updated = (
    SELECT MAX(last_updated) 
    FROM token_price_history tph2 
    WHERE tph2.token_symbol = ltd.token_symbol
  )
)
WHERE 
  ltd.fdv_usd > 0  -- Дополнительная проверка на корректные данные
ORDER BY 
  ltd.fdv_usd DESC;  -- Сортируем по FDV (самые крупные токены сверху)

-- Комментарий: VIEW теперь показывает исторические изменения цен
-- Использует LEFT JOIN с token_price_history для 24h/7d данных
-- Если истории нет - показывает NULL (постепенно заполнится после сбора данных) 