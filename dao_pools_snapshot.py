#!/usr/bin/env python3
"""
DAO Pools Snapshot Generator (FIXED)
Правильная логика:
1. Ищем пулы через GeckoTerminal API  
2. Из Supabase берем только НАШИ ПОЗИЦИИ
3. Если позиции нет -> target_lp_value = 1% FDV для BIO пар
"""

import asyncio
import httpx
import csv
import json
import sys
import os
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from decimal import Decimal, getcontext

# Настройка точности
getcontext().prec = 78

# Supabase handler
try:
    from database_handler import supabase_handler
    SUPABASE_ENABLED = supabase_handler is not None
    if SUPABASE_ENABLED:
        print("✅ Supabase handler подключен")
except ImportError:
    print("⚠️ Supabase handler недоступен")
    supabase_handler = None
    SUPABASE_ENABLED = False

class DAOPoolsSnapshotGenerator:
    def __init__(self):
        self.target_fdv_percentage = 1.0  # 1% от FDV как таргет
        
        # Загружаем белый список известных адресов пулов
        self._load_known_pool_addresses()
    
    def _load_known_pool_addresses(self):
        """Загружает белый список известных адресов пулов из tokens_pools_config.json"""
        try:
            with open('tokens_pools_config.json', 'r') as f:
                config = json.load(f)
                
            self.known_pool_addresses = set()
            
            # Собираем все известные адреса пулов
            for network, pools in config.get('pools', {}).items():
                for pool in pools:
                    address = pool.get('address', '').strip()
                    if address:
                        self.known_pool_addresses.add(address)
                        
            print(f"📋 Загружено {len(self.known_pool_addresses)} известных адресов пулов из конфига")
            
        except Exception as e:
            print(f"⚠️ Ошибка загрузки конфига: {e}")
            self.known_pool_addresses = set()
    
    def _is_suspicious_token(self, token: str) -> tuple:
        """Проверяет токен на подозрительность"""
        token = token.strip()
        
        # 1. Китайские символы и эмодзи
        if any('\u4e00' <= char <= '\u9fff' for char in token):
            return True, "китайские_символы"
            
        # 2. Известные скам токены
        scam_tokens = {
            'SHEGEN', 'GRIFFAIN', 'TrackedBio', 'saint', 'michi', '$michi',
            'JupSOL', 'JUP', 'PNET', 'PEPE', 'DOGE', 'SHIB'
        }
        if token in scam_tokens:
            return True, f"скам_токен_{token}"
            
        # 3. Подозрительные паттерны
        suspicious_patterns = ['track', 'fake', 'test', 'pump', 'dump', 'scam']
        token_lower = token.lower()
        for pattern in suspicious_patterns:
            if pattern in token_lower:
                return True, f"подозрительный_паттерн_{pattern}"
                
        # 4. Слишком длинные названия (> 15 символов)
        if len(token) > 15:
            return True, "слишком_длинное_название"
            
        return False, ""
    
    def _is_valid_pool_pair(self, pool_name: str, pool_address: str = '', dex_id: str = '', network: str = '') -> bool:
        """
        МНОГОУРОВНЕВАЯ ВАЛИДАЦИЯ ПУЛОВ:
        
        1. Структурная проверка (формат пары)
        2. Проверка на скам/подозрительные токены
        3. Белый список основных токенов 
        3.5. Строгая проверка для проблемных токенов (URO/RIF)
        4. Дедупликация одинаковых пар
        """
        if not pool_name or '/' not in pool_name:
            return False
            
        # Разделяем токены в паре
        tokens = pool_name.split('/')
        if len(tokens) != 2:
            return False
            
        token1, token2 = [t.strip() for t in tokens]
        
        # 1. БЕЛЫЙ СПИСОК РАЗРЕШЕННЫХ ТОКЕНОВ
        allowed_tokens = {
            # Основные стейблкоины и базовые токены
            'WETH', 'SOL', 'BIO', 'USDC', 'USDT', 'ETH', 'WBTC',
            
            # Наши DAO токены (из tokens_pools_config.json)
            'VITA', 'HAIR', 'NEURON', 'ATH', 'GROW', 'CRYO', 'QBIO', 'PSY',
            'SPINE', 'CURES', 'RIF', '$RIF', 'URO', '$URO', 'MYCO',
            
            # Связанные/партнерские токены (только проверенные!)
            'VITA-FAST', 'VITARNA', 'POO'
        }
        
        # 2. ПРОВЕРКА НА СКАМ/ПОДОЗРИТЕЛЬНЫЕ ТОКЕНЫ
        for token in [token1, token2]:
            is_suspicious, reason = self._is_suspicious_token(token)
            if is_suspicious:
                print(f"⚠️ Отклонен пул {pool_name}: подозрительный токен {token} ({reason})")
                return False
                
        # 3. ПРОВЕРКА БЕЛОГО СПИСКА
        token1_valid = token1 in allowed_tokens
        token2_valid = token2 in allowed_tokens
        
        if not (token1_valid and token2_valid):
            print(f"⚠️ Отклонен пул {pool_name}: токены не в белом списке ({token1}: {token1_valid}, {token2}: {token2_valid})")
            return False
            
        # 3.5. СТРОГАЯ ПРОВЕРКА ТОЛЬКО ДЛЯ ПРОБЛЕМНЫХ ТОКЕНОВ (URO/RIF)
        # Эти токены привлекают много скамеров, поэтому для них особые правила
        problematic_tokens = {'RIF', '$RIF', 'URO', '$URO'}
        
        if any(token in problematic_tokens for token in [token1, token2]):
            # Для URO/RIF разрешены только пары с основными токенами
            safe_pairs_for_problematic = {'SOL', 'BIO', 'WETH', 'ETH', 'RIF', '$RIF', 'URO', '$URO'}
            
            if not (token1 in safe_pairs_for_problematic and token2 in safe_pairs_for_problematic):
                print(f"⚠️ Отклонен пул {pool_name}: для {token1}/{token2} разрешены только основные пары")
                return False
                
            # Блокируем стейблкоины для проблемных токенов
            stablecoins = {'USDT', 'USDC'}
            if any(token in stablecoins for token in [token1, token2]):
                print(f"⚠️ Отклонен пул {pool_name}: пары со стейблкоинами подозрительны для {token1}/{token2}")
                return False
                
        # 4. ДЕДУПЛИКАЦИЯ: нормализуем порядок токенов + сеть для проверки дубликатов  
        normalized_pair = tuple(sorted([token1, token2]) + [network])
        if not hasattr(self, '_seen_pairs'):
            self._seen_pairs = set()
            
        if normalized_pair in self._seen_pairs:
            print(f"⚠️ Отклонен пул {pool_name} ({network}): дубликат пары {normalized_pair}")
            return False
            
        self._seen_pairs.add(normalized_pair)
        
        return True
    
    def _standardize_pool_name(self, raw_name: str) -> str:
        """
        Стандартизирует название пула из GeckoTerminal API
        
        Примеры:
        "HAIR / WETH 1%" -> "HAIR/WETH"
        "$RIF / SOL" -> "$RIF/SOL"
        "BIO/MYCO" -> "BIO/MYCO" (остается как есть)
        """
        if not raw_name or raw_name == 'Unknown':
            return raw_name
            
        # Убираем проценты и информацию о комиссиях
        name = raw_name.split(' 0.')[0]  # Убираем " 0.3%" и т.д.
        name = name.split(' 1%')[0]      # Убираем " 1%"
        name = name.split(' %')[0]       # Убираем другие проценты
        
        # Стандартизируем разделитель: заменяем " / " на "/"
        name = name.replace(' / ', '/')
        name = name.replace('/ ', '/')
        name = name.replace(' /', '/')
        
        # Убираем лишние пробелы
        parts = name.split('/')
        clean_parts = [part.strip() for part in parts]
        
        standardized = '/'.join(clean_parts)
        
        # Проверяем что результат валидный
        if '/' not in standardized or len(standardized.split('/')) != 2:
            print(f"⚠️ Странное название пула: '{raw_name}' -> '{standardized}'")
            
        return standardized
        
    async def load_pools_from_config(self) -> List[Dict[str, Any]]:
        """Загрузить все пулы напрямую из tokens_pools_config.json"""
        try:
            with open('tokens_pools_config.json', 'r') as f:
                config = json.load(f)
            
            all_pools = []
            
            # Собираем все пулы из всех сетей
            for network, pools in config.get('pools', {}).items():
                for pool_config in pools:
                    pool_info = {
                        'pool_name': pool_config['name'],
                        'pool_address': pool_config['address'],
                        'network': network,
                        'protocol': pool_config.get('protocol', 'unknown'),
                        'fee_tier': pool_config.get('fee_tier', 0),
                        'token0': pool_config.get('token0', ''),
                        'token1': pool_config.get('token1', ''),
                        # Эти поля будут заполнены через API
                        'tvl_usd': 0,
                        'volume_24h_usd': 0,
                        'dex': 'unknown'
                    }
                    all_pools.append(pool_info)
            
            print(f"📊 Загружено {len(all_pools)} пулов из конфига")
            return all_pools
            
        except Exception as e:
            print(f"❌ Ошибка загрузки пулов из конфига: {e}")
            return []
    
    async def load_dao_tokens_for_calculations(self) -> Dict[str, Dict[str, Any]]:
        """Загрузить DAO токены для расчетов FDV и метрик"""
        try:
            with open('tokens_pools_config.json', 'r') as f:
                config = json.load(f)
            
            dao_tokens = {}
            
            # Собираем все DAO токены (исключаем служебные)
            excluded_symbols = {'BIO', 'WETH', 'SOL'}
            
            for network, tokens in config['tokens'].items():
                for token in tokens:
                    symbol = token['symbol']
                    
                    if symbol in excluded_symbols:
                        continue
                    
                    if symbol not in dao_tokens:
                        dao_tokens[symbol] = {
                            'symbol': symbol,
                            'name': token['name'],
                            'coingecko_id': token['coingecko_id'],
                            'addresses': {},
                            'fdv_usd': 0,
                            'price_usd': 0
                        }
                    
                    dao_tokens[symbol]['addresses'][network] = token['address']
            
            # Загружаем FDV и цены через GeckoTerminal API
            await self._fetch_missing_fdv_from_api(dao_tokens)
            
            print(f"📊 Загружено {len(dao_tokens)} DAO токенов для расчетов")
            return dao_tokens
            
        except Exception as e:
            print(f"❌ Ошибка загрузки токенов для расчетов: {e}")
            return {}
    


    async def _get_bio_price_from_api(self) -> float:
        """Получить актуальную цену BIO через GeckoTerminal API"""
        bio_addresses = {
            'ethereum': '0xcb1592591996765ec0efc1f92599a19767ee5ffa',
            'base': '0x226a2fa2556c48245e57cd1cba4c6c9e67077dd2',
            'solana': 'bioJ9JTqW62MLz7UKHU69gtKhPpGi1BQhccj2kmSvUJ'
        }
        
        # Пробуем получить цену с разных сетей (начинаем с Ethereum как самой ликвидной)
        for network, address in bio_addresses.items():
            try:
                async with httpx.AsyncClient() as client:
                    url = f'https://api.geckoterminal.com/api/v2/networks/{network}/tokens/{address}'
                    response = await client.get(url, timeout=10)
                    
                    if response.status_code == 200:
                        data = response.json()
                        attrs = data.get('data', {}).get('attributes', {})
                        
                        price_usd = attrs.get('price_usd')
                        if price_usd and float(price_usd) > 0:
                            price = float(price_usd)
                            print(f"💰 Актуальная цена BIO: ${price:.4f} (из {network})")
                            return price
                            
                    await asyncio.sleep(0.2)  # Задержка между запросами
                    
            except Exception as e:
                print(f"⚠️ Ошибка получения цены BIO из {network}: {e}")
                continue
        
        # Fallback - используем старую цену из env или дефолт
        fallback_price = float(os.getenv('BIO_PRICE_USD', '0.07'))
        print(f"⚠️ Не удалось получить цену BIO из API, используем fallback: ${fallback_price}")
        return fallback_price

    async def _fetch_missing_fdv_from_api(self, dao_tokens: Dict[str, Dict[str, Any]]):
        """Получить актуальные FDV через GeckoTerminal API (максимальный из всех сетей)"""
        print("🔍 Получаем актуальные FDV через GeckoTerminal API...")
        
        async with httpx.AsyncClient() as client:
            for token_symbol, token_info in dao_tokens.items():
                # ВСЕГДА обновляем FDV для получения актуальных данных
                best_fdv = 0
                best_price = 0
                best_network = None
                
                # Проверяем все сети и выбираем максимальный FDV
                for network, address in token_info['addresses'].items():
                    if not address:
                        continue
                        
                    try:
                        network_map = {'ethereum': 'eth', 'base': 'base', 'solana': 'solana'}
                        network_id = network_map.get(network, network)
                        
                        url = f'https://api.geckoterminal.com/api/v2/networks/{network_id}/tokens/{address}'
                        response = await client.get(url, timeout=10)
                        
                        if response.status_code == 200:
                            data = response.json()
                            attrs = data.get('data', {}).get('attributes', {})
                            
                            fdv_usd = attrs.get('fdv_usd')
                            price_usd = attrs.get('price_usd')
                            
                            if fdv_usd and float(fdv_usd) > best_fdv:
                                best_fdv = float(fdv_usd)
                                best_network = network
                                if price_usd:
                                    best_price = float(price_usd)
                        
                        # Задержка между запросами
                        await asyncio.sleep(0.3)
                        
                    except Exception as e:
                        print(f"   ⚠️ {token_symbol} ({network}): {e}")
                
                # Сохраняем лучшие данные
                if best_fdv > 0:
                    token_info['fdv_usd'] = best_fdv
                    print(f"   ✅ {token_symbol}: FDV ${best_fdv:,.0f} (из {best_network})")
                    
                    if best_price > 0 and token_info.get('price_usd', 0) <= 0:
                        token_info['price_usd'] = best_price
                else:
                    print(f"   ⚠️ {token_symbol}: не удалось получить FDV")
    
    async def load_our_positions_from_supabase(self) -> Dict[str, Dict[str, Any]]:
        """Загрузить наши позиции из Supabase lp_position_snapshots"""
        if not SUPABASE_ENABLED or not supabase_handler or not supabase_handler.is_connected():
            print("⚠️ Supabase недоступен для позиций")
            return {}
        
        print("🔍 Загружаем наши позиции из Supabase...")
        
        try:
            # Получаем последние позиции за последние 7 дней (для полноты данных)
            week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
            
            result = supabase_handler.client.table('lp_position_snapshots').select('*').gte(
                'created_at', week_ago
            ).order('created_at', desc=True).execute()
            
            if not result.data:
                print("   ⚠️ Нет данных о позициях в Supabase")
                return {}
            
            # Группируем по pool_id + network, берем ТОЛЬКО ПОСЛЕДНИЕ по дате
            positions_by_pool = {}
            for pos in result.data:
                # Используем pool_id (уже без префиксов) и network из данных позиции
                pool_address = pos.get('pool_id', '')  # Теперь это чистый адрес
                network = pos.get('network', 'solana')  # Поле network добавлено в таблицу
                pool_key = f"{pool_address.lower()}_{network}"
                created_at = pos.get('created_at', '')
                
                # Берем только самую свежую запись для каждого пула
                if pool_key not in positions_by_pool or created_at > positions_by_pool[pool_key]['created_at']:
                    positions_by_pool[pool_key] = {
                        'pool_address': pool_address,  # Чистый адрес из pool_id
                        'network': network,  # Поле network
                        'pool_name': pos.get('pool_name', ''),
                        'total_value_usd': float(pos.get('position_value_usd', 0)),  # Исправлено название поля
                        'created_at': created_at
                    }
            
            print(f"   ✅ Загружено {len(positions_by_pool)} уникальных позиций")
            return positions_by_pool
            
        except Exception as e:
            print(f"   ❌ Ошибка загрузки позиций из Supabase: {e}")
            return {}
    
    async def get_pool_data_from_geckoterminal(self, pool_info: Dict[str, Any], client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
        """Получить данные пула по его адресу из GeckoTerminal API с retry логикой"""
        network_map = {
            'ethereum': 'eth',
            'base': 'base',
            'solana': 'solana'
        }
        
        network = pool_info['network']
        pool_address = pool_info['pool_address']
        network_id = network_map.get(network, network)
        
        url = f'https://api.geckoterminal.com/api/v2/networks/{network_id}/pools/{pool_address}'
        
        # Retry логика для 429 ошибок
        max_retries = 3
        base_delay = 2.0  # Увеличенная базовая задержка
        
        for attempt in range(max_retries):
            try:
                response = await client.get(url, timeout=20)  # Увеличенный timeout
                
                if response.status_code == 200:
                    data = response.json()
                    pool_attrs = data.get('data', {}).get('attributes', {})
                    
                    # Извлекаем актуальные данные
                    reserve_usd = pool_attrs.get('reserve_in_usd', 0)
                    tvl = float(reserve_usd) if reserve_usd else 0
                    
                    volume_24h = 0
                    try:
                        volume_data = pool_attrs.get('volume_usd', {})
                        if volume_data:
                            volume_24h = float(volume_data.get('h24', 0) or 0)
                    except:
                        pass
                    
                    # Обновляем данные пула
                    updated_pool = pool_info.copy()
                    updated_pool.update({
                        'tvl_usd': tvl,
                        'volume_24h_usd': volume_24h,
                        'dex': pool_attrs.get('dex_id', 'unknown'),
                        'fee_percent': pool_attrs.get('pool_fee_percent', 0),
                    })
                    
                    print(f"      ✅ {updated_pool['pool_name']} ({network}): TVL ${tvl:,.0f}, Volume ${volume_24h:,.0f}")
                    return updated_pool
                    
                elif response.status_code == 429:
                    # Rate limiting - retry с экспоненциальной задержкой
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        print(f"      🔄 {pool_info['pool_name']} ({network}): Rate limit, retry {attempt + 1}/{max_retries} через {delay}s")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        print(f"      ⚠️ {pool_info['pool_name']} ({network}): Rate limit после {max_retries} попыток - сохраняем с API_ERROR")
                        # Сохраняем пул с меткой что данные недоступны из-за API ошибки
                        updated_pool = pool_info.copy()
                        updated_pool.update({
                            'tvl_usd': 0,
                            'volume_24h_usd': 0,
                            'dex': 'api_error_429',  # Метка что это ошибка API
                            'fee_percent': 0,
                        })
                        return updated_pool
                        
                elif response.status_code == 404:
                    print(f"      ⚠️ {pool_info['pool_name']} ({network}): Пул не найден (404) - ПРОПУСКАЕМ")
                    return None  # Пропускаем несуществующие пулы
                    
                else:
                    print(f"      ⚠️ {pool_info['pool_name']} ({network}): API вернул {response.status_code} - сохраняем с API_ERROR")
                    # Сохраняем пул с меткой что данные недоступны из-за API ошибки
                    updated_pool = pool_info.copy()
                    updated_pool.update({
                        'tvl_usd': 0,
                        'volume_24h_usd': 0,
                        'dex': f'api_error_{response.status_code}',  # Метка с кодом ошибки
                        'fee_percent': 0,
                    })
                    return updated_pool
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"      🔄 {pool_info['pool_name']} ({network}): Ошибка {e}, retry {attempt + 1}/{max_retries} через {delay}s")
                    await asyncio.sleep(delay)
                    continue
                else:
                    print(f"      ❌ {pool_info['pool_name']} ({network}): Ошибка после {max_retries} попыток: {e} - сохраняем с API_ERROR")
                    # Сохраняем пул с меткой что данные недоступны из-за ошибки
                    updated_pool = pool_info.copy()
                    updated_pool.update({
                        'tvl_usd': 0,
                        'volume_24h_usd': 0,
                        'dex': 'api_error_exception',  # Метка что это исключение
                        'fee_percent': 0,
                    })
                    return updated_pool
        
        return None  # Если дошли сюда - все попытки неудачны
    
    def calculate_pool_dao_metrics(self, pool_data: Dict[str, Any], dao_token_info: Dict[str, Any], our_positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Рассчитать метрики пула для DAO токена"""
        
        # Определяем какой токен в пуле является DAO токеном
        dao_token_symbol = dao_token_info['symbol']
        pool_name = pool_data['pool_name'].upper()
        
        # Простая проверка по названию пула
        is_dao_in_pool = dao_token_symbol.upper() in pool_name
        
        # Проверяем является ли пул парой с BIO
        is_bio_pair = (
            'BIO' in pool_name and dao_token_symbol.upper() in pool_name
        )
        
        # Рассчитываем количество DAO токена в пуле (приблизительно)
        tvl_usd = pool_data['tvl_usd']
        dao_token_price = dao_token_info.get('price_usd', 0)
        
        if dao_token_price > 0 and is_dao_in_pool:
            # Предполагаем 50/50 распределение в пуле
            dao_token_value_in_pool = tvl_usd / 2
            dao_token_amount_in_pool = dao_token_value_in_pool / dao_token_price
        else:
            dao_token_value_in_pool = 0
            dao_token_amount_in_pool = 0
        
        # Рассчитываем процент от FDV
        dao_token_fdv_percentage = 0
        if dao_token_info.get('fdv_usd', 0) > 0:
            dao_token_fdv_percentage = (dao_token_value_in_pool / dao_token_info['fdv_usd']) * 100
        
        # Получаем стоимость наших позиций в этом пуле
        pool_key = f"{pool_data['pool_address'].lower()}_{pool_data['network']}"
        our_position_value = 0
        if pool_key in our_positions:
            our_position_value = our_positions[pool_key]['total_value_usd']
        
        # Рассчитываем целевую стоимость LP для BIO пар
        target_lp_value_usd = 0
        if is_bio_pair and dao_token_info.get('fdv_usd', 0) > 0:
            target_lp_value_usd = dao_token_info['fdv_usd'] * (self.target_fdv_percentage / 100)
        
        # Рассчитываем разрыв (gap)
        lp_gap_usd = target_lp_value_usd - our_position_value
        
        return {
            'is_bio_pair': is_bio_pair,
            'our_position_value_usd': our_position_value,
            'target_lp_value_usd': target_lp_value_usd,
            'lp_gap_usd': lp_gap_usd
        }
    
    async def generate_snapshot(self) -> List[Dict[str, Any]]:
        """Генерировать полный снапшот всех пулов из конфига"""
        print("🚀 Начинаем генерацию снапшота пулов из конфига...")
        
        # Получаем актуальную цену BIO
        bio_price = await self._get_bio_price_from_api()
        
        # Загружаем все пулы из конфига
        all_pools = await self.load_pools_from_config()
        if not all_pools:
            raise Exception("Не удалось загрузить пулы из конфига")
        
        # Загружаем DAO токены для расчетов
        dao_tokens = await self.load_dao_tokens_for_calculations()
        
        # Загружаем наши позиции из Supabase
        our_positions = await self.load_our_positions_from_supabase()
        
        all_pool_snapshots = []
        snapshot_timestamp = datetime.now(timezone.utc)
        
        print(f"\n🔍 Обрабатываем {len(all_pools)} пулов из конфига...")
        
        async with httpx.AsyncClient() as client:
            # Проходим по каждому пулу из конфига
            for i, pool_info in enumerate(all_pools, 1):
                print(f"\n📊 [{i}/{len(all_pools)}] {pool_info['pool_name']} ({pool_info['network']})")
                
                # Получаем актуальные данные пула
                updated_pool = await self.get_pool_data_from_geckoterminal(pool_info, client)
                
                # Пропускаем пул только если он действительно не существует (404)
                if updated_pool is None:
                    print(f"      ⏭️ Пропускаем {pool_info['pool_name']} ({pool_info['network']}) - пул не существует (404)")
                    continue
                
                # Находим соответствующий DAO токен для расчетов
                dao_token_info = self._find_dao_token_for_pool(updated_pool, dao_tokens)
                
                if dao_token_info:
                    # Рассчитываем метрики DAO для пула
                    dao_metrics = self.calculate_pool_dao_metrics(updated_pool, dao_token_info, our_positions)
                    token_symbol = dao_token_info['symbol']
                    token_fdv_usd = dao_token_info['fdv_usd']
                    token_price_usd = dao_token_info['price_usd']
                else:
                    # Если DAO токен не найден, создаем базовые метрики
                    dao_metrics = self._create_basic_pool_metrics(updated_pool, our_positions)
                    token_symbol = self._extract_token_from_pool_name(updated_pool['pool_name'])
                    token_fdv_usd = 0
                    token_price_usd = 0
                
                # Создаем полную запись снапшота
                snapshot = {
                    'snapshot_timestamp': snapshot_timestamp.isoformat(),
                    'token_symbol': token_symbol,
                    'token_address': self._get_token_address_for_pool(updated_pool, dao_tokens),
                    'network': updated_pool['network'],
                    'pool_name': updated_pool['pool_name'],
                    'pool_address': updated_pool['pool_address'],
                    'dex': updated_pool['dex'],
                    'fee_percent': updated_pool.get('fee_percent', 0),
                    'tvl_usd': updated_pool['tvl_usd'],
                    'volume_24h_usd': updated_pool['volume_24h_usd'],
                    'token_price_usd': token_price_usd,
                    'token_fdv_usd': token_fdv_usd,
                    'is_bio_pair': dao_metrics['is_bio_pair'],
                    'our_position_value_usd': dao_metrics['our_position_value_usd'],
                    'target_lp_value_usd': dao_metrics['target_lp_value_usd'],
                    'lp_gap_usd': dao_metrics['lp_gap_usd'],
                    'bio_price_usd': bio_price,
                    'target_fdv_percentage': self.target_fdv_percentage
                }
                
                all_pool_snapshots.append(snapshot)
                
                # Увеличенная задержка между запросами для избежания rate limiting
                await asyncio.sleep(1.0)  # Увеличено с 0.2 до 1.0 секунды
        
        # Добавляем виртуальные BIO пары для отсутствующих пар
        virtual_bio_pairs = self._create_virtual_bio_pairs(dao_tokens, bio_price, all_pool_snapshots)
        all_pool_snapshots.extend(virtual_bio_pairs)
        
        # Рассчитываем исторические изменения для каждого токена
        print(f"\n📊 Рассчитываем исторические изменения...")
        
        # Группируем снапшоты по токенам для расчета агрегированных метрик
        tokens_data = {}
        for snapshot in all_pool_snapshots:
            token_symbol = snapshot['token_symbol']
            if token_symbol not in tokens_data:
                tokens_data[token_symbol] = {
                    'current_price': snapshot['token_price_usd'],
                    'total_tvl': 0,
                    'snapshots': []
                }
            
            # Агрегируем TVL (исключаем виртуальные пулы)
            if snapshot['pool_address'] != '':
                tokens_data[token_symbol]['total_tvl'] += snapshot['tvl_usd']
            
            tokens_data[token_symbol]['snapshots'].append(snapshot)

        # Рассчитываем исторические изменения для каждого токена
        for token_symbol, token_data in tokens_data.items():
            current_price = token_data['current_price']
            current_tvl = token_data['total_tvl']
            
            print(f"      📈 {token_symbol}: цена=${current_price:.6f}, TVL=${current_tvl:,.0f}")
            
            # Получаем изменения цены
            price_changes = self._calculate_price_changes(token_symbol, current_price)
            
            # Получаем изменения TVL  
            tvl_changes = self._calculate_tvl_changes(token_symbol, current_tvl)
            
            # Применяем изменения ко всем снапшотам этого токена
            for snapshot in token_data['snapshots']:
                snapshot.update(price_changes)
                snapshot.update(tvl_changes)
        
        print(f"\n✅ Сгенерировано {len(all_pool_snapshots)} снапшотов пулов ({len(all_pool_snapshots) - len(virtual_bio_pairs)} реальных + {len(virtual_bio_pairs)} виртуальных)")
        print(f"📊 Рассчитаны исторические изменения для {len(tokens_data)} токенов")
        return all_pool_snapshots
    
    def _find_dao_token_for_pool(self, pool_info: Dict[str, Any], dao_tokens: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Найти DAO токен для пула по названию"""
        pool_name = pool_info['pool_name'].upper()
        
        # Проходим по всем DAO токенам и ищем совпадение в названии пула
        for token_symbol, token_info in dao_tokens.items():
            if token_symbol.upper() in pool_name:
                return token_info
        
        return None
    
    def _create_basic_pool_metrics(self, pool_info: Dict[str, Any], our_positions: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Создать базовые метрики для пула без DAO токена"""
        
        # Получаем стоимость наших позиций в этом пуле
        pool_key = f"{pool_info['pool_address'].lower()}_{pool_info['network']}"
        our_position_value = 0
        if pool_key in our_positions:
            our_position_value = our_positions[pool_key]['total_value_usd']
        
        # Проверяем является ли пул парой с BIO
        pool_name = pool_info['pool_name'].upper()
        is_bio_pair = 'BIO' in pool_name
        
        return {
            'is_bio_pair': is_bio_pair,
            'our_position_value_usd': our_position_value,
            'target_lp_value_usd': 0,
            'lp_gap_usd': 0
        }
    
    def _extract_token_from_pool_name(self, pool_name: str) -> str:
        """Извлечь основной токен из названия пула"""
        if '/' in pool_name:
            tokens = pool_name.split('/')
            # Возвращаем первый токен (не BIO/WETH/SOL/USDC)
            for token in tokens:
                token = token.strip()
                if token.upper() not in {'BIO', 'WETH', 'ETH', 'SOL', 'USDC', 'USDT'}:
                    return token
            return tokens[0].strip()
        return pool_name
    
    def _get_token_address_for_pool(self, pool_info: Dict[str, Any], dao_tokens: Dict[str, Dict[str, Any]]) -> str:
        """Получить адрес токена для пула"""
        dao_token_info = self._find_dao_token_for_pool(pool_info, dao_tokens)
        if dao_token_info:
            network = pool_info['network']
            return dao_token_info['addresses'].get(network, '')
        return pool_info.get('token0', '')  # Возвращаем token0 как fallback
    
    def _calculate_price_changes(self, token_symbol: str, current_price: float) -> Dict[str, float]:
        """Рассчитать изменения цены токена за 24ч и 7д"""
        changes = {
            'price_change_24h_percent': 0.0,
            'price_change_7d_percent': 0.0
        }
        
        try:
            # Цена 24 часа назад
            price_24h = supabase_handler.get_historical_token_price(token_symbol, 1)
            if price_24h and price_24h > 0:
                changes['price_change_24h_percent'] = ((current_price - price_24h) / price_24h) * 100
            
            # Цена 7 дней назад
            price_7d = supabase_handler.get_historical_token_price(token_symbol, 7)
            if price_7d and price_7d > 0:
                changes['price_change_7d_percent'] = ((current_price - price_7d) / price_7d) * 100
                
        except Exception as e:
            print(f"⚠️ Ошибка расчета изменений цены для {token_symbol}: {e}")
        
        return changes

    def _calculate_tvl_changes(self, token_symbol: str, current_total_tvl: float) -> Dict[str, float]:
        """Рассчитать изменение общего TVL токена за 7 дней"""
        changes = {
            'tvl_change_7d_percent': 0.0
        }
        
        try:
            tvl_7d = supabase_handler.get_historical_token_tvl(token_symbol, 7)
            if tvl_7d and tvl_7d > 0:
                changes['tvl_change_7d_percent'] = ((current_total_tvl - tvl_7d) / tvl_7d) * 100
                
        except Exception as e:
            print(f"⚠️ Ошибка расчета изменений TVL для {token_symbol}: {e}")
        
        return changes
    
    def _create_virtual_bio_pairs(self, dao_tokens: Dict[str, Dict[str, Any]], bio_price: float, existing_snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Создать виртуальные записи для отсутствующих BIO пар"""
        
        # Собираем существующие BIO пары по токенам и сетям
        existing_bio_pairs = set()
        for snapshot in existing_snapshots:
            if snapshot['is_bio_pair']:
                token_symbol = snapshot['token_symbol']
                network = snapshot['network']
                existing_bio_pairs.add((token_symbol, network))
        
        virtual_pairs = []
        snapshot_timestamp = datetime.now(timezone.utc)
        
        print(f"\n🔍 Проверяем отсутствующие BIO пары...")
        
        for token_symbol, token_info in dao_tokens.items():
            if token_info.get('fdv_usd', 0) <= 0:
                continue  # Пропускаем токены без FDV
            
            # Проверяем каждую сеть где есть этот токен
            for network, token_address in token_info['addresses'].items():
                pair_key = (token_symbol, network)
                
                if pair_key not in existing_bio_pairs:
                    # Создаем виртуальную BIO пару
                    target_lp_value = token_info['fdv_usd'] * (self.target_fdv_percentage / 100)
                    
                    virtual_pair = {
                        'snapshot_timestamp': snapshot_timestamp.isoformat(),
                        'token_symbol': token_symbol,
                        'token_address': token_address,
                        'network': network,
                        'pool_name': f"BIO/{token_symbol}",
                        'pool_address': '',  # Виртуальный адрес - пул еще не создан
                        'dex': 'virtual',
                        'fee_percent': 0,
                        'tvl_usd': 0,  # Виртуальный пул
                        'volume_24h_usd': 0,
                        'token_price_usd': token_info['price_usd'],
                        'token_fdv_usd': token_info['fdv_usd'],
                        'is_bio_pair': True,  # Это виртуальная BIO пара
                        'our_position_value_usd': 0,  # У нас нет позиции в несуществующем пуле
                        'target_lp_value_usd': target_lp_value,
                        'lp_gap_usd': target_lp_value,  # Весь таргет это gap
                        'bio_price_usd': bio_price,
                        'target_fdv_percentage': self.target_fdv_percentage
                    }
                    
                    virtual_pairs.append(virtual_pair)
                    print(f"   ➕ Виртуальная пара: BIO/{token_symbol} ({network}) → Target LP: ${target_lp_value:,.0f}")
        
        print(f"   ✅ Создано {len(virtual_pairs)} виртуальных BIO пар")
        return virtual_pairs
    
    def _get_network_stats(self, snapshots: List[Dict[str, Any]]) -> str:
        """Получить статистику по сетям"""
        by_network = {}
        
        for snapshot in snapshots:
            network = snapshot['network']
            if network not in by_network:
                by_network[network] = {
                    'pools': 0,
                    'total_tvl': 0,
                    'bio_pairs': 0,
                    'our_positions': 0,
                    'target_lp': 0,
                    'lp_gap': 0
                }
            
            stats = by_network[network]
            stats['pools'] += 1
            stats['total_tvl'] += snapshot['tvl_usd']
            
            if snapshot['is_bio_pair']:
                stats['bio_pairs'] += 1
                stats['target_lp'] += snapshot['target_lp_value_usd']
                stats['lp_gap'] += snapshot['lp_gap_usd']
            
            if snapshot['our_position_value_usd'] > 0:
                stats['our_positions'] += 1
        
        # Форматируем вывод
        lines = []
        for network, stats in by_network.items():
            lines.append(f"   📊 {network.upper():8}: {stats['pools']:2d} пулов, ${stats['total_tvl']:,.0f} TVL, {stats['bio_pairs']} BIO пар, {stats['our_positions']} наших позиций")
            if stats['bio_pairs'] > 0:
                lines.append(f"      💰 Target LP: ${stats['target_lp']:,.0f}, Gap: ${stats['lp_gap']:,.0f}")
        
        return '\n'.join(lines)
    
    async def save_to_csv(self, snapshots: List[Dict[str, Any]]) -> str:
        """Сохранить снапшоты в CSV файл"""
        if not snapshots:
            print("⚠️ Нет данных для сохранения в CSV")
            return ""
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'dao_pools_snapshot_{timestamp}.csv'
        
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=snapshots[0].keys())
            writer.writeheader()
            writer.writerows(snapshots)
        
        print(f"💾 Данные сохранены в {filename}")
        return filename
    
    async def save_to_supabase(self, snapshots: List[Dict[str, Any]]) -> bool:
        """Сохранить снапшоты в Supabase"""
        if not SUPABASE_ENABLED or not supabase_handler or not supabase_handler.is_connected():
            print("⚠️ Supabase недоступен для сохранения")
            return False
        
        if not snapshots:
            print("⚠️ Нет данных для сохранения в Supabase")
            return False
        
        try:
            print(f"💾 Сохраняем {len(snapshots)} снапшотов в Supabase...")
            
            # UPSERT логика: обновляем данные за сегодня, сохраняем историю
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
            
            # Проверяем, есть ли уже записи за сегодня
            existing_today = supabase_handler.client.table('dao_pool_snapshots').select('id, pool_id').gte('created_at', f'{today}T00:00:00Z').lte('created_at', f'{today}T23:59:59.999Z').execute()
            
            if existing_today.data:
                print(f"   🔄 Найдено {len(existing_today.data)} записей за сегодня ({today}) - обновляем")
                
                # Создаём mapping существующих записей по pool_id
                existing_pools = {record['pool_id']: record['id'] for record in existing_today.data}
                
                success_count = 0
                for snapshot in snapshots:
                    snapshot['created_at'] = datetime.now(timezone.utc).isoformat()
                    pool_id = snapshot.get('pool_id')
                    
                    if pool_id in existing_pools:
                        # Обновляем существующую запись
                        result = supabase_handler.client.table('dao_pool_snapshots').update(snapshot).eq('id', existing_pools[pool_id]).execute()
                        if result.data:
                            success_count += 1
                    else:
                        # Создаём новую запись (новый пул)
                        result = supabase_handler.client.table('dao_pool_snapshots').insert(snapshot).execute()
                        if result.data:
                            success_count += 1
                            
            else:
                print(f"   ✨ Записей за сегодня ({today}) нет - создаём новые")
                
                # Добавляем created_at для каждой записи
                for snapshot in snapshots:
                    snapshot['created_at'] = datetime.now(timezone.utc).isoformat()
                
                # Сохраняем батчами по 100
                batch_size = 100
                success_count = 0
                
                for i in range(0, len(snapshots), batch_size):
                    batch = snapshots[i:i + batch_size]
                    result = supabase_handler.client.table('dao_pool_snapshots').insert(batch).execute()
                    
                    if result.data:
                        success_count += len(result.data)
                    else:
                        print(f"   ⚠️ Ошибка сохранения батча {i // batch_size + 1}")
            
            print(f"   ✅ Успешно обработано {success_count} из {len(snapshots)} записей")
            print(f"   📈 Режим: Историческая коллекция (UPSERT по дням)")
            print(f"   📊 Views используют актуальные данные за {today}")
            return success_count > 0
            
        except Exception as e:
            print(f"   ❌ Ошибка сохранения в Supabase: {e}")
            return False

    async def fetch_token_ohlcv_data(self, pool_address: str, network: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
        """Получить OHLCV данные для расчета исторических изменений цен"""
        network_map = {
            'ethereum': 'eth',
            'base': 'base', 
            'solana': 'solana'
        }
        
        network_id = network_map.get(network, network)
        url = f'https://api.geckoterminal.com/api/v2/networks/{network_id}/pools/{pool_address}/ohlcv/day?limit=8'
        
        # Retry логика для rate limits
        max_retries = 3
        base_delay = 2.0
        
        for attempt in range(max_retries):
            try:
                response = await client.get(url, timeout=20)
                
                if response.status_code == 200:
                    data = response.json()
                    ohlcv_list = data.get('data', {}).get('attributes', {}).get('ohlcv_list', [])
                    
                    if len(ohlcv_list) >= 2:  # Минимум 2 дня данных
                        return {
                            'current': ohlcv_list[0],  # Последний день [timestamp, open, high, low, close, volume]
                            'day_1': ohlcv_list[1] if len(ohlcv_list) > 1 else None,  # 1 день назад
                            'day_7': ohlcv_list[7] if len(ohlcv_list) > 7 else ohlcv_list[-1],  # 7 дней назад или самый старый
                            'count': len(ohlcv_list)
                        }
                    else:
                        print(f"   ⚠️ Недостаточно OHLCV данных для {pool_address} ({network}): {len(ohlcv_list)} дней")
                        return None
                        
                elif response.status_code == 429:  # Rate limit
                    delay = base_delay * (2 ** attempt)  # Exponential backoff
                    if attempt < max_retries - 1:
                        print(f"   🔄 OHLCV Rate limit для {pool_address}, retry {attempt + 1}/{max_retries} через {delay}s")
                        await asyncio.sleep(delay)
                        continue
                    else:
                        print(f"   ⚠️ OHLCV Rate limit для {pool_address} после {max_retries} попыток")
                        return None
                else:
                    print(f"   ⚠️ OHLCV API error для {pool_address}: {response.status_code}")
                    return None
                    
            except Exception as e:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    print(f"   🔄 OHLCV ошибка для {pool_address}, retry {attempt + 1}/{max_retries} через {delay}s: {e}")
                    await asyncio.sleep(delay)
                    continue
                else:
                    print(f"   ❌ Ошибка получения OHLCV для {pool_address}: {e}")
                    return None
        
        return None

    def calculate_price_changes(self, current_price: float, ohlcv_data: Dict[str, Any]) -> Dict[str, float]:
        """Рассчитать изменения цен на основе OHLCV данных"""
        changes = {
            'price_change_24h_percent': None,
            'price_change_7d_percent': None
        }
        
        try:
            # 24h изменение: current vs 1 день назад
            if ohlcv_data.get('day_1'):
                price_24h_ago = float(ohlcv_data['day_1'][4])  # close price
                if price_24h_ago > 0:
                    changes['price_change_24h_percent'] = ((current_price - price_24h_ago) / price_24h_ago) * 100
            
            # 7d изменение: current vs 7 дней назад
            if ohlcv_data.get('day_7'):
                price_7d_ago = float(ohlcv_data['day_7'][4])  # close price
                if price_7d_ago > 0:
                    changes['price_change_7d_percent'] = ((current_price - price_7d_ago) / price_7d_ago) * 100
            
            return changes
            
        except Exception as e:
            print(f"   ❌ Ошибка расчета изменений цен: {e}")
            return changes

    async def save_token_price_history(self, token_symbol: str, network: str, current_price: float, 
                                     current_fdv: float, ohlcv_data: Dict[str, Any] = None) -> bool:
        """Сохранить историю цен токена в Supabase"""
        if not SUPABASE_ENABLED or not supabase_handler or not supabase_handler.is_connected():
            return False
        
        try:
            # Рассчитываем изменения на основе OHLCV
            price_changes = self.calculate_price_changes(current_price, ohlcv_data or {})
            
            # Извлекаем исторические цены из OHLCV
            price_24h_ago = None
            price_7d_ago = None
            fdv_24h_ago = None
            fdv_7d_ago = None
            
            if ohlcv_data:
                if ohlcv_data.get('day_1'):
                    price_24h_ago = float(ohlcv_data['day_1'][4])  # close price
                    if current_fdv and current_price:
                        fdv_24h_ago = current_fdv * (price_24h_ago / current_price)
                
                if ohlcv_data.get('day_7'):
                    price_7d_ago = float(ohlcv_data['day_7'][4])  # close price  
                    if current_fdv and current_price:
                        fdv_7d_ago = current_fdv * (price_7d_ago / current_price)
            
            # Рассчитываем FDV изменения
            fdv_change_24h = None
            fdv_change_7d = None
            
            if fdv_24h_ago and fdv_24h_ago > 0:
                fdv_change_24h = ((current_fdv - fdv_24h_ago) / fdv_24h_ago) * 100
                
            if fdv_7d_ago and fdv_7d_ago > 0:
                fdv_change_7d = ((current_fdv - fdv_7d_ago) / fdv_7d_ago) * 100
            
            # Формируем данные для сохранения
            price_history_data = {
                'token_symbol': token_symbol,
                'network': network,
                'price_current': current_price,
                'fdv_current': current_fdv,
                'price_24h_ago': price_24h_ago,
                'price_7d_ago': price_7d_ago,
                'fdv_24h_ago': fdv_24h_ago,
                'fdv_7d_ago': fdv_7d_ago,
                'price_change_24h_percent': price_changes['price_change_24h_percent'],
                'price_change_7d_percent': price_changes['price_change_7d_percent'],
                'fdv_change_24h_percent': fdv_change_24h,
                'fdv_change_7d_percent': fdv_change_7d,
                'last_updated': datetime.now(timezone.utc).isoformat(),
                'data_source': 'geckoterminal'
            }
            
            # Сохраняем в Supabase
            return supabase_handler.save_token_price_history(price_history_data)
            
        except Exception as e:
            print(f"   ❌ Ошибка сохранения истории цен {token_symbol}: {e}")
            return False

    async def collect_token_price_history(self, all_pool_snapshots: List[Dict[str, Any]], dao_tokens: Dict[str, Dict[str, Any]], client: httpx.AsyncClient):
        """Собрать историю цен для всех уникальных токенов"""
        print(f"\n📈 Сбор исторических данных цен токенов...")
        
        # Группируем пулы по токенам и сетям
        tokens_by_network = {}
        
        for snapshot in all_pool_snapshots:
            token_symbol = snapshot.get('token_symbol')
            network = snapshot.get('network')
            pool_address = snapshot.get('pool_address')
            
            if not token_symbol or not network or not pool_address:
                continue
                
            # Исключаем базовые токены
            if token_symbol in ['SOL', 'ETH', 'BIO', 'WETH']:
                continue
            
            key = (token_symbol, network)
            if key not in tokens_by_network:
                tokens_by_network[key] = {
                    'token_symbol': token_symbol,
                    'network': network,
                    'pools': [],
                    'best_pool': None,
                    'max_tvl': 0
                }
            
            # Добавляем пул и отслеживаем лучший (по TVL)
            pool_info = {
                'address': pool_address,
                'tvl': snapshot.get('tvl_usd', 0),
                'price': snapshot.get('token_price_usd', 0),
                'fdv': snapshot.get('token_fdv_usd', 0)
            }
            
            tokens_by_network[key]['pools'].append(pool_info)
            
            if pool_info['tvl'] > tokens_by_network[key]['max_tvl']:
                tokens_by_network[key]['max_tvl'] = pool_info['tvl']
                tokens_by_network[key]['best_pool'] = pool_info
        
        # Собираем OHLCV данные для каждого токена
        success_count = 0
        total_count = len(tokens_by_network)
        rate_limit_count = 0  # Счетчик rate limits для адаптивных задержек
        
        for i, ((token_symbol, network), token_data) in enumerate(tokens_by_network.items(), 1):
            best_pool = token_data['best_pool']
            
            if not best_pool or best_pool['price'] <= 0:
                print(f"   ⚠️ {token_symbol} ({network}): нет корректных данных")
                continue
            
            try:
                # Получаем актуальные данные пула для точной цены
                pool_address = best_pool['address']
                network_map = {'ethereum': 'eth', 'base': 'base', 'solana': 'solana'}
                network_id = network_map.get(network, network)
                
                # Запрашиваем актуальную цену из API пула
                pool_url = f'https://api.geckoterminal.com/api/v2/networks/{network_id}/pools/{pool_address}'
                pool_response = await client.get(pool_url, timeout=20)
                
                current_price = best_pool['price']  # Fallback к цене из snapshot
                original_price = best_pool['price']  # Сохраняем оригинальную цену
                
                # Используем правильный FDV из dao_tokens (максимальный из всех сетей)
                current_fdv = dao_tokens.get(token_symbol, {}).get('fdv_usd', 0)
                
                if pool_response.status_code == 200:
                    pool_data = pool_response.json()
                    attrs = pool_data.get('data', {}).get('attributes', {})
                    
                    # Получаем актуальную цену базового токена (CURES в паре BIO/CURES)
                    api_price = float(attrs.get('base_token_price_usd', 0))
                    if api_price > 0:
                        current_price = api_price
                        if abs(current_price - original_price) > 0.000001:  # Цена действительно изменилась
                            print(f"   📊 {token_symbol}: актуальная цена ${current_price:.6f} (было ${original_price:.6f})")
                        else:
                            print(f"   📊 {token_symbol}: актуальная цена ${current_price:.6f} (без изменений)")
                    else:
                        print(f"   📊 {token_symbol}: используем цену из snapshot ${current_price:.6f}")
                    
                    # FDV не берем из API пула (неточно), используем уже рассчитанный
                elif pool_response.status_code == 429:
                    rate_limit_count += 1
                    print(f"   ⚠️ {token_symbol}: Rate limit для API пула, используем цену из snapshot ${current_price:.6f}")
                else:
                    print(f"   ⚠️ {token_symbol}: API пула недоступен ({pool_response.status_code}), используем цену из snapshot ${current_price:.6f}")
                
                # Получаем OHLCV данные для лучшего пула
                ohlcv_data = await self.fetch_token_ohlcv_data(
                    pool_address, 
                    network, 
                    client
                )
                
                # Сохраняем историю цен с АКТУАЛЬНОЙ ценой
                success = await self.save_token_price_history(
                    token_symbol,
                    network,
                    current_price,    # ← ИСПРАВЛЕНО: используем актуальную цену
                    current_fdv,      # ← ИСПРАВЛЕНО: используем актуальную FDV
                    ohlcv_data
                )
                
                if success:
                    success_count += 1
                
                # Адаптивная задержка: увеличиваем при частых rate limits
                base_delay = 1.0
                if rate_limit_count > 5:  # Много rate limits
                    delay = base_delay * 3  # Утроенная задержка
                    print(f"   ⏳ Увеличиваем задержку до {delay}s из-за rate limits ({rate_limit_count})")
                elif rate_limit_count > 2:  # Умеренные rate limits  
                    delay = base_delay * 2  # Удвоенная задержка
                else:
                    delay = base_delay
                
                await asyncio.sleep(delay)
                
            except Exception as e:
                print(f"   ❌ Ошибка обработки {token_symbol} ({network}): {e}")
        
        print(f"   ✅ Обработано {success_count} из {total_count} токенов (rate limits: {rate_limit_count})")

async def main():
    """Основная функция"""
    print("🚀 ЗАПУСК DAO POOLS SNAPSHOT GENERATOR")
    print("=" * 50)
    
    try:
        generator = DAOPoolsSnapshotGenerator()
        
        # Генерируем снапшот
        snapshots = await generator.generate_snapshot()
        
        if not snapshots:
            print("❌ Не удалось получить данные о пулах")
            return
        
        # Выводим статистику
        print(f"\n📊 СТАТИСТИКА СНАПШОТА:")
        print(f"   🎯 Всего снапшотов: {len(snapshots)}")
        print(f"   💰 Общий TVL: ${sum(s['tvl_usd'] for s in snapshots):,.0f}")
        print(f"   🔗 BIO пар: {sum(1 for s in snapshots if s['is_bio_pair'])}")
        print(f"   💼 Наших позиций: {sum(1 for s in snapshots if s['our_position_value_usd'] > 0)}")
        print(f"\n{generator._get_network_stats(snapshots)}")
        
        # Сохраняем в CSV (всегда)
        csv_file = await generator.save_to_csv(snapshots)
        
        # Сохраняем в Supabase (если доступен)
        if SUPABASE_ENABLED:
            await generator.save_to_supabase(snapshots)
            
            # Получаем актуальные DAO токены для исторических данных
            dao_tokens = await generator.load_dao_tokens_for_calculations()
            
            # Собираем исторические данные цен токенов
            async with httpx.AsyncClient() as client:
                await generator.collect_token_price_history(snapshots, dao_tokens, client)
        
        print(f"\n✅ СНАПШОТ ЗАВЕРШЕН")
        print(f"📁 Файл: {csv_file}")
        
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 