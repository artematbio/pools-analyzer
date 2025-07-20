"""
Uniswap v3 Market Data Module
Получение данных пулов через Uniswap v3 Subgraph
"""

import asyncio
import logging
from typing import Dict, List, Any, Optional
import httpx
from datetime import datetime, timedelta
import sys
import os

# Добавляем пути для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from shared.rate_limiter import APIRateLimiter

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Константы и конфигурация
THEGRAPH_API_KEY = os.getenv('THEGRAPH_API_KEY', 'ed5e8fbed08836e4e5e540c65d635f0d')
UNISWAP_V3_SUBGRAPH_ID = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"
UNISWAP_V3_SUBGRAPH = f"https://gateway.thegraph.com/api/{THEGRAPH_API_KEY}/subgraphs/id/{UNISWAP_V3_SUBGRAPH_ID}"

class UniswapMarketData:
    """Класс для работы с рыночными данными Uniswap v3"""
    
    def __init__(self):
        self.rate_limiter = APIRateLimiter()
        
    async def fetch_pool_data(self, pool_addresses: List[str], http_client: httpx.AsyncClient = None) -> Dict[str, Any]:
        """
        Получает данные пулов через Uniswap v3 Subgraph
        
        Args:
            pool_addresses: Список адресов пулов
            http_client: HTTP клиент
            
        Returns:
            Словарь с данными пулов
        """
        if not pool_addresses:
            return {}
            
        # Создаем HTTP клиент если не передан
        close_client = False
        if http_client is None:
            http_client = httpx.AsyncClient(timeout=30.0)
            close_client = True
            
        try:
            # Формируем GraphQL запрос для получения данных пулов
            pool_addresses_lower = [addr.lower() for addr in pool_addresses]
            
            query = """
            query GetPoolsData($poolIds: [ID!]!) {
              pools(where: {id_in: $poolIds}) {
                id
                token0 {
                  id
                  symbol
                  name
                  decimals
                }
                token1 {
                  id
                  symbol
                  name
                  decimals
                }
                feeTier
                liquidity
                sqrtPrice
                tick
                token0Price
                token1Price
                volumeUSD
                totalValueLockedUSD
                volumeToken0
                volumeToken1
                txCount
                totalValueLockedToken0
                totalValueLockedToken1
                poolDayData(first: 7, orderBy: date, orderDirection: desc) {
                  date
                  volumeUSD
                  tvlUSD
                  high
                  low
                  open
                  close
                }
              }
            }
            """
            
            variables = {
                "poolIds": pool_addresses_lower
            }
            
            # Отправляем запрос с rate limiting
            async with self.rate_limiter.rate_limited_request('the_graph', 'subgraph_query'):
                response = await http_client.post(
                    UNISWAP_V3_SUBGRAPH,
                    json={
                        "query": query,
                        "variables": variables
                    },
                    headers={
                        "Content-Type": "application/json"
                    }
                )
            
            if response.status_code != 200:
                logger.error(f"Subgraph request failed: {response.status_code}")
                return {}
                
            data = response.json()
            
            if "errors" in data:
                logger.error(f"Subgraph errors: {data['errors']}")
                return {}
                
            pools_data = data.get("data", {}).get("pools", [])
            
            # Обрабатываем результаты
            result = {}
            for pool in pools_data:
                pool_address = pool["id"]
                
                # Парсим основные данные пула
                pool_info = {
                    "pool_address": pool_address,
                    "token0": {
                        "address": pool["token0"]["id"],
                        "symbol": pool["token0"]["symbol"],
                        "name": pool["token0"]["name"],
                        "decimals": int(pool["token0"]["decimals"])
                    },
                    "token1": {
                        "address": pool["token1"]["id"],
                        "symbol": pool["token1"]["symbol"],
                        "name": pool["token1"]["name"],
                        "decimals": int(pool["token1"]["decimals"])
                    },
                    "fee_tier": int(pool["feeTier"]),
                    "liquidity": pool["liquidity"],
                    "sqrt_price": pool["sqrtPrice"],
                    "tick": int(pool["tick"]) if pool["tick"] else None,
                    "token0_price": float(pool["token0Price"]) if pool["token0Price"] else 0.0,
                    "token1_price": float(pool["token1Price"]) if pool["token1Price"] else 0.0,
                    "volume_usd": float(pool["volumeUSD"]) if pool["volumeUSD"] else 0.0,
                    "tvl_usd": float(pool["totalValueLockedUSD"]) if pool["totalValueLockedUSD"] else 0.0,
                    "volume_token0": float(pool["volumeToken0"]) if pool["volumeToken0"] else 0.0,
                    "volume_token1": float(pool["volumeToken1"]) if pool["volumeToken1"] else 0.0,
                    "tx_count": int(pool["txCount"]) if pool["txCount"] else 0,
                    "tvl_token0": float(pool["totalValueLockedToken0"]) if pool["totalValueLockedToken0"] else 0.0,
                    "tvl_token1": float(pool["totalValueLockedToken1"]) if pool["totalValueLockedToken1"] else 0.0,
                }
                
                # Добавляем исторические данные за 7 дней
                historical_data = []
                for day_data in pool.get("poolDayData", []):
                    historical_data.append({
                        "date": day_data["date"],
                        "volume_usd": float(day_data["volumeUSD"]) if day_data["volumeUSD"] else 0.0,
                        "tvl_usd": float(day_data["tvlUSD"]) if day_data["tvlUSD"] else 0.0,
                        "high": float(day_data["high"]) if day_data["high"] else 0.0,
                        "low": float(day_data["low"]) if day_data["low"] else 0.0,
                        "open": float(day_data["open"]) if day_data["open"] else 0.0,
                        "close": float(day_data["close"]) if day_data["close"] else 0.0,
                    })
                
                pool_info["historical_data"] = historical_data
                pool_info["fetch_timestamp"] = datetime.utcnow().isoformat()
                
                result[pool_address] = pool_info
                
            logger.info(f"✅ Получены данные для {len(result)} пулов из Uniswap Subgraph")
            return result
            
        except Exception as e:
            logger.error(f"❌ Ошибка получения данных Uniswap Subgraph: {e}")
            return {}
        finally:
            if close_client:
                await http_client.aclose()


