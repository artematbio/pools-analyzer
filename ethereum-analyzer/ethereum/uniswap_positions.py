"""
Uniswap v3 Positions Manager - расширенная версия с получением данных позиций
"""

import asyncio
import logging
import sys
import os
from typing import List, Dict, Any, Optional

# Добавляем пути для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from ethereum.data_sources.rpc_client import create_ethereum_rpc_client, EthereumRPCClient
from ethereum.contracts.uniswap_abis import NONFUNGIBLE_POSITION_MANAGER, get_token_symbol

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def decode_position_data(hex_data):
    """Декодирует данные позиции из hex результата positions()"""
    if not hex_data or hex_data == "0x":
        return None
    
    try:
        # Убираем 0x и разбиваем на 32-байтовые чанки (64 hex символа)
        clean_hex = hex_data[2:]
        chunks = [clean_hex[i:i+64] for i in range(0, len(clean_hex), 64)]
        
        if len(chunks) < 12:
            return None
        
        def decode_int24(hex_chunk):
            """Правильное декодирование signed int24 из 32-байтового chunk"""
            # Берем только последние 3 байта (6 hex символов)
            int24_hex = hex_chunk[-6:]
            value = int(int24_hex, 16)
            
            # Если старший бит установлен, это отрицательное число
            if value >= 2**23:
                value = value - 2**24
            return value
        
        # Декодируем каждое поле согласно ABI positions()
        return {
            'nonce': int(chunks[0], 16),
            'operator': '0x' + chunks[1][-40:],  # последние 20 байт
            'token0': '0x' + chunks[2][-40:],
            'token1': '0x' + chunks[3][-40:], 
            'fee': int(chunks[4], 16),
            'tick_lower': decode_int24(chunks[5]),  # правильное декодирование signed int24
            'tick_upper': decode_int24(chunks[6]),  # правильное декодирование signed int24
            'liquidity': int(chunks[7], 16),
            'fee_growth_inside0_last_x128': int(chunks[8], 16),
            'fee_growth_inside1_last_x128': int(chunks[9], 16),
            'tokens_owed0': int(chunks[10], 16),
            'tokens_owed1': int(chunks[11], 16)
        }
    except Exception as e:
        logger.error(f"Ошибка декодирования позиции: {e}")
        return None

async def test_position_discovery():
    """Расширенный тест получения данных позиций"""
    wallet_address = "0x31AAc4021540f61fe20c3dAffF64BA6335396850"
    
    print(f"🧪 Тестируем получение данных позиций для {wallet_address}")
    
    rpc_client = create_ethereum_rpc_client()
    
    async with rpc_client:
        try:
            # 1. Получаем количество позиций
            balance_call = {
                "method": "eth_call",
                "params": [
                    {
                        "to": NONFUNGIBLE_POSITION_MANAGER,
                        "data": f"0x70a08231{wallet_address[2:].zfill(64)}"
                    },
                    "latest"
                ],
                "id": 1
            }
            
            results = await rpc_client.batch_call([balance_call])
            if not (results and "result" in results[0]):
                print("❌ Не удалось получить balance")
                return
                
            balance = int(results[0]["result"], 16)
            print(f"✅ Найдено {balance} позиций в кошельке")
            
            # 2. Получаем первые 3 token IDs
            max_test = min(3, balance)
            token_id_calls = []
            
            for i in range(max_test):
                data = (
                    "0x2f745c59" +  # tokenOfOwnerByIndex selector
                    wallet_address[2:].zfill(64) +  # owner
                    hex(i)[2:].zfill(64)  # index
                )
                
                token_id_calls.append({
                    "method": "eth_call",
                    "params": [
                        {
                            "to": NONFUNGIBLE_POSITION_MANAGER,
                            "data": data
                        },
                        "latest"
                    ],
                    "id": i + 2
                })
            
            token_results = await rpc_client.batch_call(token_id_calls)
            
            # Извлекаем token IDs
            token_ids = []
            for result in token_results:
                if "result" in result:
                    token_ids.append(int(result["result"], 16))
            
            print(f"✅ Token IDs: {token_ids}")
            
            # 3. Получаем данные позиций для каждого token ID
            position_calls = []
            for i, token_id in enumerate(token_ids):
                data = (
                    "0x99fbab88" +  # positions selector
                    hex(token_id)[2:].zfill(64)  # tokenId
                )
                
                position_calls.append({
                    "method": "eth_call",
                    "params": [
                        {
                            "to": NONFUNGIBLE_POSITION_MANAGER,
                            "data": data
                        },
                        "latest"
                    ],
                    "id": i + 10
                })
            
            position_results = await rpc_client.batch_call(position_calls)
            
            # 4. Декодируем и отображаем данные позиций
            print(f"\n📊 Данные позиций:")
            for i, (token_id, result) in enumerate(zip(token_ids, position_results)):
                if "result" in result:
                    position_data = decode_position_data(result["result"])
                    
                    if position_data:
                        token0_sym = get_token_symbol(position_data['token0'])
                        token1_sym = get_token_symbol(position_data['token1'])
                        
                        fee_percent = position_data['fee'] / 10000
                        
                        print(f"\n  Position {i+1} (Token ID: {token_id}):")
                        print(f"    🏦 Пара: {token0_sym}/{token1_sym}")
                        print(f"    💰 Fee tier: {fee_percent}%") 
                        print(f"    📈 Tick range: {position_data['tick_lower']} to {position_data['tick_upper']}")
                        print(f"    💧 Liquidity: {position_data['liquidity']:,}")
                        print(f"    💎 Token0: {position_data['token0']}")
                        print(f"    💎 Token1: {position_data['token1']}")
                        
                        # Проверка на uncollected fees
                        if position_data['tokens_owed0'] > 0 or position_data['tokens_owed1'] > 0:
                            print(f"    🎁 Unpaid fees: {position_data['tokens_owed0']} | {position_data['tokens_owed1']}")
                    else:
                        print(f"  Position {i+1}: ❌ Не удалось декодировать")
                else:
                    print(f"  Position {i+1}: ❌ Ошибка: {result}")
                    
        except Exception as e:
            logger.error(f"❌ Ошибка теста: {e}")

