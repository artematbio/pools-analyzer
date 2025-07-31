# Supabase Handlers - Диагностические скрипты

Этот каталог содержит скрипты для диагностики и управления данными в Supabase.

## 📋 Скрипты проверки данных

### Проверка свежести данных
- `check_fresh_data.py` - Проверка актуальности данных
- `check_position_data_freshness.py` - Проверка свежести позиций

### Проверка view bio_dao_lp_support
- `check_view_current_state.py` - Текущее состояние view
- `check_view_definition.py` - Определение view
- `check_view_latest.py` - Последние данные view
- `check_view_problem.py` - Диагностика проблем view

### Проверка FDV данных
- `check_supabase_fdv.py` - Проверка FDV в Supabase
- `debug_view_sql.py` - Отладка SQL view

## 🛠️ SQL скрипты

### Исправления view bio_dao_lp_support
- `fix_bio_dao_lp_support_FINAL_v6_NOT_DUMB.sql`
- `fix_bio_dao_lp_support_FINAL_v7_ULTIMATE.sql` 
- `fix_bio_dao_lp_support_FINAL_v8_AGGREGATE.sql` - **АКТУАЛЬНАЯ ВЕРСИЯ**

## 🚀 Использование

Запуск скриптов:
```bash
python3 supabase-handlers/check_view_current_state.py
```

Применение SQL:
```sql
-- Подключитесь к Supabase и выполните:
\i supabase-handlers/fix_bio_dao_lp_support_FINAL_v8_AGGREGATE.sql
```