async def fetch_uniswap_subgraph_data(pool_addresses: List[str], http_client: httpx.AsyncClient = None) -> Dict[str, Any]:
    """
    Удобная функция для получения данных пулов Uniswap v3
    Аналог fetch_raydium_pool_market_data()
    
    Args:
        pool_addresses: Список адресов пулов
        http_client: HTTP клиент
        
    Returns:
        Словарь с данными пулов
    """
    market_data = UniswapMarketData()
    return await market_data.fetch_pool_data(pool_addresses, http_client)


async def test_uniswap_market_data():
    """Тестирование получения данных пулов"""
    
    # Тестовые пулы из наших позиций
    test_pools = [
        "0x2dc8fbafc10da100f2f12807b93cbb3e5ff7e6b0",  # VITA/BIO
        "0x08a5a1e2671839dadc25e2e20f9206fd33c88092",  # WETH/BIO
    ]
    
    print("🧪 Тестирование Uniswap Market Data...")
    print(f"Тестовые пулы: {len(test_pools)}")
    
    async with httpx.AsyncClient() as client:
        pools_data = await fetch_uniswap_subgraph_data(test_pools, client)
        
        print(f"\n📊 Результаты для {len(pools_data)} пулов:")
        for pool_addr, data in pools_data.items():
            print(f"\n🏊 Пул: {pool_addr}")
            print(f"  Токены: {data['token0']['symbol']}/{data['token1']['symbol']}")
            print(f"  TVL: ${data['tvl_usd']:,.2f}")
            print(f"  Volume 24h: ${data['volume_usd']:,.2f}")
            print(f"  Fee Tier: {data['fee_tier']/10000:.2f}%")
            print(f"  TX Count: {data['tx_count']:,}")
            print(f"  Historical data: {len(data['historical_data'])} дней")


if __name__ == "__main__":
    asyncio.run(test_uniswap_market_data()) 