if __name__ == "__main__":
    asyncio.run(test_position_discovery())

# ======================================================================
# Phase 3: Pool Data Integration 
# ======================================================================

async def fetch_pool_states(pool_addresses: List[str], rpc_client) -> Dict[str, Dict[str, Any]]:
    """
    Получает состояние пулов Uniswap v3 через batch вызовы
    
    Args:
        pool_addresses: Список адресов пулов 
        rpc_client: RPC клиент
        
    Returns:
        Dict с данными каждого пула: {pool_address: {sqrtPriceX96, tick, liquidity, fee}}
    """
    try:
        if not pool_addresses:
            return {}
            
        calls = []
        call_id = 1
        
        # Создаем batch вызовы для каждого пула
        for pool_addr in pool_addresses:
            # slot0() -> sqrtPriceX96, tick, observationIndex, observationCardinality, ...
            slot0_data = "0x3850c7bd"  # slot0() selector
            calls.append({
                "method": "eth_call",
                "params": [{"to": pool_addr, "data": slot0_data}, "latest"],
                "id": call_id
            })
            call_id += 1
            
            # liquidity() -> uint128 liquidity
            liquidity_data = "0x1a686502"  # liquidity() selector  
            calls.append({
                "method": "eth_call", 
                "params": [{"to": pool_addr, "data": liquidity_data}, "latest"],
                "id": call_id
            })
            call_id += 1
            
            # fee() -> uint24 fee
            fee_data = "0xddca3f43"  # fee() selector
            calls.append({
                "method": "eth_call",
                "params": [{"to": pool_addr, "data": fee_data}, "latest"], 
                "id": call_id
            })
            call_id += 1
            
        # Выполняем batch вызов
        results = await rpc_client.batch_call(calls)
        
        # Парсим результаты
        pool_states = {}
        
        for i, pool_addr in enumerate(pool_addresses):
            try:
                # Каждый пул имеет 3 вызова: slot0, liquidity, fee
                slot0_result = results[i * 3]
                liquidity_result = results[i * 3 + 1] 
                fee_result = results[i * 3 + 2]
                
                if all("result" in r for r in [slot0_result, liquidity_result, fee_result]):
                    # Декодируем slot0 (sqrtPriceX96, tick, ...)
                    slot0_hex = slot0_result["result"]
                    sqrt_price_x96 = int(slot0_hex[2:66], 16)  # Первые 32 байта
                    tick = int(slot0_hex[66:130], 16)  # Следующие 32 байта
                    # Если tick больше 2^31, это отрицательное число
                    if tick >= 2**31:
                        tick = tick - 2**32
                    
                    # Декодируем liquidity
                    liquidity = int(liquidity_result["result"], 16)
                    
                    # Декодируем fee 
                    fee = int(fee_result["result"], 16)
                    
                    pool_states[pool_addr] = {
                        "sqrtPriceX96": sqrt_price_x96,
                        "tick": tick,
                        "liquidity": liquidity,
                        "fee": fee
                    }
                    
                    print(f"✅ Pool {pool_addr[:8]}...: tick={tick}, liquidity={liquidity:,}, fee={fee}")
                    
                else:
                    print(f"❌ Ошибка получения данных для пула {pool_addr}")
                    
            except Exception as e:
                print(f"❌ Ошибка парсинга пула {pool_addr}: {e}")
                
        return pool_states
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения состояния пулов: {e}")
        return {}

