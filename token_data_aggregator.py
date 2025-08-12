"""
Token Data Aggregator
Объединяет данные из CoinMarketCap (приоритет) + CoinGecko (fallback)
"""

import asyncio
import httpx
import os
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from coinmarketcap_client import CoinMarketCapClient

logger = logging.getLogger(__name__)

class TokenDataAggregator:
    def __init__(self):
        # УБИРАЕМ CoinMarketCap - не имеет нужных токенов
        # self.cmc_client = CoinMarketCapClient()
        self.coingecko_api_key = os.getenv('COINGECKO_API_KEY', 'CG-2zrbNPwAg5rJeE4zrfCRJk6j')
        
        # Актуальные CoinGecko ID для наших токенов (из tokens_pools_config.json)
        self.token_coingecko_ids = {
            'BIO': 'bio-protocol',
            'VITA': 'vitadao',
            'HAIR': 'hairdao', 
            'NEURON': 'cerebrum-dao',
            'ATH': 'athenadao-token',  # ИСПРАВЛЕНО
            'GROW': 'valleydao',
            'CRYO': 'cryodao',
            'PSY': 'psychedelics-anonymous',
            'QBIO': 'qbio-dao',
            'SPINE': 'spinefi',
            'CURES': 'cures-token',
            'RIF': 'rif-token',
            'URO': 'uro-token',
            'MYCO': 'mycelium'
        }

    async def get_comprehensive_token_data(self, token_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        ОБНОВЛЕНО: Получает данные токенов только через основной CoinGecko API (с max_supply)
        
        Returns:
        {
            'ATH': {
                'price_usd': 0.439182,
                'market_cap': 1234567,
                'fully_diluted_valuation': 43918200,  # price × max_supply
                'max_supply': 100000000,
                'circulating_supply': 30000000,
                'total_supply': 100000000,
                'data_sources': ['coingecko_main'],
                'priority_source': 'coingecko_main',
                'last_updated': '2025-08-11T...'
            }
        }
        """
        logger.info(f"🔄 Получаем данные для {len(token_symbols)} токенов через основной CoinGecko API...")
        
        # Используем только основной CoinGecko API с max_supply
        coingecko_data = await self._get_main_coingecko_data(token_symbols)
        logger.info(f"✅ CoinGecko: получено данных для {len(coingecko_data)} токенов")
        
        # Логируем результаты
        self._log_coingecko_results(coingecko_data)
        
        return coingecko_data

    async def _get_main_coingecko_data(self, token_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Получение данных через основной CoinGecko API с max_supply"""
        result = {}
        
        async with httpx.AsyncClient() as client:
            for symbol in token_symbols:
                symbol_upper = symbol.upper()
                
                if symbol_upper not in self.token_coingecko_ids:
                    logger.warning(f"⚠️ Нет CoinGecko ID для {symbol_upper}")
                    continue
                
                coingecko_id = self.token_coingecko_ids[symbol_upper]
                
                try:
                    # Используем публичный CoinGecko API (работает лучше)
                    url = f'https://api.coingecko.com/api/v3/coins/{coingecko_id}'
                    
                    response = await client.get(url, timeout=15)
                    
                    if response.status_code == 200:
                        data = response.json()
                        market_data = data.get('market_data', {})
                        
                        # Извлекаем все нужные данные
                        current_price = market_data.get('current_price', {}).get('usd', 0)
                        market_cap = market_data.get('market_cap', {}).get('usd', 0)
                        circulating_supply = market_data.get('circulating_supply', 0)
                        total_supply = market_data.get('total_supply', 0)
                        max_supply = market_data.get('max_supply', 0)
                        
                        # ПРАВИЛЬНЫЙ РАСЧЕТ FDV = price × max_supply
                        if current_price and max_supply:
                            fdv = current_price * max_supply
                        elif current_price and total_supply:
                            # Fallback: используем total_supply если нет max_supply
                            fdv = current_price * total_supply
                        else:
                            fdv = market_data.get('fully_diluted_valuation', {}).get('usd', 0)
                        
                        token_data = {
                            'price_usd': current_price,
                            'market_cap': market_cap,
                            'fully_diluted_valuation': fdv,
                            'circulating_supply': circulating_supply,
                            'total_supply': total_supply,
                            'max_supply': max_supply,
                            'data_sources': ['coingecko_main'],
                            'priority_source': 'coingecko_main',
                            'last_updated': datetime.now().isoformat()
                        }
                        
                        result[symbol_upper] = token_data
                        
                        logger.info(f"✅ {symbol_upper}: Price=${current_price:.6f}, "
                                  f"MC=${market_cap:,.0f}, FDV=${fdv:,.0f}, "
                                  f"Max Supply={max_supply:,.0f}" if max_supply else 
                                  f"Max Supply=None")
                        
                    else:
                        logger.warning(f"⚠️ {symbol_upper}: API error {response.status_code}")
                        
                    # Задержка между запросами
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    logger.error(f"❌ {symbol_upper}: {e}")
        
        return result

    def _log_coingecko_results(self, coingecko_data: Dict):
        """Логирование результатов CoinGecko"""
        logger.info("📊 РЕЗУЛЬТАТЫ COINGECKO API:")
        logger.info(f"  Получено данных: {len(coingecko_data)} токенов")
        
        for symbol, data in coingecko_data.items():
            fdv = data.get('fully_diluted_valuation', 0)
            mc = data.get('market_cap', 0)
            max_supply = data.get('max_supply', 0)
            price = data.get('price_usd', 0)
            
            logger.info(f"  {symbol}: FDV=${fdv:,.0f}, MC=${mc:,.0f}, "
                       f"Price=${price:.6f}, Max Supply={max_supply:,.0f}" if max_supply else 
                       f"Price=${price:.6f}, Max Supply=None")

    async def _get_coingecko_data(self, token_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Получение данных из CoinGecko API"""
        try:
            # Получаем CoinGecko IDs для символов
            coingecko_ids = []
            symbol_to_id_map = {}
            
            for symbol in token_symbols:
                if symbol.upper() in self.token_coingecko_ids:
                    cg_id = self.token_coingecko_ids[symbol.upper()]
                    coingecko_ids.append(cg_id)
                    symbol_to_id_map[cg_id] = symbol.upper()
            
            if not coingecko_ids:
                return {}
            
            # Формируем запрос к CoinGecko
            ids_str = ','.join(coingecko_ids)
            
            async with httpx.AsyncClient(timeout=30) as client:
                params = {
                    'ids': ids_str,
                    'vs_currencies': 'usd',
                    'include_market_cap': 'true',
                    'include_24hr_vol': 'true',
                    'include_24hr_change': 'true',
                    'include_last_updated_at': 'true'
                }
                
                # Добавляем API ключ в заголовки (правильный метод для CoinGecko)
                headers = {}
                if self.coingecko_api_key and self.coingecko_api_key != 'your_coingecko_api_key':
                    headers['x-cg-pro-api-key'] = self.coingecko_api_key
                
                response = await client.get(
                    'https://api.coingecko.com/api/v3/simple/price',
                    params=params,
                    headers=headers
                )
                
                if response.status_code == 200:
                    data = response.json()
                    return self._parse_coingecko_response(data, symbol_to_id_map)
                else:
                    logger.warning(f"⚠️ CoinGecko API error {response.status_code}: {response.text}")
                    return {}
                    
        except Exception as e:
            logger.warning(f"⚠️ CoinGecko API exception: {e}")
            return {}

    def _parse_coingecko_response(self, data: Dict, symbol_to_id_map: Dict[str, str]) -> Dict[str, Dict[str, Any]]:
        """Парсинг ответа от CoinGecko"""
        result = {}
        
        for cg_id, token_data in data.items():
            if cg_id in symbol_to_id_map:
                symbol = symbol_to_id_map[cg_id]
                
                parsed_data = {
                    'price_usd': token_data.get('usd', 0),
                    'market_cap': token_data.get('usd_market_cap', 0),
                    'volume_24h': token_data.get('usd_24h_vol', 0),
                    'percent_change_24h': token_data.get('usd_24h_change', 0),
                    'last_updated': token_data.get('last_updated_at'),
                    'source': 'coingecko'
                }
                
                result[symbol] = parsed_data
        
        return result

    def _combine_token_data(self, cmc_data: Dict, coingecko_data: Dict, requested_symbols: List[str]) -> Dict[str, Dict[str, Any]]:
        """Объединение и приоритизация данных из двух источников"""
        combined = {}
        
        for symbol in requested_symbols:
            symbol_upper = symbol.upper()
            combined_token_data = {}
            data_sources = []
            priority_source = None
            
            # Проверяем наличие данных в CMC (приоритет)
            if symbol_upper in cmc_data:
                combined_token_data.update(cmc_data[symbol_upper])
                data_sources.append('coinmarketcap')
                priority_source = 'coinmarketcap'
                
            # Дополняем/заменяем данными из CoinGecko
            if symbol_upper in coingecko_data:
                cg_data = coingecko_data[symbol_upper]
                data_sources.append('coingecko')
                
                # Если нет данных CMC, CoinGecko становится приоритетным
                if not priority_source:
                    priority_source = 'coingecko'
                
                # Заполняем отсутствующие поля из CoinGecko
                for key, value in cg_data.items():
                    if key not in combined_token_data or combined_token_data[key] == 0:
                        combined_token_data[key] = value
                        
                # КРИТИЧЕСКОЕ СРАВНЕНИЕ: если расхождения в ключевых метриках > 10%
                if 'coinmarketcap' in data_sources:
                    self._flag_significant_differences(symbol_upper, cmc_data.get(symbol_upper, {}), cg_data)
            
            # Добавляем метаданные
            if combined_token_data:
                combined_token_data['data_sources'] = data_sources
                combined_token_data['priority_source'] = priority_source
                combined_token_data['last_aggregated'] = datetime.now().isoformat()
                combined[symbol_upper] = combined_token_data
        
        return combined

    def _flag_significant_differences(self, symbol: str, cmc_data: Dict, cg_data: Dict):
        """Выявление значительных расхождений между источниками"""
        critical_fields = ['price_usd', 'market_cap', 'volume_24h']
        
        for field in critical_fields:
            cmc_value = cmc_data.get(field, 0)
            cg_value = cg_data.get(field, 0)
            
            if cmc_value > 0 and cg_value > 0:
                difference_percent = abs(cmc_value - cg_value) / cmc_value * 100
                
                if difference_percent > 10:  # Расхождение > 10%
                    logger.warning(
                        f"⚠️ ЗНАЧИТЕЛЬНОЕ РАСХОЖДЕНИЕ {symbol} {field}: "
                        f"CMC={cmc_value:,.2f}, CoinGecko={cg_value:,.2f} "
                        f"({difference_percent:.1f}% разница)"
                    )

    def _log_data_comparison(self, cmc_data: Dict, coingecko_data: Dict, combined_data: Dict):
        """Логирование результатов сравнения данных"""
        logger.info("📊 СВОДКА ПО ИСТОЧНИКАМ ДАННЫХ:")
        logger.info(f"  CoinMarketCap: {len(cmc_data)} токенов")
        logger.info(f"  CoinGecko: {len(coingecko_data)} токенов") 
        logger.info(f"  Объединено: {len(combined_data)} токенов")
        
        # Показываем приоритеты по токенам
        cmc_priority = sum(1 for data in combined_data.values() if data.get('priority_source') == 'coinmarketcap')
        cg_priority = sum(1 for data in combined_data.values() if data.get('priority_source') == 'coingecko')
        
        logger.info(f"  Приоритет CMC: {cmc_priority} токенов")
        logger.info(f"  Приоритет CoinGecko: {cg_priority} токенов")

# Тестирование
async def test_aggregator():
    """Тест агрегатора данных"""
    aggregator = TokenDataAggregator()
    
    test_symbols = ['BIO', 'VITA', 'MYCO', 'ETH']
    result = await aggregator.get_comprehensive_token_data(test_symbols)
    
    print("\n🧪 РЕЗУЛЬТАТЫ АГРЕГАЦИИ:")
    for symbol, data in result.items():
        print(f"\n{symbol}:")
        print(f"  💰 Цена: ${data.get('price_usd', 0):.6f}")
        print(f"  📊 Market Cap: ${data.get('market_cap', 0):,.0f}")
        print(f"  📈 FDV: ${data.get('fully_diluted_valuation', 0):,.0f}")
        print(f"  🔄 Объем 24ч: ${data.get('volume_24h', 0):,.0f}")
        print(f"  📡 Источники: {data.get('data_sources', [])}")
        print(f"  🎯 Приоритет: {data.get('priority_source', 'unknown')}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_aggregator())
