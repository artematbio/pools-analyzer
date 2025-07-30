"""
Database Handler for Supabase Integration
Модуль для работы с базой данных Supabase - дублирование данных из PostgreSQL
"""

import os
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import json

try:
    from supabase import create_client, Client
except ImportError:
    print("Warning: supabase package not installed. Install with: pip install supabase")
    Client = None

from dotenv import load_dotenv

load_dotenv()

class SupabaseHandler:
    """
    Класс для работы с Supabase базой данных
    Дублирует данные из PostgreSQL в Supabase
    Все таблицы имеют префикс lp_ (liquidity pools)
    """
    
    def __init__(self):
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_key = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
        self.client = None
        self._connected = False
        
        # Попытка подключения при инициализации
        self.connect()
    
    def connect(self) -> bool:
        """Подключение к Supabase"""
        try:
            if not self.supabase_url or not self.supabase_key:
                logging.warning("Supabase credentials не найдены")
                return False
                
            if not Client:
                logging.warning("Supabase client не доступен")
                return False
                
            self.client = create_client(self.supabase_url, self.supabase_key)
            self._connected = True
            logging.info("✅ Supabase подключен")
            return True
            
        except Exception as e:
            logging.error(f"❌ Ошибка подключения к Supabase: {e}")
            self._connected = False
            return False
    
    def is_connected(self) -> bool:
        """Проверка подключения"""
        return self._connected and self.client is not None
    
    def _convert_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Конвертация данных для Supabase"""
        converted = {}
        
        for key, value in data.items():
            if value is None:
                converted[key] = None
            elif isinstance(value, Decimal):
                converted[key] = float(value)
            elif isinstance(value, datetime):
                converted[key] = value.isoformat()
            elif isinstance(value, (dict, list)):
                converted[key] = value
            else:
                converted[key] = value
                
        return converted
    
    # === ALERTS ===
    def save_alert(self, alert_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить alert в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(alert_data)
            
            result = self.client.table('lp_alerts').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Alert сохранен в Supabase: {alert_data.get('title', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить alert: {alert_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения alert: {e}")
            return None
    
    # === TOKEN PRICES ===
    def save_token_price(self, price_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить цену токена в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(price_data)
            
            # Проверяем, есть ли уже запись для этого токена и времени
            existing = self.client.table('lp_token_prices').select('id').eq(
                'token_address', price_data.get('token_address')
            ).eq(
                'timestamp', price_data.get('timestamp')
            ).execute()
            
            if existing.data:
                # Обновляем существующую запись
                result = self.client.table('lp_token_prices').update(
                    converted_data
                ).eq('id', existing.data[0]['id']).execute()
                
                if result.data:
                    logging.info(f"✅ Цена токена обновлена: {price_data.get('symbol', 'N/A')}")
                    return existing.data[0]['id']
            else:
                # Создаем новую запись
                result = self.client.table('lp_token_prices').insert(converted_data).execute()
                
                if result.data:
                    logging.info(f"✅ Цена токена сохранена: {price_data.get('symbol', 'N/A')}")
                    return result.data[0].get('id')
                    
            return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения цены токена: {e}")
            return None
    
    def save_token_price_history(self, price_history_data: Dict[str, Any]) -> bool:
        """Сохранить исторические данные цен токена (UPSERT)"""
        if not self.is_connected():
            print("⚠️ Supabase не подключен для сохранения истории цен")
            return False
        
        try:
            # UPSERT логика: обновляем если существует, создаем если нет
            result = self.client.table('token_price_history').upsert(
                price_history_data,
                on_conflict='token_symbol,network'
            ).execute()
            
            if result.data:
                token_symbol = price_history_data.get('token_symbol', 'Unknown')
                network = price_history_data.get('network', 'Unknown')
                price_24h = price_history_data.get('price_change_24h_percent')
                price_7d = price_history_data.get('price_change_7d_percent')
                
                # Безопасное форматирование - заменяем None на 'N/A'
                price_24h_str = f"{price_24h:+.2f}" if price_24h is not None else "N/A"
                price_7d_str = f"{price_7d:+.2f}" if price_7d is not None else "N/A"
                
                print(f"✅ История цен {token_symbol} ({network}): 24h={price_24h_str}%, 7d={price_7d_str}%")
                return True
            else:
                print(f"⚠️ Не удалось сохранить историю цен: {price_history_data}")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка сохранения истории цен: {e}")
            return False
    
    def get_token_price_history(self, token_symbol: str, network: str = None) -> Optional[Dict[str, Any]]:
        """Получить историю цен токена"""
        if not self.is_connected():
            return None
        
        try:
            query = self.client.table('token_price_history').select('*').eq('token_symbol', token_symbol)
            
            if network:
                query = query.eq('network', network)
            
            result = query.order('last_updated', desc=True).limit(1).execute()
            
            if result.data:
                return result.data[0]
            return None
            
        except Exception as e:
            print(f"❌ Ошибка получения истории цен для {token_symbol}: {e}")
            return None

    def cleanup_old_price_history(self, days_to_keep: int = 30) -> int:
        """Очистка старых записей истории цен (старше N дней)"""
        if not self.is_connected():
            return 0
        
        try:
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_to_keep)).isoformat()
            
            result = self.client.table('token_price_history').delete().lt(
                'last_updated', cutoff_date
            ).execute()
            
            deleted_count = len(result.data) if result.data else 0
            if deleted_count > 0:
                print(f"🧹 Удалено {deleted_count} старых записей истории цен")
            
            return deleted_count
            
        except Exception as e:
            print(f"❌ Ошибка очистки истории цен: {e}")
            return 0
    
    # === TREASURY TRANSACTIONS ===
    def save_treasury_transaction(self, tx_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить транзакцию treasury в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(tx_data)
            
            # Проверяем дубликаты по tx_hash
            existing = self.client.table('lp_treasury_transactions').select('id').eq(
                'tx_hash', tx_data.get('tx_hash')
            ).execute()
            
            if existing.data:
                logging.info(f"⚠️ Транзакция уже существует: {tx_data.get('tx_hash', 'N/A')}")
                return existing.data[0]['id']
            
            result = self.client.table('lp_treasury_transactions').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Treasury транзакция сохранена: {tx_data.get('tx_hash', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить транзакцию: {tx_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения транзакции: {e}")
            return None
    
    # === BALANCE SNAPSHOTS ===
    def save_balance_snapshot(self, balance_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить снимок баланса в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(balance_data)
            
            result = self.client.table('lp_balance_snapshots').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Снимок баланса сохранен: {balance_data.get('dao_name', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить снимок баланса: {balance_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения снимка баланса: {e}")
            return None
    
    # === POOL ACTIVITIES ===
    def save_pool_activity(self, activity_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить активность пула в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(activity_data)
            
            result = self.client.table('lp_pool_activities').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Активность пула сохранена: {activity_data.get('pool_name', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить активность пула: {activity_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения активности пула: {e}")
            return None
    
    # === POOL SNAPSHOTS ===
    def save_pool_snapshot(self, pool_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить снимок пула в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            # Рассчитываем TVL изменение если есть исторические данные
            tvl_change_percent = None
            tvl_change_usd = None
            
            if 'pool_id' in pool_data:
                historical_data = self.get_historical_pool_tvl(pool_data['pool_id'], days_back=1)
                if historical_data and 'tvl_usd' in historical_data:
                    current_tvl = float(pool_data.get('tvl_usd', 0))
                    historical_tvl = float(historical_data.get('tvl_usd', 0))
                    
                    if historical_tvl > 0:
                        tvl_change_percent = ((current_tvl - historical_tvl) / historical_tvl) * 100
                        tvl_change_usd = current_tvl - historical_tvl
            
            # Рассчитываем 7-дневные метрики
            metrics_7d = {}
            if 'pool_id' in pool_data:
                metrics_7d = self.calculate_7d_metrics(pool_data['pool_id'])
            
            # Подготавливаем данные для сохранения
            converted_data = self._convert_data(pool_data)
            
            # Добавляем рассчитанные данные TVL изменений
            if tvl_change_percent is not None:
                converted_data['tvl_change_percent'] = tvl_change_percent
                converted_data['tvl_change_usd'] = tvl_change_usd
                
            # Добавляем 7-дневные метрики
            converted_data.update(metrics_7d)
            
            result = self.client.table('lp_pool_snapshots').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Снимок пула сохранен: {pool_data.get('pool_name', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить снимок пула: {pool_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения снимка пула: {e}")
            return None
    
    # === POSITION SNAPSHOTS ===
    def save_position_snapshot(self, position_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить снимок позиции в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(position_data)
            
            result = self.client.table('lp_position_snapshots').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Снимок позиции сохранен: {position_data.get('position_mint', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить снимок позиции: {position_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения снимка позиции: {e}")
            return None
    
    # === POOL VOLUMES ===
    def save_pool_volume_data(self, volume_data: Dict[str, Any]) -> Optional[str]:
        """Сохранить данные объема пула в Supabase"""
        try:
            if not self.is_connected():
                return None
                
            converted_data = self._convert_data(volume_data)
            
            result = self.client.table('lp_pool_volumes').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Данные объема пула сохранены: {volume_data.get('pool_name', 'N/A')} - {volume_data.get('date', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить данные объема пула: {volume_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения данных объема пула: {e}")
            return None
    
    # === BATCH OPERATIONS ===
    def save_batch_data(self, table_name: str, data_list: List[Dict[str, Any]]) -> int:
        """Сохранить множество записей одновременно"""
        try:
            if not self.is_connected() or not data_list:
                return 0
                
            # Добавляем префикс lp_ если его нет
            if not table_name.startswith('lp_'):
                table_name = f'lp_{table_name}'
                
            converted_data_list = [self._convert_data(data) for data in data_list]
            
            result = self.client.table(table_name).insert(converted_data_list).execute()
            
            if result.data:
                success_count = len(result.data)
                logging.info(f"✅ Batch операция выполнена: {success_count}/{len(data_list)} записей в {table_name}")
                return success_count
            else:
                logging.error(f"❌ Не удалось выполнить batch операцию для {table_name}")
                return 0
                
        except Exception as e:
            logging.error(f"❌ Ошибка batch операции: {e}")
            return 0
    
    # === МУЛЬТИ-ЧЕЙН ИНТЕГРАЦИЯ ===
    
    def save_ethereum_pool_data(self, pool_data: Dict[str, Any], network: str = "ethereum") -> Optional[str]:
        """Сохранить данные пула Ethereum/Base в lp_pool_snapshots"""
        try:
            if not self.is_connected():
                return None
            
            # Адаптация данных Ethereum пула для lp_pool_snapshots
            pool_snapshot_data = {
                'pool_id': pool_data.get('pool_address', ''),  # ✅ БЕЗ ПРЕФИКСОВ
                'pool_name': pool_data.get('pool_name') or f"{pool_data.get('token0_symbol', 'TOKEN0')}/{pool_data.get('token1_symbol', 'TOKEN1')}",  # ✅ ПРАВИЛЬНЫЕ ИМЕНА
                'token0_address': pool_data.get('token0_address'),
                'token0_symbol': pool_data.get('token0_symbol'),
                'token0_price': float(pool_data.get('token0_price_usd', 0)),
                'token1_address': pool_data.get('token1_address'),
                'token1_symbol': pool_data.get('token1_symbol'),
                'token1_price': float(pool_data.get('token1_price_usd', 0)),
                'current_price': float(pool_data.get('current_price', 0)),
                'fee_rate': float(pool_data.get('fee_tier', 0)) / 10000,  # Convert from basis points to decimal
                'tvl_usd': float(pool_data.get('tvl_usd', 0)),
                'volume_24h_usd': float(pool_data.get('volume_24h_usd', 0)),
                'total_positions': pool_data.get('total_positions', 0),
                'in_range_positions': pool_data.get('in_range_positions', 0),
                'out_of_range_positions': pool_data.get('out_of_range_positions', 0),
                'total_value_usd': float(pool_data.get('total_value_usd', 0)),
                # Ethereum/Base specific fields
                'network': network,
                'pool_address': pool_data.get('pool_address'),
                'tick_current': pool_data.get('current_tick') or pool_data.get('tick'),
                'sqrt_price_x96': pool_data.get('sqrt_price_x96') or pool_data.get('sqrtPriceX96'),
                # Убрано 'liquidity' поле - оно удаляется из таблицы
                'timestamp': datetime.now().isoformat()
            }
            
            # Рассчитываем 24h изменения если есть исторические данные
            try:
                pool_snapshot_data.update(self._calculate_24h_changes(pool_data.get('pool_address') or pool_data.get('pool_id', ''), network))
            except Exception as e:
                logging.warning(f"Не удалось рассчитать 24h изменения для пула: {e}")
                pool_snapshot_data.update({
                    'price_change_24h_percent': None,
                    'volume_change_24h_percent': None
                })
            
            return self.save_pool_snapshot(pool_snapshot_data)
            
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения пула {network}: {e}")
            return None
    
    def save_ethereum_position_data(self, position_data: Dict[str, Any], network: str = "ethereum") -> Optional[str]:
        """Сохранить данные позиции Ethereum/Base в lp_position_snapshots"""
        try:
            if not self.is_connected():
                return None
            
            # Адаптация данных позиции Ethereum для lp_position_snapshots
            position_snapshot_data = {
                'position_mint': position_data.get('position_id', ''),  # Чистый position_id без префикса
                'pool_id': position_data.get('pool_address', ''),  # Чистый pool_address без префикса
                'pool_name': position_data.get('pool_name', f"{position_data.get('token0_symbol', 'UNK')}/{position_data.get('token1_symbol', 'UNK')}"),
                'token0_address': position_data.get('token0_address'),
                'token0_symbol': position_data.get('token0_symbol'),
                'token0_amount': float(position_data.get('amount0') or 0),
                'token1_address': position_data.get('token1_address'),
                'token1_symbol': position_data.get('token1_symbol'),
                'token1_amount': float(position_data.get('amount1') or 0),
                'position_value_usd': float(position_data.get('total_value_usd') or 0),
                'fees_usd': float(position_data.get('unclaimed_fees_usd') or 0),
                'in_range': position_data.get('in_range', False),
                'tick_lower': position_data.get('tick_lower'),
                'tick_upper': position_data.get('tick_upper'),
                'current_price': float(position_data.get('current_price') or 0),
                'fee_tier': float(position_data.get('fee_tier') or 0) / 10000,  # Convert from basis points
                'liquidity_share_percent': 0,  # Can be calculated later if needed
                'liquidity': str(position_data.get('liquidity') or 0),
                'position_pda': position_data.get('position_id'),  # Store position ID
                'unclaimed_fees_token0': float(position_data.get('unclaimed_fees_token0') or 0),
                'unclaimed_fees_token1': float(position_data.get('unclaimed_fees_token1') or 0),
                'token0_price_usd': float(position_data.get('token0_price_usd') or 0),
                'token1_price_usd': float(position_data.get('token1_price_usd') or 0),
                'tick_current': position_data.get('current_tick'),
                'price_range_min': float(position_data.get('price_lower') or 0),
                'price_range_max': float(position_data.get('price_upper') or 0),
                'network': network,  # Добавляем сеть для идентификации
                'timestamp': datetime.now().isoformat()
            }
            
            return self.save_position_snapshot(position_snapshot_data)
            
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения позиции {network}: {e}")
            return None
    
    def save_multichain_csv_data(self, csv_data: Dict[str, Any]) -> Dict[str, int]:
        """Сохранить данные из мульти-чейн CSV генератора"""
        try:
            if not self.is_connected():
                return {'pools': 0, 'positions': 0}
            
            pools_saved = 0
            positions_saved = 0
            
            # Обрабатываем данные пулов из CSV
            pools_data = csv_data.get('pools', [])
            for pool in pools_data:
                network = pool.get('chain', 'unknown')
                if network in ['ethereum', 'base']:
                    result = self.save_ethereum_pool_data(pool, network)
                    if result:
                        pools_saved += 1
                elif network == 'solana':
                    # Для Solana используем стандартный метод
                    result = self.save_pool_snapshot(pool)
                    if result:
                        pools_saved += 1
            
            # Обрабатываем данные позиций из CSV
            positions_data = csv_data.get('positions', [])
            for position in positions_data:
                network = position.get('network', 'unknown')
                if network in ['ethereum', 'base']:
                    result = self.save_ethereum_position_data(position, network)
                    if result:
                        positions_saved += 1
                elif network == 'solana':
                    # Для Solana используем стандартный метод
                    result = self.save_position_snapshot(position)
                    if result:
                        positions_saved += 1
            
            logging.info(f"✅ Multichain CSV данные сохранены: {pools_saved} пулов, {positions_saved} позиций")
            return {'pools': pools_saved, 'positions': positions_saved}
            
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения multichain CSV данных: {e}")
            return {'pools': 0, 'positions': 0}
    
    def get_network_statistics(self) -> Dict[str, Dict[str, int]]:
        """Получить статистику по сетям"""
        try:
            if not self.is_connected():
                return {}
            
            stats = {}
            
            # Статистика пулов по сетям
            pool_result = self.client.table('lp_pool_snapshots').select(
                'network'
            ).execute()
            
            if pool_result.data:
                network_counts = {}
                for record in pool_result.data:
                    network = record.get('network', 'unknown')
                    network_counts[network] = network_counts.get(network, 0) + 1
                stats['pools'] = network_counts
            
            # Статистика позиций по сетям (извлекаем из position_mint)
            position_result = self.client.table('lp_position_snapshots').select(
                'position_mint'
            ).execute()
            
            if position_result.data:
                network_counts = {}
                for record in position_result.data:
                    position_mint = record.get('position_mint', '')
                    if position_mint.startswith('ethereum_'):
                        network = 'ethereum'
                    elif position_mint.startswith('base_'):
                        network = 'base'
                    else:
                        network = 'solana'
                    network_counts[network] = network_counts.get(network, 0) + 1
                stats['positions'] = network_counts
            
            return stats
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения статистики сетей: {e}")
            return {}
    
    def get_pool_tvl_yesterday(self, pool_address: str, network: str) -> Optional[float]:
        """
        Получает TVL пула за прошлый день из Supabase
        
        Args:
            pool_address: Адрес пула
            network: Сеть (ethereum, base, solana)
            
        Returns:
            TVL за прошлый день или None если не найдено
        """
        try:
            if not self.is_connected():
                return None
            
            from datetime import datetime, timedelta
            
            # Вчерашняя дата
            yesterday = datetime.utcnow() - timedelta(days=1)
            yesterday_str = yesterday.strftime('%Y-%m-%d')
            
            # Ищем запись за вчерашний день
            response = self.client.table("lp_pool_snapshots").select("tvl_usd").eq(
                "pool_address", pool_address
            ).eq(
                "network", network
            ).gte(
                "created_at", f"{yesterday_str} 00:00:00"
            ).lt(
                "created_at", f"{yesterday_str} 23:59:59"
            ).order("created_at", desc=True).limit(1).execute()
            
            if response.data:
                # tvl_usd колонка содержит TVL в USD для пулов
                return float(response.data[0].get("tvl_usd", 0))
            
            return None
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения TVL пула за вчера: {e}")
            return None
    
    def calculate_tvl_change_indicator(self, current_tvl: float, pool_address: str, network: str) -> str:
        """
        Рассчитывает индикатор изменения TVL
        
        Args:
            current_tvl: Текущий TVL
            pool_address: Адрес пула  
            network: Сеть
            
        Returns:
            Строка с индикатором изменения (пустая если изменение меньше 5%)
        """
        try:
            yesterday_tvl = self.get_pool_tvl_yesterday(pool_address, network)
            
            if yesterday_tvl is None or yesterday_tvl == 0:
                return ""  # Нет данных за вчера
            
            # Рассчитываем изменение в процентах
            change_percent = ((current_tvl - yesterday_tvl) / yesterday_tvl) * 100
            
            # Если изменение больше 5% в любую сторону
            if abs(change_percent) >= 5:
                if change_percent > 0:
                    return f" 📈 +{change_percent:.1f}%"
                else:
                    return f" 📉 {change_percent:.1f}%"
            
            return ""  # Изменение меньше 5%
            
        except Exception as e:
            logging.error(f"❌ Ошибка расчета изменения TVL: {e}")
            return ""
    
    # === QUERY METHODS ===
    def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить последние alerts"""
        try:
            if not self.is_connected():
                return []
                
            result = self.client.table('lp_alerts').select('*').order(
                'timestamp', desc=True
            ).limit(limit).execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения alerts: {e}")
            return []
    
    def get_token_price_history(self, token_address: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Получить историю цен токена"""
        try:
            if not self.is_connected():
                return []
                
            result = self.client.table('lp_token_prices').select('*').eq(
                'token_address', token_address
            ).order('timestamp', desc=True).limit(limit).execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения истории цен: {e}")
            return []
    
    def get_treasury_transactions(self, dao_name: str = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Получить транзакции treasury"""
        try:
            if not self.is_connected():
                return []
                
            query = self.client.table('lp_treasury_transactions').select('*')
            
            if dao_name:
                query = query.eq('dao_name', dao_name)
                
            result = query.order('timestamp', desc=True).limit(limit).execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения транзакций treasury: {e}")
            return []
    
    def get_database_stats(self) -> Dict[str, Any]:
        """Получить статистику базы данных"""
        try:
            if not self.is_connected():
                return {}
                
            stats = {}
            
            # Список таблиц с префиксом lp_
            tables = [
                'lp_alerts', 'lp_token_prices', 'lp_treasury_transactions',
                'lp_balance_snapshots', 'lp_pool_activities', 'lp_pool_snapshots',
                'lp_pool_volumes', 'lp_position_snapshots'
            ]
            
            for table in tables:
                try:
                    result = self.client.table(table).select('id', count='exact').execute()
                    stats[table] = result.count if hasattr(result, 'count') else 0
                except:
                    stats[table] = 0
                    
            return stats
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения статистики БД: {e}")
            return {}

    def get_historical_pool_tvl(self, pool_id: str, days_back: int = 1) -> Optional[Dict[str, Any]]:
        """Получить исторические данные TVL пула из lp_pool_snapshots"""
        try:
            if not self.is_connected():
                return None
                
            # Вычисляем дату days_back дней назад
            from datetime import datetime, timedelta
            target_date = datetime.now() - timedelta(days=days_back)
            target_date_str = target_date.strftime('%Y-%m-%d')
            
            # Ищем снимки пула за указанную дату
            result = self.client.table('lp_pool_snapshots').select('*').eq(
                'pool_id', pool_id
            ).gte('created_at', target_date_str).lt(
                'created_at', (target_date + timedelta(days=1)).strftime('%Y-%m-%d')
            ).order('created_at', desc=True).limit(1).execute()
            
            if result.data and len(result.data) > 0:
                return result.data[0]
            else:
                # Если не найдено за конкретную дату, ищем ближайшую запись
                result = self.client.table('lp_pool_snapshots').select('*').eq(
                    'pool_id', pool_id
                ).lt('created_at', target_date_str).order('created_at', desc=True).limit(1).execute()
                
                return result.data[0] if result.data and len(result.data) > 0 else None
                
        except Exception as e:
            logging.error(f"❌ Ошибка получения исторических данных TVL: {e}")
            return None

    def calculate_7d_metrics(self, pool_id: str) -> dict:
        """Рассчитать метрики за 7 дней"""
        try:
            if not self.is_connected():
                return {'tvl_7d_change_pct': None, 'volume_7d_avg_usd': None}
                
            # Получить данные за 7 дней
            from datetime import datetime, timedelta
            week_ago = (datetime.now() - timedelta(days=7)).isoformat()
            
            result = self.client.table('lp_pool_snapshots').select(
                'tvl_usd, volume_24h_usd, created_at'
            ).eq('pool_id', pool_id).gte('created_at', week_ago).order('created_at', desc=True).execute()
            
            if result.data and len(result.data) > 1:
                # Берем самую свежую и самую старую записи
                current_record = result.data[0]
                old_record = result.data[-1]
                
                current_tvl = float(current_record.get('tvl_usd', 0))
                old_tvl = float(old_record.get('tvl_usd', 0))
                
                # TVL изменение за 7 дней
                tvl_7d_change = 0.0
                if old_tvl > 0:
                    tvl_7d_change = ((current_tvl - old_tvl) / old_tvl) * 100
                
                # Средний объем за 7 дней
                volumes = []
                for record in result.data:
                    volume = record.get('volume_24h_usd')
                    if volume is not None:
                        volumes.append(float(volume))
                
                avg_volume_7d = sum(volumes) / len(volumes) if volumes else 0.0
                
                return {
                    'tvl_7d_change_pct': round(tvl_7d_change, 4),
                    'volume_7d_avg_usd': round(avg_volume_7d, 2)
                }
            else:
                # Недостаточно данных за 7 дней
                return {
                    'tvl_7d_change_pct': None,
                    'volume_7d_avg_usd': None
                }
                
        except Exception as e:
            logging.error(f"❌ Ошибка расчета 7-дневных метрик: {e}")
            return {'tvl_7d_change_pct': None, 'volume_7d_avg_usd': None}

    def calculate_tvl_change(self, current_tvl: float, historical_tvl: float) -> Optional[float]:
        """Рассчитать изменение TVL в процентах"""
        try:
            if historical_tvl == 0:
                return None
                
            change_percent = ((current_tvl - historical_tvl) / historical_tvl) * 100
            return round(change_percent, 2)
            
        except Exception as e:
            logging.error(f"❌ Ошибка расчета изменения TVL: {e}")
            return None

    def _calculate_24h_changes(self, pool_address: str, network: str) -> Dict[str, Any]:
        """Рассчитывает 24-часовое изменение цены и объема для пула."""
        try:
            if not self.is_connected():
                return {'price_change_24h_percent': None, 'volume_change_24h_percent': None}

            # Получаем текущие данные пула
            current_pool_data = self.client.table('lp_pool_snapshots').select('*').eq(
                'pool_address', pool_address
            ).eq(
                'network', network
            ).order('created_at', desc=True).limit(1).execute()

            if not current_pool_data.data:
                return {'price_change_24h_percent': None, 'volume_change_24h_percent': None}

            current_record = current_pool_data.data[0]
            current_price = float(current_record.get('current_price', 0))
            current_volume = float(current_record.get('volume_24h_usd', 0))

            # Получаем данные за 24 часа назад
            from datetime import datetime, timedelta
            twenty_four_hours_ago = (datetime.now() - timedelta(hours=24)).isoformat()

            historical_pool_data = self.client.table('lp_pool_snapshots').select('*').eq(
                'pool_address', pool_address
            ).eq(
                'network', network
            ).lte('created_at', twenty_four_hours_ago).order('created_at', desc=True).limit(1).execute()

            if not historical_pool_data.data:
                return {'price_change_24h_percent': None, 'volume_change_24h_percent': None}

            historical_record = historical_pool_data.data[0]
            historical_price = float(historical_record.get('current_price', 0))
            historical_volume = float(historical_record.get('volume_24h_usd', 0))

            # Рассчитываем процентные изменения
            price_change_percent = None
            if historical_price > 0:
                price_change_percent = ((current_price - historical_price) / historical_price) * 100

            volume_change_percent = None
            if historical_volume > 0:
                volume_change_percent = ((current_volume - historical_volume) / historical_volume) * 100

            return {
                'price_change_24h_percent': round(price_change_percent, 2) if price_change_percent is not None else None,
                'volume_change_24h_percent': round(volume_change_percent, 2) if volume_change_percent is not None else None
            }
        except Exception as e:
            logging.error(f"❌ Ошибка расчета 24h изменений: {e}")
            return {'price_change_24h_percent': None, 'volume_change_24h_percent': None}

    def get_historical_token_price(self, token_symbol: str, days_back: int = 1) -> Optional[float]:
        """Получить историческую цену токена N дней назад"""
        try:
            if not self.is_connected():
                return None
                
            # Рассчитываем дату N дней назад
            target_date = datetime.now() - timedelta(days=days_back)
            
            # Ищем снапшот ближайший к целевой дате
            # Берем последний снапшот за целевой день
            result = self.client.table('dao_pool_snapshots').select('token_price_usd').eq(
                'token_symbol', token_symbol
            ).gte(
                'snapshot_timestamp', target_date.strftime('%Y-%m-%d')
            ).lt(
                'snapshot_timestamp', (target_date + timedelta(days=1)).strftime('%Y-%m-%d')
            ).order(
                'snapshot_timestamp', desc=True
            ).limit(1).execute()
            
            if result.data and len(result.data) > 0:
                price = result.data[0]['token_price_usd']
                if price and price > 0:
                    return float(price)
            
            # Если за точный день не найдено, ищем ближайший более ранний
            result_fallback = self.client.table('dao_pool_snapshots').select('token_price_usd').eq(
                'token_symbol', token_symbol
            ).lt(
                'snapshot_timestamp', target_date.strftime('%Y-%m-%d')
            ).order(
                'snapshot_timestamp', desc=True
            ).limit(1).execute()
            
            if result_fallback.data and len(result_fallback.data) > 0:
                price = result_fallback.data[0]['token_price_usd']
                if price and price > 0:
                    return float(price)
                    
            return None
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения исторической цены для {token_symbol} ({days_back}д назад): {e}")
            return None

    def get_historical_token_tvl(self, token_symbol: str, days_back: int = 7) -> Optional[float]:
        """Получить общий TVL токена N дней назад"""
        try:
            if not self.is_connected():
                return None
                
            target_date = datetime.now() - timedelta(days=days_back)
            
            # Суммируем TVL всех реальных пулов токена на целевую дату  
            result = self.client.table('dao_pool_snapshots').select('tvl_usd').eq(
                'token_symbol', token_symbol
            ).neq(
                'pool_address', ''  # Исключаем виртуальные пулы
            ).gte(
                'snapshot_timestamp', target_date.strftime('%Y-%m-%d')
            ).lt(
                'snapshot_timestamp', (target_date + timedelta(days=1)).strftime('%Y-%m-%d')
            ).execute()
            
            if result.data and len(result.data) > 0:
                # Суммируем TVL всех пулов
                total_tvl = sum(float(record['tvl_usd']) for record in result.data if record['tvl_usd'])
                return total_tvl
            
            # Fallback: ищем ближайшую более раннюю дату
            result_fallback = self.client.table('dao_pool_snapshots').select('tvl_usd').eq(
                'token_symbol', token_symbol
            ).neq(
                'pool_address', ''
            ).lt(
                'snapshot_timestamp', target_date.strftime('%Y-%m-%d')
            ).order(
                'snapshot_timestamp', desc=True
            ).limit(10).execute()  # Берем больше записей для агрегации
            
            if result_fallback.data and len(result_fallback.data) > 0:
                total_tvl = sum(float(record['tvl_usd']) for record in result_fallback.data if record['tvl_usd'])
                return total_tvl
                
            return None
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения исторического TVL для {token_symbol} ({days_back}д назад): {e}")
            return None

# Глобальный экземпляр для использования в других модулях
supabase_handler = SupabaseHandler() if Client else None 