async def get_pool_address_from_tokens(token0: str, token1: str, fee: int, rpc_client) -> Optional[str]:
    """
    Получает адрес пула через UniswapV3Factory.getPool()
    
    Args:
        token0: Адрес первого токена
        token1: Адрес второго токена  
        fee: Fee tier (500, 3000, 10000)
        rpc_client: RPC клиент
        
    Returns:
        Адрес пула или None
    """
    try:
        from ethereum.contracts.uniswap_abis import UNISWAP_V3_FACTORY
        
        # getPool(address,address,uint24) selector 
        selector = "0x1698ee82"
        
        # Сортируем токены (token0 < token1)
        if token0.lower() > token1.lower():
            token0, token1 = token1, token0
            
        data = (
            selector +
            token0[2:].zfill(64) +  # token0
            token1[2:].zfill(64) +  # token1  
            hex(fee)[2:].zfill(64)  # fee
        )
        
        call = {
            "method": "eth_call",
            "params": [{"to": UNISWAP_V3_FACTORY, "data": data}, "latest"],
            "id": 1
        }
        
        results = await rpc_client.batch_call([call])
        
        if results and "result" in results[0] and results[0]["result"] != "0x" + "0" * 64:
            pool_address = "0x" + results[0]["result"][-40:]  # Последние 20 байтов
            return pool_address
            
        return None
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения адреса пула: {e}")
        return None

async def fetch_token_prices_coingecko_ethereum(token_addresses: List[str], client) -> Dict[str, Any]:
    """
    Получает цены Ethereum токенов через CoinGecko API
    
    Args:
        token_addresses: Список адресов токенов Ethereum
        client: HTTP клиент
        
    Returns:
        Словарь {token_address: price_usd}
    """
    try:
        import httpx
        from decimal import Decimal
        
        if not token_addresses:
            return {}
            
        # CoinGecko Pro API для Ethereum токенов
        url = "https://pro-api.coingecko.com/api/v3/simple/token_price/ethereum"
        params = {
            "contract_addresses": ",".join(token_addresses),
            "vs_currencies": "usd"
        }
        
        # API ключ если есть (опционально)
        headers = {}
        
        # Импортируем API ключ
        COINGECKO_API_KEY = "CG-9MrJcucBMMx5HKnXeVBD8oSb"  # Тот же ключ что в pool_analyzer.py
        
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
            
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        
        # Обрабатываем ответ: {"address": {"usd": price}}
        prices = {}
        for address, price_data in response_data.items():
            if "usd" in price_data:
                prices[address.lower()] = Decimal(str(price_data["usd"]))
                
        print(f"✅ Получены цены для {len(prices)} Ethereum токенов")
        return prices
        
    except Exception as e:
        print(f"❌ Ошибка получения цен Ethereum токенов: {e}")
        return {}

# Ethereum токены для CoinGecko (популярные)
ETHEREUM_TOKEN_COINGECKO_IDS = {
    "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2": "wrapped-ethereum",  # WETH
    "0x6B175474E89094C44Da98b954EedeAC495271d0F": "dai",               # DAI  
    "0xA0b86a33E6441621DA8C04F53cFe4B6DC2b94c9E": "usd-coin",          # USDC
    "0xdAC17F958D2ee523a2206206994597C13D831ec7": "tether",             # USDT
    "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599": "wrapped-bitcoin",    # WBTC
    "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984": "uniswap",           # UNI
    "0x7D1AfA7B718fb893dB30A3aBc0Cfc608AaCfeBB0": "polygon",           # MATIC
    "0x514910771AF9Ca656af840dff83E8264EcF986CA": "chainlink",          # LINK
}

async def test_pool_states():
    """Тест получения состояния пулов"""
    try:
        from ethereum.data_sources.rpc_client import create_ethereum_rpc_client
        
        # Тестовые адреса популярных пулов 
        pool_addresses = [
            "0x8ad599c3A0ff1De082011EFDDc58f1908eb6e6D8",  # USDC/WETH 0.3%
            "0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",  # USDC/WETH 0.05%  
        ]
        
        print("🔍 Тестируем получение состояния пулов...")
        
        rpc_client = create_ethereum_rpc_client()
        async with rpc_client:
            pool_states = await fetch_pool_states(pool_addresses, rpc_client)
            
            print(f"\n📊 Результаты для {len(pool_states)} пулов:")
            for pool_addr, state in pool_states.items():
                print(f"\n  🏦 Pool: {pool_addr}")
                print(f"    📈 Tick: {state['tick']}")
                print(f"    💧 Liquidity: {state['liquidity']:,}")
                print(f"    💰 Fee: {state['fee']} ({state['fee']/10000}%)")
                print(f"    📊 SqrtPriceX96: {state['sqrtPriceX96']}")
            
    except Exception as e:
        print(f"❌ Ошибка теста состояния пулов: {e}")

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(test_pool_states())

