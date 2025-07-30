#!/usr/bin/env python3
"""
Multi-Chain Report Generator
Собирает данные с Solana, Ethereum и Base для единого отчета в Telegram
"""

import asyncio
import os
import sys
import glob
from datetime import datetime
from typing import Dict, List, Any, Optional

# Добавляем пути для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(os.path.join(os.path.dirname(__file__), 'ethereum-analyzer'))

from report_formatter import ReportFormatter
from telegram_sender import TelegramSender

# Импорты для получения данных
try:
    from positions import get_clmm_positions
    from unified_positions_analyzer import get_uniswap_positions
    from pool_analyzer import get_positions_from_multiple_wallets
    IMPORTS_SUCCESS = True
except ImportError as e:
    print(f"⚠️ Import error: {e}")
    IMPORTS_SUCCESS = False

class MultiChainReportGenerator:
    """Генератор мульти-чейн отчетов для Telegram"""
    
    def __init__(self):
        self.formatter = ReportFormatter()
        self.telegram = TelegramSender()
        
        # Конфигурация кошельков
        self.wallets = {
            "solana": [
                "BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD",
                "EKuXYJ1Shg38u67vT91YbucttoG1RKCneXF1aEhXq8K6"
            ],
            "ethereum": ["0x31AAc4021540f61fe20c3dAffF64BA6335396850"],
            "base": ["0x31AAc4021540f61fe20c3dAffF64BA6335396850"]
        }
        
        # API ключи
        self.helius_rpc = "https://mainnet.helius-rpc.com/?api-key=d4af7b72-f199-4d77-91a9-11d8512c5e42"
        self.helius_api_key = "d4af7b72-f199-4d77-91a9-11d8512c5e42"
    
    async def generate_multichain_report(self, min_value_usd: float = 100.0) -> bool:
        """
        Генерирует комплексный мульти-чейн отчет
        
        Args:
            min_value_usd: Минимальная стоимость позиции для включения
            
        Returns:
            True если отчет успешно отправлен
        """
        print("🌐 Генерируем мульти-чейн отчет...")
        print(f"💰 Минимальная стоимость позиции: ${min_value_usd}")
        
        if not IMPORTS_SUCCESS:
            print("❌ Ошибка импортов, не могу генерировать отчет")
            return False
        
        try:
            # Собираем данные со всех сетей
            multichain_data = await self._collect_multichain_data(min_value_usd)
            
            # Форматируем отчет
            report_parts = self.formatter.format_multichain_report(multichain_data)
            
            # Отправляем в Telegram
            success = await self._send_report_to_telegram(report_parts)
            
            if success:
                print("✅ Мульти-чейн отчет успешно отправлен в Telegram!")
            else:
                print("❌ Ошибка отправки отчета в Telegram")
            
            return success
            
        except Exception as e:
            print(f"❌ Ошибка генерации мульти-чейн отчета: {e}")
            return False
    
    async def _collect_multichain_data(self, min_value_usd: float) -> Dict[str, Any]:
        """Собирает данные со всех поддерживаемых сетей"""
        
        multichain_data = {
            'solana': None,
            'ethereum': [],
            'base': [],
            'summary': {
                'total_value_usd': 0,
                'total_positions': 0,
                'networks_active': 0
            }
        }
        
        # === SOLANA DATA ===
        print("🟣 Получаем данные Solana...")
        try:
            solana_data = await self._get_solana_data(min_value_usd)
            if solana_data:
                multichain_data['solana'] = solana_data
                multichain_data['summary']['networks_active'] += 1
                print(f"✅ Solana: {solana_data.get('total_positions', 0)} позиций")
        except Exception as e:
            print(f"⚠️ Ошибка получения данных Solana: {e}")
        
        # === ETHEREUM DATA ===
        print("⚡ Получаем данные Ethereum...")
        try:
            ethereum_positions = await self._get_ethereum_data(min_value_usd)
            if ethereum_positions:
                multichain_data['ethereum'] = ethereum_positions
                multichain_data['summary']['networks_active'] += 1
                print(f"✅ Ethereum: {len(ethereum_positions)} позиций")
        except Exception as e:
            print(f"⚠️ Ошибка получения данных Ethereum: {e}")
        
        # === BASE DATA ===
        print("🔵 Получаем данные Base...")
        try:
            base_positions = await self._get_base_data(min_value_usd)
            if base_positions:
                multichain_data['base'] = base_positions
                multichain_data['summary']['networks_active'] += 1
                print(f"✅ Base: {len(base_positions)} позиций")
        except Exception as e:
            print(f"⚠️ Ошибка получения данных Base: {e}")
        
        # === SUMMARY CALCULATION ===
        self._calculate_summary(multichain_data)
        
        return multichain_data
    
    async def _get_solana_data(self, min_value_usd: float) -> Optional[Dict]:
        """Получает данные Solana из Supabase"""
        try:
            from database_handler import supabase_handler
            
            if not supabase_handler or not supabase_handler.is_connected():
                print("⚠️ Supabase не подключен, используем файлы...")
                return await self._get_solana_data_from_files(min_value_usd)
            
            print("🗄️ Получаем данные Solana из Supabase...")
            
            # Получаем последние данные пулов Solana
            pools_result = supabase_handler.client.table('lp_pool_snapshots').select('*').eq(
                'network', 'solana'
            ).gte('created_at', '2025-07-28').order('created_at', desc=True).execute()
            
            # Получаем ТОЛЬКО ПОСЛЕДНИЕ позиции Solana (избегаем дублирование)
            positions_result = supabase_handler.client.table('lp_position_snapshots').select('*').not_.like(
                'position_mint', 'ethereum_%'
            ).not_.like(
                'position_mint', 'base_%'
            ).gte('created_at', '2025-07-28').order('created_at', desc=True).execute()
            
            # Убираем дублирование - берем только последнюю запись для каждой position_mint
            unique_positions = {}
            for pos in positions_result.data:
                pos_mint = pos['position_mint']
                if pos_mint not in unique_positions:
                    unique_positions[pos_mint] = pos
            
            # Преобразуем обратно в список только уникальных позиций  
            positions_result.data = list(unique_positions.values())
            
            if not pools_result.data:
                print("⚠️ Нет свежих данных Solana в Supabase")
                return None
            
            # Формируем данные в формате, который ожидает formatter (как из _parse_report_content)
            pools_data = []
            total_value = 0
            total_yield = 0
            
            # Фильтруем уникальные позиции по минимальной стоимости и адаптируем поля
            filtered_unique_positions = []
            for pos in unique_positions.values():
                if pos['position_value_usd'] >= min_value_usd:
                    # Адаптируем поля позиции для совместимости с форматтером
                    pos['position_value'] = pos['position_value_usd']  # Дублируем для совместимости
                    pos['pool_address'] = pos['pool_id']  # Для Solana pool_id = pool_address
                    filtered_unique_positions.append(pos)
            
            # Группируем ОТФИЛЬТРОВАННЫЕ уникальные позиции по пулам
            positions_by_pool = {}
            for pos in filtered_unique_positions:
                pool_id = pos['pool_id']
                if pool_id not in positions_by_pool:
                    positions_by_pool[pool_id] = []
                positions_by_pool[pool_id].append(pos)
            
            # Убираем дублирование пулов - берем только последние записи для каждого pool_id
            unique_pools = {}
            for pool in pools_result.data:
                pool_id = pool['pool_id']
                if pool_id not in unique_pools:
                    unique_pools[pool_id] = pool

            # Формируем данные пулов с позициями (в формате, который ожидает _format_solana_section)
            for pool in unique_pools.values():
                pool_positions = positions_by_pool.get(pool['pool_id'], [])
                pool_value = sum(pos['position_value_usd'] for pos in pool_positions)
                pool_yield = sum(pos['fees_usd'] for pos in pool_positions)
                
                pool_info = {
                    'name': pool['pool_name'],
                    'tvl': f"${pool['tvl_usd']:,.0f}" if pool['tvl_usd'] else "N/A",
                    'volume_24h': f"${pool['volume_24h_usd']:,.0f}" if pool['volume_24h_usd'] else "N/A",
                    'positions_count': len(pool_positions),
                    'positions_value': pool_value,  # Используем ожидаемое имя поля
                    'pending_yield': pool_yield,    # Используем ожидаемое имя поля  
                    'total_value': pool_value,      # Дублируем для совместимости
                    'total_yield': pool_yield,      # Дублируем для совместимости
                    'positions': pool_positions,
                    'token0_symbol': pool['token0_symbol'],
                    'token1_symbol': pool['token1_symbol'],
                    'pool_address': pool['pool_address'] or pool['pool_id'],  # Добавляем адрес пула
                    'pool_tvl_usd': pool['tvl_usd'],  # Добавляем TVL в ожидаемом формате
                    'id': pool['pool_id']  # Добавляем ID для совместимости с formatter
                }
                pools_data.append(pool_info)
                total_value += pool_value
                total_yield += pool_yield
            
            # Формируем итоговые данные в формате, который ожидает ReportFormatter  
            all_positions = filtered_unique_positions  # Используем отфильтрованные уникальные позиции
            
            solana_data = {
                'total_value': total_value,
                'total_positions': len(all_positions),
                'total_yield': total_yield,
                'pools': pools_data,
                'positions': all_positions,
                'network': 'solana'
            }
            
            print(f"✅ Загружено из Supabase: {len(pools_data)} пулов, {len(filtered_unique_positions)} уникальных позиций")
            return solana_data
                
        except Exception as e:
            print(f"❌ Ошибка получения Solana данных из Supabase: {e}")
            return await self._get_solana_data_from_files(min_value_usd)
    
    async def _get_solana_data_from_files(self, min_value_usd: float) -> Optional[Dict]:
        """Fallback: получает данные Solana из файлов"""
        try:
            # Ищем последний отчет Solana
            report_files = glob.glob('raydium_pool_report_*.txt')
            if not report_files:
                print("⚠️ Не найдены файлы отчетов Solana")
                return None
            
            # Используем время модификации файла для выбора последнего
            latest_report = max(report_files, key=os.path.getmtime)
            print(f"📄 Fallback: используем файл {latest_report}")
            
            # Читаем и парсим отчет
            with open(latest_report, 'r', encoding='utf-8') as f:
                report_content = f.read()
            
            # Парсим отчет через существующий метод
            solana_parsed = self.formatter._parse_report_content(report_content)
            
            if solana_parsed:
                print(f"📄 Загружен Solana отчет: {latest_report}")
                return solana_parsed
            else:
                print("⚠️ Не удалось распарсить Solana отчет")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка получения Solana данных из файлов: {e}")
            return None
    
    async def _get_ethereum_data(self, min_value_usd: float) -> List[Dict]:
        """Получает данные Ethereum из Supabase (позиции + пулы)"""
        try:
            from database_handler import supabase_handler
            
            if not supabase_handler or not supabase_handler.is_connected():
                print("⚠️ Supabase не подключен, получаем через RPC...")
                return await self._get_ethereum_data_via_rpc(min_value_usd)
            
            print("🗄️ Получаем данные Ethereum из Supabase...")
            
            # ✅ ИСПРАВЛЕНО: Получаем позиции по network, а не по префиксу position_mint
            positions_result = supabase_handler.client.table('lp_position_snapshots').select('*').eq(
                'network', 'ethereum'
            ).gte('position_value_usd', min_value_usd).order('created_at', desc=True).execute()
            
            # Убираем дублирование - берем только последнюю запись для каждой position_mint
            unique_positions = {}
            for pos in positions_result.data:
                pos_mint = pos['position_mint']
                if pos_mint not in unique_positions:
                    unique_positions[pos_mint] = pos
            positions_result.data = list(unique_positions.values())
            
            # Получаем данные пулов для контекста
            pools_result = supabase_handler.client.table('lp_pool_snapshots').select('*').eq(
                'network', 'ethereum'
            ).gte('created_at', '2025-07-28').order('created_at', desc=True).execute()
            
            # Адаптируем данные для совместимости с ReportFormatter
            ethereum_positions = positions_result.data if positions_result.data else []
            
            # Фильтруем тестовые данные
            ethereum_positions = [
                pos for pos in ethereum_positions 
                if not any(test_name in pos.get('pool_name', '') for test_name in ['TEST/', '/TEST', 'UNK/', '/UNK'])
            ]
            
            # Добавляем недостающие поля для совместимости с форматом RPC
            for pos in ethereum_positions:
                if 'total_value_usd' not in pos and 'position_value_usd' in pos:
                    pos['total_value_usd'] = pos['position_value_usd']
                if 'unclaimed_fees_usd' not in pos and 'fees_usd' in pos:
                    pos['unclaimed_fees_usd'] = pos['fees_usd']
                if 'token_id' not in pos and 'position_mint' in pos:
                    # Извлекаем ID из ethereum_xxxxx формата
                    pos['token_id'] = pos['position_mint'].replace('ethereum_', '')
                
                # Получаем TVL пула из таблицы пулов (исправлен поиск)
                try:
                    # Упрощенный поиск без строгих фильтров TVL
                    pool_data = supabase_handler.client.table('lp_pool_snapshots').select('tvl_usd, pool_name').eq(
                        'pool_address', pos['pool_id']  # Ищем по pool_address
                    ).eq('network', 'ethereum').order('created_at', desc=True).limit(1).execute()
                    
                    if pool_data.data:
                        tvl_value = pool_data.data[0]['tvl_usd']
                        pos['pool_tvl_usd'] = tvl_value if tvl_value is not None else 0
                        if pos['pool_tvl_usd'] > 0:
                            print(f"   ✅ ETH TVL найден: {pos.get('pool_name', 'Unknown')} = ${pos['pool_tvl_usd']:,.0f}")
                        else:
                            print(f"   ⚠️ ETH TVL найден, но равен 0: {pos.get('pool_name', 'Unknown')}")
                    else:
                        pos['pool_tvl_usd'] = 0
                        print(f"   ❌ ETH TVL не найден в lp_pool_snapshots: {pos.get('pool_name', 'Unknown')}")
                        print(f"       Ищем pool_address: {pos['pool_id']}")
                        
                except Exception as e:
                    print(f"⚠️ Ошибка получения TVL для Ethereum пула {pos.get('pool_id', 'Unknown')}: {e}")
                    pos['pool_tvl_usd'] = 0
                
                # ❌ УБИРАЕМ ВЫЧИСЛЕНИЯ ИЗ ОТЧЕТА - данные должны быть готовыми в Supabase!
                # Используем fees_usd как есть из Supabase
                if 'unclaimed_fees_usd' not in pos and 'fees_usd' in pos:
                    pos['unclaimed_fees_usd'] = pos['fees_usd']
            
            print(f"✅ Ethereum из Supabase: {len(ethereum_positions)} позиций, {len(pools_result.data if pools_result.data else [])} пулов")
            return ethereum_positions
            
        except Exception as e:
            print(f"❌ Ошибка получения Ethereum данных из Supabase: {e}")
            return await self._get_ethereum_data_via_rpc(min_value_usd)
    
    async def _get_ethereum_data_via_rpc(self, min_value_usd: float) -> List[Dict]:
        """Fallback: получает позиции Ethereum через unified_positions_analyzer"""
        try:
            ethereum_positions = []
            
            for wallet in self.wallets["ethereum"]:
                positions = await get_uniswap_positions(
                    wallet, 
                    network="ethereum",
                    min_value_usd=min_value_usd
                )
                ethereum_positions.extend(positions)
            
            return ethereum_positions
            
        except Exception as e:
            print(f"❌ Ошибка получения Ethereum позиций через RPC: {e}")
            return []
    
    async def _get_base_data(self, min_value_usd: float) -> List[Dict]:
        """Получает данные Base из Supabase (позиции + пулы)"""
        try:
            from database_handler import supabase_handler
            
            if not supabase_handler or not supabase_handler.is_connected():
                print("⚠️ Supabase не подключен, получаем через RPC...")
                return await self._get_base_data_via_rpc(min_value_usd)
            
            print("🗄️ Получаем данные Base из Supabase...")
            
            # ✅ ИСПРАВЛЕНО: Получаем позиции по network, а не по префиксу position_mint
            positions_result = supabase_handler.client.table('lp_position_snapshots').select('*').eq(
                'network', 'base'
            ).gte('position_value_usd', min_value_usd).order('created_at', desc=True).execute()
            
            # Убираем дублирование - берем только последнюю запись для каждой position_mint
            unique_positions = {}
            for pos in positions_result.data:
                pos_mint = pos['position_mint']
                if pos_mint not in unique_positions:
                    unique_positions[pos_mint] = pos
            positions_result.data = list(unique_positions.values())
            
            # Получаем данные пулов для контекста
            pools_result = supabase_handler.client.table('lp_pool_snapshots').select('*').eq(
                'network', 'base'
            ).gte('created_at', '2025-07-28').order('created_at', desc=True).execute()
            
            # Адаптируем данные для совместимости с ReportFormatter
            base_positions = positions_result.data if positions_result.data else []
            
            # Фильтруем тестовые данные
            base_positions = [
                pos for pos in base_positions 
                if not any(test_name in pos.get('pool_name', '') for test_name in ['TEST/', '/TEST', 'UNK/', '/UNK'])
            ]
            
            # Добавляем недостающие поля для совместимости с форматом RPC
            for pos in base_positions:
                if 'total_value_usd' not in pos and 'position_value_usd' in pos:
                    pos['total_value_usd'] = pos['position_value_usd']
                if 'unclaimed_fees_usd' not in pos and 'fees_usd' in pos:
                    pos['unclaimed_fees_usd'] = pos['fees_usd']
                if 'token_id' not in pos and 'position_mint' in pos:
                    # Извлекаем ID из base_xxxxx формата
                    pos['token_id'] = pos['position_mint'].replace('base_', '')
                
                # Получаем TVL пула из таблицы пулов (исправлен поиск)
                try:
                    # Упрощенный поиск без строгих фильтров TVL
                    pool_data = supabase_handler.client.table('lp_pool_snapshots').select('tvl_usd, pool_name').eq(
                        'pool_address', pos['pool_id']  # Ищем по pool_address
                    ).eq('network', 'base').order('created_at', desc=True).limit(1).execute()
                    
                    if pool_data.data:
                        tvl_value = pool_data.data[0]['tvl_usd']
                        pos['pool_tvl_usd'] = tvl_value if tvl_value is not None else 0
                        if pos['pool_tvl_usd'] > 0:
                            print(f"   ✅ BASE TVL найден: {pos.get('pool_name', 'Unknown')} = ${pos['pool_tvl_usd']:,.0f}")
                        else:
                            print(f"   ⚠️ BASE TVL найден, но равен 0: {pos.get('pool_name', 'Unknown')}")
                    else:
                        pos['pool_tvl_usd'] = 0
                        print(f"   ❌ BASE TVL не найден в lp_pool_snapshots: {pos.get('pool_name', 'Unknown')}")
                        print(f"       Ищем pool_address: {pos['pool_id']}")
                        
                except Exception as e:
                    print(f"⚠️ Ошибка получения TVL для Base пула {pos.get('pool_id', 'Unknown')}: {e}")
                    pos['pool_tvl_usd'] = 0
                
                # ❌ УБИРАЕМ ВЫЧИСЛЕНИЯ ИЗ ОТЧЕТА - данные должны быть готовыми в Supabase!
                # Используем fees_usd как есть из Supabase
                if 'unclaimed_fees_usd' not in pos and 'fees_usd' in pos:
                    pos['unclaimed_fees_usd'] = pos['fees_usd']
            
            print(f"✅ Base из Supabase: {len(base_positions)} позиций, {len(pools_result.data if pools_result.data else [])} пулов")
            return base_positions
            
        except Exception as e:
            print(f"❌ Ошибка получения Base данных из Supabase: {e}")
            return await self._get_base_data_via_rpc(min_value_usd)
    
    async def _get_base_data_via_rpc(self, min_value_usd: float) -> List[Dict]:
        """Fallback: получает позиции Base через unified_positions_analyzer"""
        try:
            base_positions = []
            
            for wallet in self.wallets["base"]:
                try:
                    positions = await get_uniswap_positions(
                        wallet, 
                        network="base",
                        min_value_usd=min_value_usd
                    )
                    base_positions.extend(positions)
                except Exception as e:
                    print(f"⚠️ Base RPC временно недоступен: {e}")
                    # Продолжаем без Base позиций
                    break
            
            return base_positions
            
        except Exception as e:
            print(f"❌ Ошибка получения Base позиций через RPC: {e}")
            return []
    
    def _calculate_summary(self, multichain_data: Dict[str, Any]) -> None:
        """Рассчитывает общую статистику портфеля"""
        
        total_value = 0
        total_positions = 0
        
        # Solana (теперь возвращается объект с total_value и total_positions)
        solana_data = multichain_data.get('solana')
        if solana_data:
            if isinstance(solana_data, dict):
                total_value += solana_data.get('total_value', 0)
                total_positions += solana_data.get('total_positions', 0)
            else:
                # Fallback для старого формата (если используются файлы)
                total_value += solana_data.get('total_value', 0) if hasattr(solana_data, 'get') else 0
                total_positions += solana_data.get('total_positions', 0) if hasattr(solana_data, 'get') else 0
        
        # Ethereum (список позиций)
        ethereum_positions = multichain_data.get('ethereum', [])
        for position in ethereum_positions:
            total_value += position.get('total_value_usd', position.get('position_value_usd', 0))
            total_positions += 1
        
        # Base (список позиций)
        base_positions = multichain_data.get('base', [])
        for position in base_positions:
            total_value += position.get('total_value_usd', position.get('position_value_usd', 0))
            total_positions += 1
        
        # Обновляем summary
        multichain_data['summary']['total_value_usd'] = total_value
        multichain_data['summary']['total_positions'] = total_positions
        
        print(f"📊 Общая статистика:")
        print(f"   💰 Общая стоимость: ${total_value:,.2f}")
        print(f"   📍 Всего позиций: {total_positions}")
        print(f"   🌐 Активных сетей: {multichain_data['summary']['networks_active']}")
    
    async def _send_report_to_telegram(self, report_parts: List[str]) -> bool:
        """Отправляет отчет в Telegram по частям"""
        try:
            if not report_parts:
                print("❌ Нет данных для отправки")
                return False
            
            print(f"📤 Отправляем отчет в Telegram ({len(report_parts)} частей)...")
            
            success_count = 0
            for i, part in enumerate(report_parts, 1):
                print(f"   📤 Отправка части {i}/{len(report_parts)}...")
                
                # Добавляем задержку между сообщениями
                if i > 1:
                    await asyncio.sleep(1)
                
                success = await self.telegram.send_message(part)
                if success:
                    success_count += 1
                    print(f"   ✅ Часть {i} отправлена")
                else:
                    print(f"   ❌ Ошибка отправки части {i}")
                    break
            
            if success_count == len(report_parts):
                print("✅ Все части отчета отправлены успешно!")
                return True
            else:
                print(f"⚠️ Отправлено только {success_count}/{len(report_parts)} частей")
                return False
                
        except Exception as e:
            print(f"❌ Ошибка отправки в Telegram: {e}")
            return False

async def main():
    """Основная функция для запуска генератора"""
    print("🌐 MULTI-CHAIN REPORT GENERATOR")
    print("=" * 50)
    
    generator = MultiChainReportGenerator()
    
    # Генерируем и отправляем отчет
    success = await generator.generate_multichain_report(min_value_usd=100.0)
    
    if success:
        print("\n🎉 Мульти-чейн отчет успешно создан и отправлен!")
    else:
        print("\n❌ Ошибка генерации мульти-чейн отчета")
    
    return success

if __name__ == "__main__":
    asyncio.run(main()) 