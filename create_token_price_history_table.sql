-- СОЗДАНИЕ ТАБЛИЦЫ ДЛЯ ИСТОРИЧЕСКИХ ЦЕН ТОКЕНОВ
-- Назначение: Хранение текущих и исторических цен для расчета 24h/7d изменений
-- Связь: token_symbol + network = уникальная запись (UPSERT логика)

CREATE TABLE IF NOT EXISTS token_price_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  
  -- Идентификация токена
  token_symbol TEXT NOT NULL,
  network TEXT NOT NULL,
  
  -- Текущие данные
  price_current DECIMAL,
  fdv_current DECIMAL,
  market_cap_current DECIMAL,
  
  -- Исторические цены (для расчетов)
  price_24h_ago DECIMAL,
  price_7d_ago DECIMAL,
  fdv_24h_ago DECIMAL,
  fdv_7d_ago DECIMAL,
  
  -- Рассчитанные изменения (%)
  price_change_24h_percent DECIMAL,
  price_change_7d_percent DECIMAL,
  fdv_change_24h_percent DECIMAL,
  fdv_change_7d_percent DECIMAL,
  
  -- Мета-данные
  last_updated TIMESTAMPTZ DEFAULT NOW(),
  data_source TEXT DEFAULT 'geckoterminal',
  
  -- Уникальность: один токен на сеть
  CONSTRAINT unique_token_network UNIQUE (token_symbol, network)
);

-- Индексы для быстрых запросов
CREATE INDEX IF NOT EXISTS idx_token_price_history_symbol ON token_price_history(token_symbol);
CREATE INDEX IF NOT EXISTS idx_token_price_history_network ON token_price_history(network);
CREATE INDEX IF NOT EXISTS idx_token_price_history_updated ON token_price_history(last_updated);

-- Комментарии
COMMENT ON TABLE token_price_history IS 'Исторические цены токенов для расчета 24h/7d изменений';
COMMENT ON COLUMN token_price_history.token_symbol IS 'Символ токена (VITA, BIO, etc)';
COMMENT ON COLUMN token_price_history.network IS 'Сеть (ethereum, base, solana)';
COMMENT ON COLUMN token_price_history.price_current IS 'Текущая цена USD';
COMMENT ON COLUMN token_price_history.price_24h_ago IS 'Цена 24 часа назад';
COMMENT ON COLUMN token_price_history.price_7d_ago IS 'Цена 7 дней назад';
COMMENT ON COLUMN token_price_history.price_change_24h_percent IS 'Изменение цены за 24ч (%)';
COMMENT ON COLUMN token_price_history.price_change_7d_percent IS 'Изменение цены за 7д (%)'; 