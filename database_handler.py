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
            
            result = self.client.table('alerts').insert(converted_data).execute()
            
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
            existing = self.client.table('token_prices').select('id').eq(
                'token_address', price_data.get('token_address')
            ).eq(
                'timestamp', price_data.get('timestamp')
            ).execute()
            
            if existing.data:
                # Обновляем существующую запись
                result = self.client.table('token_prices').update(
                    converted_data
                ).eq('id', existing.data[0]['id']).execute()
                
                if result.data:
                    logging.info(f"✅ Цена токена обновлена: {price_data.get('token_symbol', 'N/A')}")
                    return existing.data[0]['id']
            else:
                # Создаем новую запись
                result = self.client.table('token_prices').insert(converted_data).execute()
                
                if result.data:
                    logging.info(f"✅ Цена токена сохранена: {price_data.get('token_symbol', 'N/A')}")
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
            existing = self.client.table('treasury_transactions').select('id').eq(
                'tx_hash', tx_data.get('tx_hash')
            ).execute()
            
            if existing.data:
                logging.info(f"⚠️ Транзакция уже существует: {tx_data.get('tx_hash', 'N/A')}")
                return existing.data[0]['id']
            
            result = self.client.table('treasury_transactions').insert(converted_data).execute()
            
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
            
            result = self.client.table('balance_snapshots').insert(converted_data).execute()
            
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
            
            result = self.client.table('pool_activities').insert(converted_data).execute()
            
            if result.data:
                logging.info(f"✅ Активность пула сохранена: {activity_data.get('pool_address', 'N/A')}")
                return result.data[0].get('id')
            else:
                logging.error(f"❌ Не удалось сохранить активность пула: {activity_data}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сохранения активности пула: {e}")
            return None
    
    # === BATCH OPERATIONS ===
    def save_batch_data(self, table_name: str, data_list: List[Dict[str, Any]]) -> int:
        """Сохранить данные батчем"""
        try:
            if not self.is_connected() or not data_list:
                return 0
                
            converted_data = [self._convert_data(item) for item in data_list]
            
            result = self.client.table(table_name).insert(converted_data).execute()
            
            if result.data:
                count = len(result.data)
                logging.info(f"✅ Сохранено {count} записей в {table_name}")
                return count
            else:
                logging.error(f"❌ Не удалось сохранить batch в {table_name}")
                return 0
                
        except Exception as e:
            logging.error(f"❌ Ошибка batch сохранения в {table_name}: {e}")
            return 0
    
    # === QUERY METHODS ===
    def get_recent_alerts(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Получить последние alerts"""
        try:
            if not self.is_connected():
                return []
                
            result = self.client.table('alerts').select('*').order(
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
                
            result = self.client.table('token_prices').select('*').eq(
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
                
            query = self.client.table('treasury_transactions').select('*')
            
            if dao_name:
                query = query.eq('dao_name', dao_name)
                
            result = query.order('timestamp', desc=True).limit(limit).execute()
            
            return result.data if result.data else []
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения транзакций: {e}")
            return []
    
    # === STATISTICS ===
    def get_database_stats(self) -> Dict[str, Any]:
        """Получить статистику базы данных"""
        try:
            if not self.is_connected():
                return {}
                
            stats = {}
            tables = ['alerts', 'token_prices', 'treasury_transactions', 'balance_snapshots', 'pool_activities']
            
            for table in tables:
                result = self.client.table(table).select('*', count='exact').limit(1).execute()
                stats[table] = result.count if hasattr(result, 'count') else 0
                
            return stats
            
        except Exception as e:
            logging.error(f"❌ Ошибка получения статистики: {e}")
            return {}

# Создаем глобальный экземпляр
supabase_handler = SupabaseHandler() 