# ======================================================================
# Phase 4: Analytics & Math 🧮
# ======================================================================

async def get_token_decimals(token_address: str, rpc_client) -> int:
    """
    Получает количество decimals для токена через ERC20 decimals() вызов
    
    Args:
        token_address: Адрес токена
        rpc_client: RPC клиент
        
    Returns:
        Количество decimals (по умолчанию 18)
    """
    try:
        # decimals() selector = 0x313ce567
        decimals_data = "0x313ce567"
        
        call = {
            "method": "eth_call",
            "params": [
                {"to": token_address, "data": decimals_data},
                "latest"
            ],
            "id": 1
        }
        
        results = await rpc_client.batch_call([call])
        
        if results and "result" in results[0] and results[0]["result"] != "0x":
            decimals = int(results[0]["result"], 16)
            return decimals
        else:
            # По умолчанию 18 decimals для большинства токенов
            return 18
            
    except Exception as e:
        print(f"⚠️ Не удалось получить decimals для {token_address}, используем 18: {e}")
        return 18

async def calculate_position_value_usd(position_data: Dict[str, Any], pool_state: Dict[str, Any], token_prices: Dict[str, Any], rpc_client=None) -> Dict[str, Any]:
    """
    Рассчитывает стоимость позиции в USD с правильным учетом decimals
    
    Args:
        position_data: Данные позиции из positions() call
        pool_state: Состояние пула из slot0() и liquidity()
        token_prices: Цены токенов в USD
        rpc_client: RPC клиент для получения decimals (опционально)
        
    Returns:
        Dict с amount0, amount1, value_usd, is_in_range
    """
    try:
        from ethereum.math.tick_math import calculate_amounts_from_liquidity
        from decimal import Decimal
        
        if not position_data or position_data.get('liquidity', 0) == 0:
            return {
                'amount0': 0,
                'amount1': 0, 
                'value_usd': 0,
                'in_range': False,  # ИСПРАВЛЕНИЕ: используем 'in_range' а не 'is_in_range'
                'status': 'inactive'
            }
        
        # Получаем данные позиции
        liquidity = position_data['liquidity']
        tick_lower = position_data['tick_lower']
        tick_upper = position_data['tick_upper']
        token0 = position_data['token0'].lower()
        token1 = position_data['token1'].lower()
        
        # Получаем текущее состояние пула
        sqrt_price_x96 = pool_state['sqrtPriceX96']
        current_tick = pool_state['tick']
        
        # Проверяем находится ли позиция в диапазоне
        is_in_range = tick_lower <= current_tick <= tick_upper
        
        # Получаем decimals токенов
        if rpc_client:
            try:
                decimals0 = await get_token_decimals(position_data['token0'], rpc_client)
                decimals1 = await get_token_decimals(position_data['token1'], rpc_client)
            except:
                # Fallback: стандартные decimals для известных токенов
                decimals0 = 18 if token0 != "0xa0b86a33e6441621da8c04f53cfe4b6dc2b94c9e" else 6  # USDC has 6 decimals
                decimals1 = 18
        else:
            # Стандартные decimals для известных токенов
            decimals0 = 18 if token0 != "0xa0b86a33e6441621da8c04f53cfe4b6dc2b94c9e" else 6  # USDC has 6 decimals  
            decimals1 = 18
        
        print(f"💡 Token decimals: token0={decimals0}, token1={decimals1}")
        
        # Рассчитываем amounts токенов (в wei)
        amounts = calculate_amounts_from_liquidity(
            liquidity=liquidity,
            sqrt_price_x96_current=sqrt_price_x96,
            tick_lower=tick_lower,
            tick_upper=tick_upper
        )
        
        # Конвертируем в human-readable amounts с учетом decimals
        amount0_raw = float(amounts['amount0'])
        amount1_raw = float(amounts['amount1'])
        
        amount0 = amount0_raw / (10 ** decimals0)  # Конвертируем из wei
        amount1 = amount1_raw / (10 ** decimals1)  # Конвертируем из wei
        
        print(f"💧 Raw amounts: token0={amount0_raw:.0f}, token1={amount1_raw:.0f}")
        print(f"💧 Human amounts: token0={amount0:.8f}, token1={amount1:.2f}")
        
        # Получаем цены токенов
        price0 = float(token_prices.get(token0.lower(), 0))
        price1 = float(token_prices.get(token1.lower(), 0))
        
        print(f"💰 Token prices: {token0[:8]}... = ${price0}, {token1[:8]}... = ${price1}")
        
        # Рассчитываем стоимость в USD
        value0_usd = amount0 * price0
        value1_usd = amount1 * price1
        total_value_usd = value0_usd + value1_usd
        
        print(f"💎 USD values: token0=${value0_usd:.2f}, token1=${value1_usd:.2f}, total=${total_value_usd:.2f}")
        
        return {
            'amount0': amount0,
            'amount1': amount1,
            'value0_usd': value0_usd,
            'value1_usd': value1_usd,
            'value_usd': total_value_usd,
            'in_range': is_in_range,  # ИСПРАВЛЕНИЕ: используем 'in_range' а не 'is_in_range'
            'status': 'active' if is_in_range else 'out_of_range',
            'current_tick': current_tick,
            'tick_range': f"{tick_lower} to {tick_upper}",
            'decimals0': decimals0,
            'decimals1': decimals1
        }
        
    except Exception as e:
        print(f"❌ Ошибка расчета стоимости позиции: {e}")
        import traceback
        traceback.print_exc()
        return {
            'amount0': 0,
            'amount1': 0,
            'value_usd': 0,
            'in_range': False,  # ИСПРАВЛЕНИЕ: используем 'in_range' а не 'is_in_range'
            'status': 'error',
            'error': str(e)
        }

