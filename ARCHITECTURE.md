# POOLS-ANALYZER MULTICHAIN SYSTEM ARCHITECTURE

## 📋 Содержание

1. [Обзор системы](#обзор-системы)
2. [Архитектурные слои](#архитектурные-слои)
3. [Схема данных](#схема-данных)
4. [Детальный workflow](#детальный-workflow)
5. [Критические зависимости](#критические-зависимости)
6. [Вычисления и алгоритмы](#вычисления-и-алгоритмы)
7. [Обработка ошибок](#обработка-ошибок)
8. [Конфигурация](#конфигурация)
9. [Мониторинг и алертинг](#мониторинг-и-алертинг)

---

## 🎯 Обзор системы

**Pools-Analyzer** - это мультичейн система мониторинга ликвидности и позиций в DeFi протоколах, работающая с тремя блокчейнами:

- **Solana**: Raydium CLMM пулы
- **Ethereum**: Uniswap V3 пулы  
- **Base**: Uniswap V3 пулы

### Основная цель
Отслеживание портфеля DAO токенов, их ликвидности, расчет инвестиционных приоритетов и автоматическая генерация отчетов.

### Ключевые метрики
- **Total Portfolio Value**: $3.6M+ (по состоянию на последний тест)
- **Monitored Networks**: 3 (Solana, Ethereum, Base)
- **Tracked Positions**: 23+ активных позиций
- **Monitored Pools**: 48 пулов из конфигурации (20 Ethereum + 9 Base + 19 Solana)

---

## 🏗️ Архитектурные слои

### 1. DATA COLLECTION LAYER (Сбор данных)

#### 1.1 Solana Data Collection
**Основной скрипт**: `positions.py` или `csv_pools_generator_v4.py`

**Источники данных**:
- Helius RPC API
- Raydium CLMM protocol contracts
- Token metadata from Jupiter

**Процесс**:
```
1. Загрузка кошельков из конфигурации
2. Получение всех позиций для каждого кошелька
3. Фильтрация по минимальной стоимости ($10 USD)
4. Обогащение данными пулов (TVL, цены)
5. Сохранение в lp_position_snapshots
```

#### 1.2 Ethereum/Base Data Collection  
**Основной скрипт**: `unified_positions_analyzer.py`

**Источники данных**:
- Ethereum RPC (Alchemy/Infura)
- Base RPC 
- Uniswap V3 contracts
- The Graph subgraph

**Процесс**:
```
1. Инициализация RPC клиента для сети
2. Получение всех NFT позиций кошелька
3. Для каждой позиции:
   a. Получение метаданных токенов
   b. Расчет текущей стоимости
   c. Проверка статуса (in-range/out-of-range)
   d. Расчет unclaimed fees
4. Группировка по пулам
5. Сохранение в lp_position_snapshots и lp_pool_snapshots
```

#### 1.3 DAO Pools Data Collection
**Основной скрипт**: `dao_pools_snapshot.py`

**Источники данных**:
- `tokens_pools_config.json` (централизованная конфигурация)
- GeckoTerminal API
- Supabase lp_position_snapshots (для расчетов)

**Процесс**:
```
1. Загрузка всех пулов из tokens_pools_config.json
2. Загрузка данных наших позиций из Supabase
3. Для каждого пула:
   a. Запрос к GeckoTerminal API (TVL, цена)
   b. Расчет метрик DAO токена
   c. Расчет gap анализа
   d. Создание виртуальных BIO пар (если отсутствуют)
4. Расчет исторических изменений (24h, 7d)
5. Сохранение в dao_pool_snapshots
```

### 2. DATA STORAGE LAYER (Хранение)

#### 2.1 Database Handler
**Основной модуль**: `database_handler.py`

**Функции**:
- Подключение к Supabase PostgreSQL
- Batch операции для больших объемов данных
- Методы сохранения для каждого типа данных
- Получение исторических данных

**Методы**:
```python
save_position_snapshot(position_data)      # Сохранение позиций
save_pool_snapshot(pool_data)              # Сохранение пулов  
save_dao_pool_snapshot(dao_pool_data)      # Сохранение DAO снапшотов
get_historical_token_price(symbol, days)   # Исторические цены
get_historical_token_tvl(symbol, days)     # Исторический TVL
```

#### 2.2 Схемы таблиц Supabase

**lp_position_snapshots**:
```sql
CREATE TABLE lp_position_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  position_mint TEXT NOT NULL,           -- ID позиции (без префиксов сети)
  network TEXT NOT NULL,                 -- 'solana', 'ethereum', 'base' 
  pool_id TEXT NOT NULL,                 -- Адрес пула (без префиксов)
  pool_name TEXT,                        -- Имя пула (TOKEN0/TOKEN1)
  token0_address TEXT,
  token0_symbol TEXT,
  token0_amount DECIMAL,
  token1_address TEXT, 
  token1_symbol TEXT,
  token1_amount DECIMAL,
  position_value_usd DECIMAL,            -- Основная стоимость позиции
  fees_usd DECIMAL,                      -- Unclaimed fees
  in_range BOOLEAN,                      -- Статус позиции
  current_price DECIMAL,
  fee_tier DECIMAL,
  tick_lower INTEGER,
  tick_upper INTEGER,
  liquidity_share_percent DECIMAL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

**dao_pool_snapshots**:
```sql
CREATE TABLE dao_pool_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pool_address TEXT NOT NULL,
  pool_name TEXT NOT NULL,
  network TEXT NOT NULL,
  dex TEXT,
  tvl_usd DECIMAL,
  token_symbol TEXT,
  token_fdv_usd DECIMAL,
  bio_price_usd DECIMAL,
  is_bio_pair BOOLEAN,
  our_position_value_usd DECIMAL,        -- ЗАВИСИТ ОТ lp_position_snapshots
  target_lp_value_usd DECIMAL,           -- 1% от FDV для BIO пар
  lp_gap_usd DECIMAL,                    -- Разрыв до цели
  price_change_24h_percent DECIMAL,      -- Исторические изменения  
  price_change_7d_percent DECIMAL,
  tvl_change_7d_percent DECIMAL,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  snapshot_timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

**lp_pool_snapshots**:
```sql
CREATE TABLE lp_pool_snapshots (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  pool_id TEXT NOT NULL,                 -- Адрес пула
  pool_address TEXT NOT NULL,            -- Дублирование для совместимости
  pool_name TEXT,                        -- TOKEN0/TOKEN1
  network TEXT NOT NULL,
  token0_address TEXT,
  token0_symbol TEXT,
  token1_address TEXT,
  token1_symbol TEXT,
  fee_tier DECIMAL,
  tvl_usd DECIMAL,
  volume_24h_usd DECIMAL,
  tick INTEGER,                          -- Текущий тик
  sqrtPriceX96 TEXT,                     -- Цена в формате Uniswap
  liquidity TEXT,                        -- Активная ликвидность
  created_at TIMESTAMPTZ DEFAULT NOW(),
  timestamp TIMESTAMPTZ DEFAULT NOW()
);
```

### 3. REPORTING LAYER (Отчетность)

#### 3.1 Multichain Report Generator
**Основной скрипт**: `multichain_report_generator.py`

**Функции**:
- Агрегация данных со всех сетей
- Форматирование unified отчета
- Отправка в Telegram

**Алгоритм**:
```
1. Сбор данных Solana из lp_position_snapshots
2. Сбор данных Ethereum из lp_position_snapshots  
3. Сбор данных Base из lp_position_snapshots
4. Расчет агрегированной статистики:
   - Total portfolio value
   - Networks summary
   - Top positions by value
   - Out-of-range positions count
5. Форматирование через ReportFormatter
6. Отправка через TelegramSender
```

#### 3.2 CSV Report Generator  
**Основной скрипт**: `csv_pools_generator_v4.py`

**Функции**:
- Детальный CSV отчет по токенам и пулам
- Группировка по токенам
- Сохранение агрегированных данных в Supabase

### 4. ORCHESTRATION LAYER (Оркестрация)

#### 4.1 Task Scheduler
**Основной скрипт**: `scheduler.py`

**Задачи и расписание**:
```python
# СБОР ПОЗИЦИЙ
'ethereum_positions_analysis': "0 */4 * * *"           # Каждые 4 часа
'base_positions_analysis': "0 2,6,10,14,18,22 * * *"   # Каждые 4 часа (+2ч offset)

# СБОР ПУЛОВ (ЗАВИСИТ ОТ ПОЗИЦИЙ)
'dao_pools_snapshots': "30 9,21 * * *"                 # 09:30 и 21:30 UTC

# ГЕНЕРАЦИЯ ОТЧЕТОВ  
'multichain_csv_report': "0 10 * * *"                  # 10:00 UTC ежедневно
'multichain_telegram_report': "0 12,20 * * *"          # 12:00 и 20:00 UTC

# СИСТЕМНЫЕ ЗАДАЧИ
'health_check': "*/5 * * * *"                          # Каждые 5 минут
'out_of_range_check': "*/30 * * * *"                   # Каждые 30 минут
```

---

## 🔄 Детальный Workflow

### ЭТАП 1: Position Data Collection (ОБЯЗАТЕЛЬНЫЙ ПЕРВЫЙ ЭТАП)

#### 1.1 Solana Positions Collection

**Входные данные**:
- Список кошельков из конфигурации
- Минимальная стоимость позиции ($10)

**Процесс**:
```python
# positions.py или csv_pools_generator_v4.py
async def collect_solana_positions():
    for wallet_address in SOLANA_WALLETS:
        # 1. Получение всех позиций кошелька
        positions = await get_wallet_positions(wallet_address)
        
        # 2. Фильтрация по стоимости
        filtered = [p for p in positions if p['value_usd'] >= 10]
        
        # 3. Обогащение данными пулов
        for position in filtered:
            pool_data = await get_pool_info(position['pool_address'])
            position.update(pool_data)
            
        # 4. Сохранение в Supabase
        await save_positions_batch(filtered)
```

**Выходные данные**: Записи в `lp_position_snapshots` с network='solana'

#### 1.2 Ethereum/Base Positions Collection

**Входные данные**:
- Ethereum/Base кошелек: `0x31AAc4021540f61fe20c3dAffF64BA6335396850`
- RPC endpoints для сетей

**Процесс**:
```python
# unified_positions_analyzer.py
async def get_uniswap_positions(wallet_address, network):
    # 1. Инициализация RPC клиента
    rpc_client = RPCClient(NETWORK_CONFIGS[network]['rpc_url'])
    
    # 2. Получение всех NFT позиций из Uniswap V3
    nft_positions = await get_wallet_nft_positions(wallet_address)
    
    # 3. Для каждой позиции
    for nft_id in nft_positions:
        # a. Получение данных позиции
        position_data = await get_position_details(nft_id)
        
        # b. Получение метаданных токенов
        token_metadata = await get_tokens_metadata([
            position_data['token0'], 
            position_data['token1']
        ])
        
        # c. Расчет текущей стоимости
        current_value = await calculate_position_value(position_data)
        
        # d. Проверка in-range статуса
        in_range = check_position_in_range(position_data)
        
        # e. Расчет unclaimed fees
        fees = await calculate_unclaimed_fees(position_data)
        
    # 4. Сохранение в Supabase
    await save_ethereum_positions_to_supabase(positions, network)
```

**Критические исправления**:
```python
# ✅ ПРАВИЛЬНОЕ формирование pool_save_data
pool_token_info[pool_address] = {
    'token0_address': pos_data["token0"],
    'token1_address': pos_data["token1"], 
    'token0_symbol': token0_meta.get("symbol", "UNK"),
    'token1_symbol': token1_meta.get("symbol", "UNK"),
    'fee_tier': pos_data["fee"]
}

pool_save_data = {
    'pool_address': pool_address,
    'pool_name': f"{token0_symbol}/{token1_symbol}",  # ← НЕ Pool_0x...
    'pool_id': pool_address,                          # ← БЕЗ префиксов сети
    'token0_address': token_info.get('token0_address'),
    'token1_address': token_info.get('token1_address'),
    'token0_symbol': token0_symbol,
    'token1_symbol': token1_symbol,
    'fee_tier': token_info.get('fee_tier', 3000)
}
```

**Выходные данные**: 
- Записи в `lp_position_snapshots` с network='ethereum'/'base'
- Записи в `lp_pool_snapshots` с данными пулов

### ЭТАП 2: Pool Data Collection (ЗАВИСИТ ОТ ЭТАПА 1)

#### 2.1 DAO Pools Snapshot Collection

**Входные данные**:
- `tokens_pools_config.json` (48 пулов: 20 Ethereum + 9 Base + 19 Solana)
- Данные из `lp_position_snapshots` (КРИТИЧЕСКАЯ ЗАВИСИМОСТЬ)

**Процесс**:
```python
# dao_pools_snapshot.py
async def generate_snapshot():
    # 1. КРИТИЧНО: Загрузка наших позиций из Supabase
    our_positions = await load_our_positions_from_supabase()
    
    # 2. Загрузка пулов из конфигурации
    all_pools = await load_pools_from_config()
    
    # 3. Загрузка DAO токенов для расчетов FDV
    dao_tokens = await load_dao_tokens_for_calculations()
    
    # 4. Для каждого пула из конфига
    for pool_info in all_pools:
        # a. Запрос к GeckoTerminal API
        api_data = await get_pool_data_from_geckoterminal(
            pool_info['pool_address']
        )
        
        # b. Поиск соответствующего DAO токена
        dao_token = find_dao_token_for_pool(pool_info, dao_tokens)
        
        # c. КРИТИЧЕСКИЙ РАСЧЕТ: метрики с использованием позиций
        if dao_token:
            metrics = calculate_pool_dao_metrics(
                pool_info, dao_token, our_positions  # ← ЗАВИСИМОСТЬ!
            )
        else:
            metrics = create_basic_pool_metrics(pool_info, our_positions)
        
        # d. Расчет исторических изменений
        historical = await calculate_historical_changes(pool_info)
        
        # e. Формирование снапшота
        snapshot = {
            **pool_info,
            **api_data,
            **metrics,
            **historical,
            'snapshot_timestamp': datetime.now(timezone.utc)
        }
        
    # 5. Создание виртуальных BIO пар
    virtual_pairs = create_virtual_bio_pairs(dao_tokens)
    
    # 6. Сохранение в dao_pool_snapshots
    await save_snapshots_to_supabase(all_snapshots)
```

**Критическая зависимость**:
```python
async def load_our_positions_from_supabase():
    """БЕЗ ЭТИХ ДАННЫХ dao_pools_snapshot.py НЕ МОЖЕТ РАБОТАТЬ!"""
    result = supabase_handler.client.table('lp_position_snapshots').select('*').gte(
        'created_at', week_ago
    ).order('created_at', desc=True).execute()
    
    # Группировка по pool_id + network
    positions_by_pool = {}
    for pos in result.data:
        pool_key = f"{pos['pool_id'].lower()}_{pos['network']}"
        if pool_key not in positions_by_pool:
            positions_by_pool[pool_key] = pos
    
    return positions_by_pool
```

**Выходные данные**: Записи в `dao_pool_snapshots`

### ЭТАП 3: Report Generation (ИСПОЛЬЗУЕТ ВСЕ ДАННЫЕ)

#### 3.1 Multichain Telegram Report

**Входные данные**:
- `lp_position_snapshots` (все сети)
- `lp_pool_snapshots` (контекст пулов)

**Процесс**:
```python
# multichain_report_generator.py
async def generate_report():
    # 1. Сбор данных со всех сетей
    solana_data = await get_solana_data_from_supabase()
    ethereum_data = await get_ethereum_data_from_supabase()  
    base_data = await get_base_data_from_supabase()
    
    # 2. Агрегация статистики
    summary = calculate_multichain_summary({
        'solana': solana_data,
        'ethereum': ethereum_data,
        'base': base_data
    })
    
    # 3. Форматирование отчета
    formatted_report = format_multichain_report(summary)
    
    # 4. Отправка в Telegram
    await telegram_sender.send_message(formatted_report)
```

**Критическое исправление фильтрации**:
```python
# ❌ БЫЛО (неправильно):
positions_result = supabase_handler.client.table('lp_position_snapshots').select('*').like(
    'position_mint', 'ethereum_%'  # ← position_mint НЕ содержит префиксов!
)

# ✅ СТАЛО (правильно):
positions_result = supabase_handler.client.table('lp_position_snapshots').select('*').eq(
    'network', 'ethereum'  # ← Фильтрация по network колонке
)
```

---

## 🧮 Вычисления и алгоритмы

### 1. Pool DAO Metrics Calculation

**Местоположение**: `dao_pools_snapshot.py:540-591`

```python
def calculate_pool_dao_metrics(pool_data, dao_token_info, our_positions):
    """Расчет ключевых метрик для DAO пула"""
    
    # 1. Определение DAO токена в пуле
    dao_token_symbol = dao_token_info['symbol']
    pool_name = pool_data['pool_name'].upper()
    is_dao_in_pool = dao_token_symbol.upper() in pool_name
    
    # 2. Проверка BIO пары
    is_bio_pair = (
        'BIO' in pool_name and 
        dao_token_symbol.upper() in pool_name and
        dao_token_symbol.upper() != 'QBIO'  # Исключение QBIO
    )
    
    # 3. Расчет количества DAO токена в пуле
    tvl_usd = pool_data['tvl_usd']
    dao_token_price = dao_token_info.get('price_usd', 0)
    
    if dao_token_price > 0 and is_dao_in_pool:
        # Предположение 50/50 распределения в пуле
        dao_token_value_in_pool = tvl_usd / 2
        dao_token_amount_in_pool = dao_token_value_in_pool / dao_token_price
    else:
        dao_token_value_in_pool = 0
        dao_token_amount_in_pool = 0
    
    # 4. КРИТИЧЕСКИЙ РАСЧЕТ: стоимость наших позиций
    pool_key = f"{pool_data['pool_address'].lower()}_{pool_data['network']}"
    our_position_value = our_positions.get(pool_key, {}).get('total_value_usd', 0)
    
    # 5. Целевая ликвидность для BIO пар (1% от FDV)
    target_lp_value_usd = 0
    if is_bio_pair and dao_token_info.get('fdv_usd', 0) > 0:
        target_lp_value_usd = dao_token_info['fdv_usd'] * 0.01  # 1% от FDV
    
    # 6. Расчет gap (разрыва до цели)
    lp_gap_usd = target_lp_value_usd - our_position_value
    
    return {
        'is_bio_pair': is_bio_pair,
        'our_position_value_usd': our_position_value,
        'target_lp_value_usd': target_lp_value_usd,
        'lp_gap_usd': lp_gap_usd
    }
```

### 2. Historical Data Calculation

**Местоположение**: `dao_pools_snapshot.py:685-711`

```python
async def calculate_historical_changes(token_symbol):
    """Расчет исторических изменений цены и TVL"""
    
    # 1. Получение исторических цен
    price_24h_ago = await database_handler.get_historical_token_price(
        token_symbol, days_back=1
    )
    price_7d_ago = await database_handler.get_historical_token_price(
        token_symbol, days_back=7
    )
    current_price = current_token_data.get('price_usd', 0)
    
    # 2. Расчет процентных изменений цены
    if price_24h_ago and price_24h_ago > 0:
        price_change_24h = ((current_price - price_24h_ago) / price_24h_ago) * 100
    else:
        price_change_24h = 0
        
    if price_7d_ago and price_7d_ago > 0:
        price_change_7d = ((current_price - price_7d_ago) / price_7d_ago) * 100
    else:
        price_change_7d = 0
    
    # 3. Получение исторического TVL
    tvl_7d_ago = await database_handler.get_historical_token_tvl(
        token_symbol, days_back=7
    )
    current_tvl = current_token_data.get('total_tvl_usd', 0)
    
    # 4. Расчет изменения TVL
    if tvl_7d_ago and tvl_7d_ago > 0:
        tvl_change_7d = ((current_tvl - tvl_7d_ago) / tvl_7d_ago) * 100
    else:
        tvl_change_7d = 0
    
    return {
        'price_change_24h_percent': round(price_change_24h, 2),
        'price_change_7d_percent': round(price_change_7d, 2),
        'tvl_change_7d_percent': round(tvl_change_7d, 2)
    }
```

### 3. Virtual BIO Pairs Creation

**Местоположение**: `dao_pools_snapshot.py:765-798`

```python
def create_virtual_bio_pairs(dao_tokens, bio_price):
    """Создание виртуальных BIO пар для токенов без реальных пар"""
    
    virtual_pairs = []
    
    for token_symbol, token_info in dao_tokens.items():
        # Пропускаем сам BIO
        if token_symbol.upper() == 'BIO':
            continue
            
        # Проверяем, есть ли уже реальная BIO пара
        bio_pair_exists = any(
            'BIO' in existing_pool['pool_name'] and 
            token_symbol.upper() in existing_pool['pool_name'].upper()
            for existing_pool in real_pools
        )
        
        if not bio_pair_exists:
            # Создаем виртуальную пару
            fdv_usd = token_info.get('fdv_usd', 0)
            target_lp_value = fdv_usd * 0.01 if fdv_usd > 0 else 0  # 1% от FDV
            
            virtual_pair = {
                'pool_address': f"virtual_{token_symbol.lower()}_bio",
                'pool_name': f"{token_symbol}/BIO",
                'network': token_info.get('primary_network', 'solana'),
                'dex': 'virtual',
                'tvl_usd': 0,
                'token_symbol': token_symbol,
                'token_fdv_usd': fdv_usd,
                'bio_price_usd': bio_price,
                'is_bio_pair': True,
                'our_position_value_usd': 0,
                'target_lp_value_usd': target_lp_value,
                'lp_gap_usd': target_lp_value,  # Полный gap, так как позиции нет
                'price_change_24h_percent': 0,
                'price_change_7d_percent': 0,
                'tvl_change_7d_percent': 0
            }
            
            virtual_pairs.append(virtual_pair)
    
    return virtual_pairs
```

### 4. Multichain Summary Calculation

**Местоположение**: `multichain_report_generator.py:138-180`

```python
def _calculate_summary(multichain_data):
    """Расчет агрегированной статистики по всем сетям"""
    
    summary = multichain_data['summary']
    
    # 1. Подсчет общих метрик
    total_value = 0
    total_positions = 0
    out_of_range_count = 0
    
    for network, positions in multichain_data.items():
        if network == 'summary':
            continue
            
        network_value = 0
        network_positions = len(positions)
        
        for position in positions:
            value = position.get('total_value_usd', 0) or position.get('position_value_usd', 0)
            network_value += value
            
            # Подсчет out-of-range позиций
            if not position.get('in_range', True):
                out_of_range_count += 1
        
        total_value += network_value
        total_positions += network_positions
        
        # Сохранение статистики по сети
        summary[f'{network}_value'] = network_value
        summary[f'{network}_positions'] = network_positions
    
    # 2. Обновление общей статистики
    summary.update({
        'total_value_usd': total_value,
        'total_positions': total_positions,
        'out_of_range_positions': out_of_range_count,
        'in_range_positions': total_positions - out_of_range_count,
        'average_position_size': total_value / total_positions if total_positions > 0 else 0
    })
    
    # 3. Определение топ-5 позиций
    all_positions = []
    for network, positions in multichain_data.items():
        if network != 'summary':
            for pos in positions:
                pos['network'] = network
                all_positions.append(pos)
    
    # Сортировка по стоимости
    top_positions = sorted(
        all_positions, 
        key=lambda x: x.get('total_value_usd', 0) or x.get('position_value_usd', 0),
        reverse=True
    )[:5]
    
    summary['top_positions'] = top_positions
```

---

## 🔗 Критические зависимости

### 1. dao_pools_snapshot.py → lp_position_snapshots

**Проблема**: `dao_pools_snapshot.py` НЕ МОЖЕТ работать без данных позиций

**Код зависимости**:
```python
# dao_pools_snapshot.py:608-609
our_positions = await self.load_our_positions_from_supabase()

# Без этих данных невозможно рассчитать:
# - our_position_value_usd
# - lp_gap_usd  
# - Инвестиционные приоритеты
```

**Решение**: Обязательное выполнение сбора позиций ПЕРЕД сбором пулов

### 2. multichain_report_generator.py → обе таблицы

**Зависимости**:
- `lp_position_snapshots` - для данных позиций
- `lp_pool_snapshots` - для контекста пулов и TVL

### 3. Последовательность в Scheduler

**Критическое требование**:
```python
# ✅ ПРАВИЛЬНАЯ последовательность:
# 1. Сначала позиции (каждые 4 часа)
'ethereum_positions_analysis': "0 */4 * * *"
'base_positions_analysis': "0 2,6,10,14,18,22 * * *"

# 2. Потом пулы (2 раза в день, ПОСЛЕ позиций)  
'dao_pools_snapshots': "30 9,21 * * *"

# 3. Потом отчеты (используют ВСЕ данные)
'multichain_telegram_report': "0 12,20 * * *"
```

---

## ⚠️ Обработка ошибок

### 1. RPC Errors

**Стратегия**: Retry с exponential backoff

```python
# unified_positions_analyzer.py
async def call_with_retry(rpc_call, max_retries=3):
    for attempt in range(max_retries):
        try:
            return await rpc_call()
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            
            wait_time = 2 ** attempt  # Exponential backoff
            await asyncio.sleep(wait_time)
```

### 2. API Rate Limits

**GeckoTerminal API**: Ограничение запросов

```python
# dao_pools_snapshot.py
async def get_pool_data_from_geckoterminal(pool_address):
    for attempt in range(3):
        try:
            response = await session.get(url)
            if response.status == 429:  # Rate limit
                wait_time = 2 ** attempt
                await asyncio.sleep(wait_time)
                continue
            return await response.json()
        except Exception as e:
            if attempt == 2:
                # Возвращаем пул с ошибкой, но не прерываем обработку
                return {
                    'dex': f'api_error_{response.status}',
                    'tvl_usd': 0
                }
```

### 3. Database Errors

**Supabase Connection**: Graceful degradation

```python
# database_handler.py  
def save_with_fallback(data):
    try:
        return supabase_handler.save_data(data)
    except Exception as e:
        logger.error(f"Supabase save failed: {e}")
        # Fallback: сохранение в локальный файл
        save_to_local_backup(data)
        return None
```

### 4. Missing Data Handling

**Позиции отсутствуют**:
```python
# dao_pools_snapshot.py
our_positions = await load_our_positions_from_supabase()
if not our_positions:
    logger.warning("No position data available - using defaults")
    our_positions = {}  # Продолжаем с пустыми позициями
```

---

## ⚙️ Конфигурация

### 1. Environment Variables

**Обязательные переменные**:
```bash
# Supabase
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-service-role-key

# RPC Endpoints  
ETHEREUM_RPC_URL=https://eth-mainnet.g.alchemy.com/v2/your-key
BASE_RPC_URL=https://base-mainnet.g.alchemy.com/v2/your-key  
HELIUS_RPC_URL=https://rpc.helius.xyz/?api-key=your-key

# Telegram
TELEGRAM_BOT_TOKEN=your-bot-token
TELEGRAM_CHAT_ID=your-chat-id

# Кошельки
TARGET_WALLET_ADDRESS=BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD  # Solana
ETHEREUM_WALLET_ADDRESS=0x31AAc4021540f61fe20c3dAffF64BA6335396850    # ETH/Base
```

### 2. tokens_pools_config.json

**Структура**:
```json
{
  "dao_tokens": {
    "BIO": {
      "symbol": "BIO",
      "name": "BIO Protocol",
      "addresses": {
        "solana": "BIOhBJbeCx9xTqbLMsYhNVv1CJjUhzqvNVxR5i2gwzWc",
        "ethereum": "0x1234...",
        "base": "0x5678..."
      },
      "coingecko_id": "bio-protocol"
    }
  },
  "monitored_pools": {
    "solana": [
      {
        "pool_address": "ABC123...",
        "pool_name": "BIO/VITA",
        "tokens": ["BIO", "VITA"]
      }
    ],
    "ethereum": [...],
    "base": [...]
  }
}
```

### 3. Network Configurations

```python
# unified_positions_analyzer.py
NETWORK_CONFIGS = {
    'ethereum': {
        'rpc_url': os.getenv('ETHEREUM_RPC_URL'),
        'nft_manager': '0xC36442b4a4522E871399CD717aBDD847Ab11FE88',
        'subgraph_url': 'https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3'
    },
    'base': {
        'rpc_url': os.getenv('BASE_RPC_URL'), 
        'nft_manager': '0x03a520b32C04BF3bEEf7BF5d1088b7a39dCbF5Ed',
        'subgraph_url': 'https://api.studio.thegraph.com/query/3/base-v3/version/latest'
    }
}
```

---

## 📊 Мониторинг и алертинг

### 1. Health Checks

**Системные проверки каждые 5 минут**:
```python
# scheduler.py:942-987
async def perform_health_check():
    # 1. Проверка файлов
    core_files = [
        'pool_analyzer.py', 'dao_pools_snapshot.py',
        'unified_positions_analyzer.py', 'tokens_pools_config.json'
    ]
    missing_files = [f for f in core_files if not os.path.exists(f)]
    
    # 2. Проверка Telegram подключения
    telegram_status = await telegram.test_connection()
    
    # 3. Проверка Supabase подключения  
    supabase_status = supabase_handler.is_connected()
    
    # 4. Отправка алертов при проблемах
    if missing_files or not telegram_status or not supabase_status:
        await alerting_system.send_system_health_alert()
```

### 2. Out-of-Range Positions Monitoring

**Проверка каждые 30 минут**:
```python
# scheduler.py:988-1008
async def check_out_of_range_positions():
    # Умная логика: алерт только при изменениях
    alert_sent = await alerting_system.check_out_of_range_positions()
```

### 3. Task Execution Monitoring

**Отслеживание выполнения задач**:
```python
# scheduler.py:290-291
async def _execute_task(task):
    try:
        task.last_status = TaskStatus.RUNNING
        await task.function()
        task.last_status = TaskStatus.SUCCESS
        task.execution_count += 1
    except Exception as e:
        task.last_status = TaskStatus.FAILED
        task.last_error = str(e)
        await alerting_system.send_task_failure_alert(task)
```

### 4. Performance Metrics

**Отслеживание ключевых метрик**:
- **Execution Time**: Время выполнения каждой задачи
- **Data Volume**: Количество обработанных позиций/пулов
- **Error Rate**: Процент неудачных запросов к API/RPC
- **Data Freshness**: Время последнего обновления данных

---

## 🚀 Deployment Readiness

### Checklist перед деплоем:

**✅ Компоненты готовы**:
- [x] Все 3 сети собирают данные
- [x] Supabase integration работает
- [x] Telegram отчеты отправляются
- [x] Scheduler настроен
- [x] Error handling реализован

**✅ Данные валидны**:
- [x] lp_position_snapshots: 23+ позиций
- [x] dao_pool_snapshots: 48 пулов (20 ETH + 9 Base + 19 SOL)
- [x] Исторические данные рассчитываются
- [x] Метрики корректны

**✅ Мониторинг активен**:
- [x] Health checks работают
- [x] Alerting настроен
- [x] Performance tracking включен

**Система готова к полной замене старого `pool_analyzer.py`!** 