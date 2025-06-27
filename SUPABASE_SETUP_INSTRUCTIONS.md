# Инструкция по настройке таблиц в Supabase

## 🚀 Быстрая настройка

### 1. Откройте Supabase SQL Editor
1. Перейдите в ваш проект Supabase
2. Откройте раздел "SQL Editor"
3. Создайте новый запрос

### 2. Выполните финальную оптимизированную схему
**ВАЖНО:** Используйте файл `supabase_final_schema.sql` вместо старых схем!

```sql
-- Скопируйте и выполните весь код из supabase_final_schema.sql
-- Этот файл удалит старые таблицы и создаст новые с префиксом lp_
```

### 3. Проверьте созданные таблицы
После выполнения должны быть созданы таблицы с префиксом `lp_`:

**Основные таблицы:**
- `lp_pool_snapshots` - снимки данных пулов (TVL, объемы, позиции)
- `lp_pool_volumes` - дневные объемы торгов по дням
- `lp_position_snapshots` - снимки позиций в пулах
- `lp_token_prices` - история цен токенов

**Дополнительные таблицы:**
- `lp_alerts` - системные уведомления
- `lp_treasury_transactions` - транзакции treasury (зарезервировано)
- `lp_balance_snapshots` - снимки балансов (зарезервировано)
- `lp_pool_activities` - активность в пулах (зарезервировано)

### 4. Проверьте политики безопасности
Убедитесь, что включены Row Level Security (RLS) политики.

### 5. Проверьте функции
Должны быть созданы полезные функции:
- `get_pool_stats(pool_id)` - статистика пула
- `get_top_pools_by_tvl(limit)` - топ пулов по TVL
- `get_database_summary()` - статистика всех таблиц

## 📊 Что будет дублироваться

### Pool Snapshots (`lp_pool_snapshots`)
- TVL пула в USD
- 24h объем торгов
- Количество позиций (общее, in-range, out-of-range)
- Цены токенов пула
- Комиссия пула

### Pool Volumes (`lp_pool_volumes`)
- Дневные объемы за 7 дней
- USD объемы и базовые объемы
- Количество сделок
- Источник данных (BitQuery, API)

### Position Snapshots (`lp_position_snapshots`)
- Стоимость позиций в USD
- Количество токенов в позиции
- Статус in/out of range
- Tick boundaries
- Накопленные комиссии
- Процент ликвидности от общего TVL

### Token Prices (`lp_token_prices`)
- История цен всех токенов
- Источник данных (GeckoTerminal, CoinGecko)
- Временные метки

## 🔧 Тестирование

После настройки запустите анализ:
```bash
python3 pool_analyzer.py
```

Проверьте в Supabase что данные появились в таблицах с префиксом `lp_`.

## 📈 API доступ

Данные доступны через Supabase API:
- GET `lp_pool_snapshots` - получить снимки пулов
- GET `lp_pool_volumes` - получить объемы торгов
- GET `lp_position_snapshots` - получить снимки позиций
- GET `lp_token_prices` - получить цены токенов

## 🔍 Полезные запросы

### Получить последние данные пула
```sql
SELECT * FROM lp_pool_snapshots 
WHERE pool_id = 'YOUR_POOL_ID' 
ORDER BY timestamp DESC 
LIMIT 1;
```

### Получить топ пулов по TVL
```sql
SELECT * FROM get_top_pools_by_tvl(10);
```

### Получить статистику пула
```sql
SELECT * FROM get_pool_stats('YOUR_POOL_ID');
```

### Получить статистику всех таблиц
```sql
SELECT * FROM get_database_summary();
```

### Получить последние цены токенов
```sql
SELECT DISTINCT ON (token_address) 
    token_address, symbol, price_usd, timestamp
FROM lp_token_prices 
ORDER BY token_address, timestamp DESC;
```

## ⚠️ Важные замечания

1. **Префикс `lp_`**: Все таблицы имеют префикс `lp_` (liquidity pools)
2. **Удаление старых таблиц**: Схема автоматически удалит старые таблицы без префикса
3. **Обновленный код**: `database_handler.py` обновлен для работы с новыми таблицами
4. **Безопасность**: Все таблицы защищены RLS политиками

## 🧹 Что было очищено

Схема удаляет следующие ненужные таблицы:
- `wallets`, `pools`, `positions` (из старой схемы)
- `pool_metrics`, `historical_trades`, `daily_volumes` (дубликаты)
- `analysis_runs`, `system_logs` (не используются)
- Все таблицы без префикса `lp_` (если существуют) 