async def check_position_in_range(position_data: Dict[str, Any], pool_state: Dict[str, Any]) -> Dict[str, Any]:
    """
    Проверяет находится ли позиция в текущем диапазоне цен
    
    Args:
        position_data: Данные позиции 
        pool_state: Текущее состояние пула
        
    Returns:
        Dict с информацией о статусе позиции
    """
    try:
        current_tick = pool_state['tick']
        tick_lower = position_data['tick_lower']
        tick_upper = position_data['tick_upper']
        liquidity = position_data.get('liquidity', 0)
        
        is_in_range = tick_lower <= current_tick <= tick_upper
        
        # Специальная проверка для full range позиций (почти MIN_TICK to MAX_TICK)
        is_full_range = abs(tick_lower - (-887272)) <= 100 and abs(tick_upper - 887272) <= 100
        if is_full_range:
            is_in_range = True  # Full range позиции всегда in range
        
        # Рассчитываем расстояние до границ
        distance_to_lower = current_tick - tick_lower
        distance_to_upper = tick_upper - current_tick
        
        if is_in_range:
            status = "🟢 IN RANGE"
            distance_info = f"До нижней границы: {distance_to_lower}, до верхней: {distance_to_upper}"
        elif current_tick < tick_lower:
            status = "🔴 BELOW RANGE"
            distance_info = f"Ниже диапазона на {abs(distance_to_lower)} ticks"
        else:
            status = "🔴 ABOVE RANGE"  
            distance_info = f"Выше диапазона на {distance_to_upper} ticks"
            
        return {
            'in_range': is_in_range,  # ИСПРАВЛЕНИЕ: используем 'in_range' а не 'is_in_range'
            'status': status,
            'current_tick': current_tick,
            'tick_lower': tick_lower,
            'tick_upper': tick_upper,
            'distance_info': distance_info,
            'is_active': liquidity > 0 and is_in_range
        }
        
    except Exception as e:
        return {
            'in_range': False,  # ИСПРАВЛЕНИЕ: используем 'in_range' а не 'is_in_range'
            'status': "❌ ERROR",
            'error': str(e)
        }

async def calculate_uncollected_fees(position_data: Dict[str, Any], token_prices: Dict[str, Any], rpc_client=None) -> Dict[str, Any]:
    """
    Рассчитывает неполученные комиссии с правильным учетом decimals
    
    Args:
        position_data: Данные позиции
        token_prices: Цены токенов в USD
        rpc_client: RPC клиент для получения decimals (опционально)
        
    Returns:
        Dict с информацией о комиссиях
    """
    try:
        tokens_owed0 = position_data.get('tokens_owed0', 0)
        tokens_owed1 = position_data.get('tokens_owed1', 0)
        
        token0 = position_data['token0'].lower()
        token1 = position_data['token1'].lower()
        
        # Получаем decimals токенов
        if rpc_client:
            try:
                decimals0 = await get_token_decimals(position_data['token0'], rpc_client)
                decimals1 = await get_token_decimals(position_data['token1'], rpc_client)
            except:
                decimals0 = 18 if token0 != "0xa0b86a33e6441621da8c04f53cfe4b6dc2b94c9e" else 6
                decimals1 = 18
        else:
            decimals0 = 18 if token0 != "0xa0b86a33e6441621da8c04f53cfe4b6dc2b94c9e" else 6
            decimals1 = 18
        
        # Получаем цены токенов
        price0 = float(token_prices.get(token0, 0))
        price1 = float(token_prices.get(token1, 0))
        
        # Конвертируем fees в human-readable формат
        fee0_amount = tokens_owed0 / (10 ** decimals0)
        fee1_amount = tokens_owed1 / (10 ** decimals1)
        
        # Рассчитываем стоимость комиссий в USD
        fee0_usd = fee0_amount * price0
        fee1_usd = fee1_amount * price1
        
        total_fees_usd = fee0_usd + fee1_usd
        
        has_fees = tokens_owed0 > 0 or tokens_owed1 > 0
        
        return {
            'tokens_owed0': tokens_owed0,
            'tokens_owed1': tokens_owed1,
            'fee0_amount': fee0_amount,
            'fee1_amount': fee1_amount,
            'fee0_usd': fee0_usd,
            'fee1_usd': fee1_usd,
            'total_fees_usd': total_fees_usd,
            'has_uncollected_fees': has_fees,
            'fee_info': f"Token0: {fee0_amount:.8f}, Token1: {fee1_amount:.2f}" if has_fees else "No uncollected fees"
        }
        
    except Exception as e:
        return {
            'tokens_owed0': 0,
            'tokens_owed1': 0,
            'total_fees_usd': 0,
            'has_uncollected_fees': False,
            'error': str(e)
        }

