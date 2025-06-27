"""
Database Handler for Supabase Integration
Модуль для работы с базой данных Supabase - дублирование данных из PostgreSQL
"""

import os
import logging
from typing import Dict, List, Optional, Any, Union
from datetime import datetime, timezone
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
                
            converted_data = self._convert_data(pool_data)
            
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

# Глобальный экземпляр для использования в других модулях
supabase_handler = SupabaseHandler() if Client else None 