async def get_pool_address_from_position(position_data: Dict[str, Any], rpc_client) -> Optional[str]:
    """
    Получает адрес пула для позиции через UniswapV3Factory
    
    Args:
        position_data: Данные позиции с token0, token1, fee
        rpc_client: RPC клиент
        
    Returns:
        Адрес пула или None
    """
    try:
        token0 = position_data['token0']
        token1 = position_data['token1']
        fee = position_data['fee']
        
        return await get_pool_address_from_tokens(token0, token1, fee, rpc_client)
        
    except Exception as e:
        print(f"❌ Ошибка получения адреса пула: {e}")
        return None

async def analyze_position_complete(position_data: Dict[str, Any], rpc_client, token_prices: Dict[str, Any]) -> Dict[str, Any]:
    """
    Полный анализ позиции - объединяет все аналитические функции
    
    Args:
        position_data: Данные позиции
        rpc_client: RPC клиент
        token_prices: Цены токенов
        
    Returns:
        Полный анализ позиции
    """
    try:
        # Получаем адрес пула
        pool_address = await get_pool_address_from_position(position_data, rpc_client)
        
        if not pool_address:
            return {'error': 'Could not find pool address'}
            
        # Получаем состояние пула
        pool_states = await fetch_pool_states([pool_address], rpc_client)
        
        if not pool_states or pool_address not in pool_states:
            return {'error': 'Could not fetch pool state'}
            
        pool_state = pool_states[pool_address]
        
        # Выполняем все анализы
        value_analysis = await calculate_position_value_usd(position_data, pool_state, token_prices, rpc_client)
        range_analysis = await check_position_in_range(position_data, pool_state)
        fees_analysis = await calculate_uncollected_fees(position_data, token_prices, rpc_client)
        
        # Получаем символы токенов
        token0_symbol = get_token_symbol(position_data.get('token0', ''))
        token1_symbol = get_token_symbol(position_data.get('token1', ''))
        
        # Добавляем символы в value_analysis
        if isinstance(value_analysis, dict):
            value_analysis['token0_symbol'] = token0_symbol
            value_analysis['token1_symbol'] = token1_symbol
            value_analysis['token0_amount_formatted'] = value_analysis.get('amount0', 0)
            value_analysis['token1_amount_formatted'] = value_analysis.get('amount1', 0)
        
        # Объединяем результаты
        return {
            'pool_address': pool_address,
            'pool_state': pool_state,
            'value_analysis': value_analysis,
            'range_analysis': range_analysis,
            'fees_analysis': fees_analysis,
            'position_data': position_data,
            'token0_symbol': token0_symbol,
            'token1_symbol': token1_symbol
        }
        
    except Exception as e:
        return {'error': f'Analysis failed: {str(e)}'}

async def test_phase4_analytics():
    """Тест аналитических функций Phase 4"""
    try:
        from ethereum.data_sources.rpc_client import create_ethereum_rpc_client
        
        print('🧮 Тестируем Phase 4: Analytics & Math')
        print('=' * 60)
        
        # Возьмем активную позицию из нашего анализа
        test_position = {
            'token0': '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2',  # WETH
            'token1': '0xcb1592591996765ec0efc1f92599a19767ee5ffa',  # BIO
            'fee': 3000,  # 0.3%
            'liquidity': 62289561593523376994406,
            'tick_lower': 104280,
            'tick_upper': 108180,
            'tokens_owed0': 0,
            'tokens_owed1': 0
        }
        
        # Пример цен токенов
        token_prices = {
            '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2': 3500.0,  # WETH
            '0xcb1592591996765ec0efc1f92599a19767ee5ffa': 0.070623  # BIO
        }
        
        print('📊 Анализируем тестовую позицию WETH/BIO...')
        
        rpc_client = create_ethereum_rpc_client()
        async with rpc_client:
            analysis = await analyze_position_complete(test_position, rpc_client, token_prices)
            
            if 'error' in analysis:
                print(f'❌ Ошибка анализа: {analysis["error"]}')
            else:
                print('✅ Анализ завершен!')
                print(f'📍 Pool address: {analysis["pool_address"]}')
                print(f'💰 Total value: ${analysis["value_analysis"]["value_usd"]:.2f}')
                print(f'📈 Status: {analysis["range_analysis"]["status"]}')
                print(f'🎁 Fees: ${analysis["fees_analysis"]["total_fees_usd"]:.2f}')
            
    except Exception as e:
        print(f'❌ Ошибка теста: {e}')
        import traceback
        traceback.print_exc()

# if __name__ == "__main__":
#     import asyncio
#     asyncio.run(test_phase4_analytics())

# ======================================================================
# Функции для полного анализа портфеля с фильтрацией
# ======================================================================

async def get_user_positions_filtered(wallet_address: str, min_value_usd: float = 1000.0, rpc_client=None) -> Dict[str, Any]:
    """
    Получает все позиции пользователя с фильтрацией по минимальной стоимости
    
    Args:
        wallet_address: Адрес кошелька для анализа
        min_value_usd: Минимальная стоимость позиции в USD для включения в отчет (по умолчанию $1000)
        rpc_client: RPC клиент (если не передан, создается новый)
        
    Returns:
        Dict с отфильтрованными позициями и общей статистикой
    """
    if rpc_client is None:
        async with create_ethereum_rpc_client() as rpc_client:
            return await _get_positions_with_client(wallet_address, min_value_usd, rpc_client)
    else:
        return await _get_positions_with_client(wallet_address, min_value_usd, rpc_client)


async def _get_positions_with_client(wallet_address: str, min_value_usd: float, rpc_client) -> Dict[str, Any]:
    """Внутренняя функция для работы с уже инициализированным RPC клиентом"""
    try:
        print(f"🔍 Анализируем позиции для кошелька: {wallet_address}")
        print(f"💰 Минимальная стоимость для включения в отчет: ${min_value_usd}")
        
        # 1. Получаем количество позиций через batch_call
        balance_call = [{
            "method": "eth_call",
            "params": [{
                "to": NONFUNGIBLE_POSITION_MANAGER,
                "data": "0x70a08231" + wallet_address[2:].zfill(64)  # balanceOf
            }, "latest"],
            "id": 1
        }]
        
        balance_results = await rpc_client.batch_call(balance_call)
        
        if not balance_results or "result" not in balance_results[0]:
            return {"error": "Failed to get balance", "positions": [], "total_positions": 0}
            
        balance = int(balance_results[0]["result"], 16)
        print(f"📊 Найдено {balance} позиций NFT")
        
        if balance == 0:
            return {"positions": [], "total_positions": 0, "filtered_positions": 0, "total_value_usd": 0}
        
        # 2. Получаем token IDs через batch calls
        token_calls = []
        for i in range(balance):
            data = (
                "0x2f745c59" +  # tokenOfOwnerByIndex selector
                wallet_address[2:].zfill(64) +  # owner address
                hex(i)[2:].zfill(64)  # index
            )
            token_calls.append({
                "method": "eth_call",
                "params": [{"to": NONFUNGIBLE_POSITION_MANAGER, "data": data}, "latest"],
                "id": i
            })
        
        token_results = await rpc_client.batch_call(token_calls)
        
        # Извлекаем token IDs
        token_ids = []
        for result in token_results:
            if "result" in result:
                token_ids.append(int(result["result"], 16))
        
        print(f"✅ Token IDs: {token_ids}")
        
        # 3. Получаем данные позиций
        position_calls = []
        for i, token_id in enumerate(token_ids):
            data = (
                "0x99fbab88" +  # positions selector
                hex(token_id)[2:].zfill(64)  # tokenId
            )
            position_calls.append({
                "method": "eth_call",
                "params": [{"to": NONFUNGIBLE_POSITION_MANAGER, "data": data}, "latest"],
                "id": i + 10
            })
        
        position_results = await rpc_client.batch_call(position_calls)
        
        # 4. Получаем цены токенов из CoinGecko
        token_prices = await fetch_token_prices_coingecko_ethereum()
        print(f"💰 Получено цен токенов: {len(token_prices)}")
        
        # 5. Анализируем каждую позицию
        positions = []
        total_value_usd = 0
        filtered_out_count = 0
        
        for i, (token_id, result) in enumerate(zip(token_ids, position_results)):
            if "result" in result:
                position_data = decode_position_data(result["result"])
                
                if position_data:
                    print(f"\n📍 Анализируем позицию {i+1} (Token ID: {token_id})...")
                    
                    # Полный анализ позиции
                    analysis = await analyze_position_complete(position_data, rpc_client, token_prices)
                    
                    if 'error' not in analysis:
                        position_value = analysis.get("value_analysis", {}).get("value_usd", 0)
                        
                        if position_value >= min_value_usd:
                            # Добавляем token_id к анализу
                            analysis["token_id"] = token_id
                            positions.append(analysis)
                            total_value_usd += position_value
                            print(f"✅ Позиция включена в отчет: ${position_value:.2f}")
                        else:
                            filtered_out_count += 1
                            print(f"⚠️ Позиция отфильтрована (${position_value:.2f} < ${min_value_usd})")
                    else:
                        print(f"❌ Ошибка анализа позиции {token_id}: {analysis.get('error')}")
        
        return {
            "positions": positions,
            "total_positions": balance,
            "filtered_positions": len(positions),
            "filtered_out": filtered_out_count,
            "total_value_usd": total_value_usd,
            "min_value_filter": min_value_usd,
            "wallet_address": wallet_address
        }
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения позиций: {e}")
        import traceback
        traceback.print_exc()
        return {"error": str(e), "positions": [], "total_positions": 0}


async def fetch_token_prices_coingecko_ethereum() -> Dict[str, float]:
    """
    Получает цены токенов Ethereum через CoinGecko API
    
    Returns:
        Dict с ценами токенов {token_address_lowercase: price_usd}
    """
    import aiohttp
    import os
    
    # Получаем API key из переменной окружения
    COINGECKO_API_KEY = "CG-9MrJcucBMMx5HKnXeVBD8oSb"
    
    # Основные токены Ethereum для мониторинга
    token_addresses = [
        "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",  # WETH
        "0xcb1592591996765ec0efc1f92599a19767ee5ffa",  # BIO (правильный адрес)
        "0x81f8f0bb1cb2a06649e51913a151f0e7ef6fa321",  # VITA (правильный адрес)
        "0xa0b73e1ff0b80914ab6fe0444e65848c4c34450b",  # CRON
        "0x6b175474e89094c44da98b954eedeac495271d0f",  # DAI
        "0xa0b86a33e6e114011c36e3c3b8c67c63b8d0fcf9",  # USDC
        "0xdac17f958d2ee523a2206206994597c13d831ec7",  # USDT
    ]
    
    try:
        # Формируем строку адресов для API
        addresses_str = ",".join(token_addresses)
        
        # Правильный URL для Pro API
        url = f"https://pro-api.coingecko.com/api/v3/simple/token_price/ethereum?contract_addresses={addresses_str}&vs_currencies=usd"
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'x-cg-pro-api-key': COINGECKO_API_KEY
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    
                    # Преобразуем данные в нужный формат
                    prices = {}
                    for address, price_data in data.items():
                        if isinstance(price_data, dict) and 'usd' in price_data:
                            prices[address.lower()] = float(price_data['usd'])
                    
                    print(f"✅ Получены цены для {len(prices)} токенов")
                    return prices
                else:
                    print(f"❌ Ошибка CoinGecko API: {response.status}")
                    return {}
                    
    except Exception as e:
        print(f"❌ Ошибка получения цен: {e}")
        return {}


if __name__ == "__main__":
    async def main():
        # Тестовый кошелек
        test_wallet = "0x31AAc4021540f61fe20c3dAffF64BA6335396850"
        
        # Получаем позиции с фильтрацией по $1000
        result = await get_user_positions_filtered(test_wallet, min_value_usd=1000.0)
        
        if "error" not in result:
            print(f"\n🎯 РЕЗУЛЬТАТЫ АНАЛИЗА:")
            print(f"📊 Всего позиций: {result['total_positions']}")
            print(f"✅ Включено в отчет: {result['filtered_positions']}")
            print(f"⚠️ Отфильтровано: {result['filtered_out']}")
            print(f"💰 Общая стоимость: ${result['total_value_usd']:.2f}")
            
            for i, pos in enumerate(result['positions'], 1):
                print(f"\nПозиция {i} (Token ID: {pos['token_id']}):")
                print(f"  💰 Стоимость: ${pos['value_analysis']['value_usd']:.2f}")
                print(f"  📈 Статус: {pos['range_analysis']['status']}")
        else:
            print(f"❌ Ошибка: {result['error']}")
    
    import asyncio
    asyncio.run(main())