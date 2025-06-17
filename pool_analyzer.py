import os
import asyncio
import json
import math
import base64
import traceback
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Set, Any
from decimal import Decimal, getcontext, ROUND_DOWN
from dotenv import load_dotenv
import random

import httpx
from construct import Struct, Int8ul, Int16ul, Int32sl, Int32ul, Int64ul, Bytes, Array, Pass, Adapter
from solders.pubkey import Pubkey

# Импортируем функцию get_clmm_positions из positions.py
from positions import get_clmm_positions

# --- Определение основных целевых пулов для детального анализа ---
TARGET_POOL_ID_1 = "DojNuRx9Ncky7BbWRfsLmJg2oYb8qsYD344XufUHAjbJ"  # BIO/CURES
TARGET_POOL_ID_2 = "4LuGwek6Jv4xpGvsQwZXonmLuRhrpHtmKVs95bN9EkTm"  # SOL/BIO
TARGET_POOL_ID_3 = "DCNWwwSHSLYRR9WbBunkRaPEC73ba68yQNhytap3qRJZ"  # BIO/QBIO
TARGET_POOL_ID_4 = "3K2NaZx1KAyJqsdUkUu9qgtk1qJEs6wbygjLxJvvXrLhq" # BIO/GROW
TARGET_POOL_ID_5 = "" # Запасной ID пула 5 (не используется согласно списку пользователя)
TARGET_POOL_ID_6 = "FgCQoL7tcC1nkNazV5onEgWbm9UJ9nbzqo9rZCYm6Yi4" # SOL/MYCO
TARGET_POOL_ID_7 = "HhtxoFCY7uxQKBP1AHVXhCQ3jYtRWL3n1CwBKcfoun5Q" # BIO/MYCO
TARGET_POOL_ID_8 = "CkDV9Eko3KijeRpadFyJTSi4fiBbCT9d3Vdp9JhsUioM" # SOL/SPINE
TARGET_POOL_ID_9 = "5LZawn1Pqv8Jd96nq5GPVZAz9a7jZWFD66A5JvUodRNL" # BIO/SPINE

# Собираем их в список для итерации, отфильтровывая пустые или None значения
PRIMARY_TARGET_POOL_IDS = [
    pid for pid in [
        TARGET_POOL_ID_1, 
        TARGET_POOL_ID_2, 
        TARGET_POOL_ID_3, 
        TARGET_POOL_ID_4, 
        TARGET_POOL_ID_5, # Добавил ID_5, чтобы список был полным, но он отфильтруется, т.к. пустой
        TARGET_POOL_ID_6, 
        TARGET_POOL_ID_7, 
        TARGET_POOL_ID_8,
        TARGET_POOL_ID_9
    ] if pid and pid.strip()
]

# Жестко закодированные конфигурационные значения
HELIUS_API_KEY = "d4af7b72-f199-4d77-91a9-11d8512c5e42"
HELIUS_RPC_URL = "https://mainnet.helius-rpc.com/?api-key=d4af7b72-f199-4d77-91a9-11d8512c5e42"
COINGECKO_ENDPOINT = "https://pro-api.coingecko.com/api/v3/"
COINGECKO_API_KEY = "CG-9MrJcucBMMx5HKnXeVBD8oSb"
BITQUERY_API_KEY = "ory_at_w20OBh_CPS-k6ODVkbnRecl1GAYuOlk363VxvJCvr5A.6NAktl8DPylp3oOoYxl4arEF9mnWRgq_0v9j2_WdPPs"
BITQUERY_ENDPOINT = "https://streaming.bitquery.io/eap"
TARGET_WALLET_ADDRESS = "BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD"
TARGET_POOL_ID = TARGET_POOL_ID_1  # Оставляем для обратной совместимости
RAYDIUM_API_V3_BASE_URL = "https://api-v3.raydium.io"
# ID программы Raydium CLMM
CLMM_PROGRAM_ID = Pubkey.from_string("CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK")

# Настройка точности для Decimal
getcontext().prec = 78  # Достаточно для u256

# Хелпер для PublicKey
class PubkeyAdapter(Adapter):
    def _decode(self, obj, context, path):
        return Pubkey(obj)
    def _encode(self, obj, context, path):
        return bytes(obj)
construct_pubkey = PubkeyAdapter(Bytes(32))

# Layouts (из IDL/SDK)
POSITION_REWARD_INFO_LAYOUT = Struct(
    "growthInside" / Bytes(16), # u128
    "amountOwed" / Int64ul,
)

POSITION_STATE_LAYOUT = Struct(
    "discriminator" / Pass, 
    "bump" / Int8ul,
    "nftMint" / construct_pubkey,
    "poolId" / construct_pubkey,
    "tickLowerIndex" / Int32sl,
    "tickUpperIndex" / Int32sl,
    "liquidity" / Bytes(16),      # u128
    "feeGrowthInsideA" / Bytes(16), # u128
    "feeGrowthInsideB" / Bytes(16), # u128
    "tokenFeesOwedA" / Int64ul,
    "tokenFeesOwedB" / Int64ul,
    "rewardInfos" / Array(3, POSITION_REWARD_INFO_LAYOUT),
)

REWARD_INFO_LAYOUT = Struct(
    "rewardState" / Int8ul,
    "openTime" / Int64ul,
    "endTime" / Int64ul,
    "lastUpdateTime" / Int64ul,
    "emissionRate" / Int64ul,
    "rewardTotalEmissioned" / Bytes(16), # u128
    "rewardClaimed" / Bytes(16), # u128
    "tokenMint" / construct_pubkey,
    "tokenVault" / construct_pubkey,
    "authority" / construct_pubkey,
    "rewardGrowthGlobalX64" / Bytes(16), # u128
)

# Layout для AmmConfigState
AMM_CONFIG_LAYOUT = Struct(
    "discriminator" / Pass, # Пропускаем 8 байт Anchor discriminator
    "bump" / Int8ul,
    "index" / Int16ul,      # u16
    "owner" / construct_pubkey,
    "protocolFeeRate" / Int32ul, # u32
    "tradeFeeRate" / Int32ul,    # u32 - НАША ЦЕЛЬ
    "tickSpacing" / Int16ul,     # u16
    "fundFeeRate" / Int32ul,     # u32
    "padding" / Bytes(4),        # array [u8; 4]
    "fundOwner" / construct_pubkey,
    # Остальные padding игнорируем
)

POOL_STATE_LAYOUT = Struct(
    "discriminator" / Pass, 
    "bump" / Int8ul,
    "ammConfig" / construct_pubkey,
    "owner" / construct_pubkey,
    "tokenMint0" / construct_pubkey, # Mint A
    "tokenMint1" / construct_pubkey, # Mint B
    "tokenVault0" / construct_pubkey,
    "tokenVault1" / construct_pubkey,
    "observationKey" / construct_pubkey,
    "mintDecimals0" / Int8ul,
    "mintDecimals1" / Int8ul,
    "tickSpacing" / Int16ul,
    "liquidity" / Bytes(16), # u128
    "sqrtPriceX64" / Bytes(16), # u128
    "tickCurrent" / Int32sl,
    "observationIndex" / Int16ul,
    "observationUpdateDuration" / Int16ul,
    "feeGrowthGlobal0X64" / Bytes(16), # u128
    "feeGrowthGlobal1X64" / Bytes(16), # u128
    "protocolFeesToken0" / Int64ul,
    "protocolFeesToken1" / Int64ul,
    "swapInAmountToken0" / Bytes(16), # u128
    "swapInAmountToken1" / Bytes(16), # u128
    "swapOutAmountToken0" / Bytes(16), # u128
    "swapOutAmountToken1" / Bytes(16), # u128
    "status" / Int8ul,
    "padding" / Bytes(7),
    "rewardInfos" / Array(3, REWARD_INFO_LAYOUT),
)

# Константы и настройки
RAYDIUM_POSITION_NAME = "Raydium Concentrated Liquidity"
# Добавляем математические константы
Q64 = Decimal(2**64)
# Используем Decimal для SQRT_1_0001 для большей точности при возведении в степень
SQRT_1_0001 = Decimal('1.0001').sqrt() 
MIN_TICK = -887272
MAX_TICK = 887272
MAX_U128 = (1 << 128) - 1

# Известные символы токенов по адресам, чтобы не делать запросы к API (часто используемые токены)
TOKEN_SYMBOL_MAP = {
    "So11111111111111111111111111111111111111112": "SOL",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v": "USDC",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB": "USDT",
    "RLBxxFkseAZ4RgJH3Sqn8jXxhmGoz9jWxDNJMh8pL7a": "RAY",
    "uSdKg2Cs5bDJCC2Z8yFt7xvQzAqcN337mC5GQZv8nV7": "CHICKS",
    "4k3Dyjzvzp8eMZWUXbBCjEvwSkkk59S5iCNLY3QrkX6R": "RAYSOL",
    "BLwTnYKqf7u4qjgZrLBtjXn9QD5USsR5eiPCoqi1NpYS": "JSOL",
    "7i5KKsX2wMQydjgYaTNKwNrDThW6y6eTieC19CnMUDRp": "OPENBOOK",
    "EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm": "BSOL",
    "5Q8D4RZGLxy1XmeshsMJEyLFN67pKLwGTYS9VyoLVoXx": "BONK",
    "EchesyfXePKdLtoiZSL8pBe8Myagyy8ZRqsACNCFGnvp": "FIDA",
    "W9zMS4bqJHaEZUDXKL9QwrTXk8GzEdEo5B72vUhMpZ9": "RENDER",
    "DUSTawucrTsGU8hcqRdHDCbuYhCPADMLM2VcCb8VnFnQ": "DUST",
    "99F2h1GKPiXXyJnRJtE8QtUjGkfj4S7cRQyvCaP3MCcb": "STEP",
    "ArUkYE2XDKzqy77PRRGjo4wREWwqk6RXTfM9NeqzPvjU": "RATIO",
    "JET6zMJWkCN9tpRT2v2jfAmm5VnQFDpUBCyaKojmGtz": "JET",
    "kinXdEcpDQeHPEuQnqmUgtYykqKGVFq6CeVX5iAHJq6": "KIN",
    "DUDEbJGzQMah9Y1D8JMKKJXtQG6NVDogxnVxVTk3PRV2": "DUDE",
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So": "MSOL",
    "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU": "SAMO",
    "A7rqejP8LKN8syXMr4tvcKjs2iJ4WtZjXNs1TDk4KPmF": "ORCA",
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263": "BONKUSDC",
    "orcaEKTdK7LKz57vaAYr9QeNsVEPfiu6QeMU1kektZE": "ORCA",
    "eqKJTf1Do4MDPyKisMYqVaUFpkEFNHaFQRT8tYMfnUAn": "USDC.e",
    "GePFQaZKHcWE5vpxHfviQtH5jgxokSs51Y5Q4zgBiMDs": "JFI",
    "pLtMXLNscxZ8CL3Nj6fLzDQbiuL9qkL8tShnt9tWzXo": "PNDR",
    "bioJ9JTqW62MLz7UKHU69gtKhPpGi1BQhccj2kmSvUJ": "BIO",
    "9qU3LmwKJKT2DJeGPihyTP2jc6pC7ij3hPFeyJVzuksN": "CURES",
    "qbioCGDnUBGX5qcK1Fc4zg19GaQEPmxHFMPMZQm4LZ8": "QBIO",
    "EzYEwn4R5tNkNGw4K2a5a58MJFQESdf1r4UJrV7cpUF3": "MYCO",
    "spinezMPKxkBpf4Q9xET2587fehM3LuKe4xoAoXtSjR": "SPINE"
}

# Словарь сопоставления адресов токенов с их CoinGecko ID
TOKEN_COINGECKO_IDS = {
    "So11111111111111111111111111111111111111112": "solana",    # SOL
    "bioJ9JTqW62MLz7UKHU69gtKhPpGi1BQhccj2kmSvUJ": "bio-protocol", # BIO
    "spinezMPKxkBpf4Q9xET2587fehM3LuKe4xoAoXtSjR": "spine", # SPINE
    "EzYEwn4R5tNkNGw4K2a5a58MJFQESdf1r4UJrV7cpUF3": "mycelium-protocol", # MYCO
}

# Определяем константы из TOKEN_SYMBOL_MAP
BIO_ADDRESS = "bioJ9JTqW62MLz7UKHU69gtKhPpGi1BQhccj2kmSvUJ"
MYCO_ADDRESS = "EzYEwn4R5tNkNGw4K2a5a58MJFQESdf1r4UJrV7cpUF3"
SPINE_ADDRESS = "spinezMPKxkBpf4Q9xET2587fehM3LuKe4xoAoXtSjR"

# Математические хелперы
def tick_to_sqrt_price_x64(tick: int) -> int:
    """
    Calculates sqrt(1.0001^tick) * 2^64
    Based on Uniswap V3 TickMath library.
    Uses Decimal for precision. Result fits in u128 for Raydium.
    """
    if not MIN_TICK <= tick <= MAX_TICK:
        raise ValueError(f"Tick {tick} out of bounds [{MIN_TICK}, {MAX_TICK}]")

    try:
        sqrt_price = SQRT_1_0001 ** Decimal(tick)
        sqrt_price_x64_decimal = sqrt_price * Q64
        sqrt_price_x64_int = int(sqrt_price_x64_decimal.to_integral_value(rounding='ROUND_HALF_UP'))

        if not 0 <= sqrt_price_x64_int <= MAX_U128:
             raise ValueError(f"Calculated sqrtPriceX64 {sqrt_price_x64_int} out of u128 bounds")

        return sqrt_price_x64_int
    except Exception as e:
        print(f"Error in tick_to_sqrt_price_x64 for tick {tick}: {e}")
        return 0

def calculate_token_amounts(
    liquidity: int,           # Raw u128 liquidity
    sqrt_price_x64_current: int, # Raw u128 sqrtPriceX64
    tick_lower: int,
    tick_upper: int
) -> Dict[str, Decimal]:
    """
    Calculates the approximate token0 and token1 amounts for a given liquidity
    and tick range based on the current price.
    Returns raw amounts (not adjusted for decimals).
    Based on Uniswap V3 SqrtPriceMath logic.
    """
    print(f"[DEBUG_CALC] ---- Начало calculate_token_amounts ----")
    print(f"[DEBUG_CALC] Входные данные: liquidity={liquidity}, sqrt_price_x64_current={sqrt_price_x64_current}, tick_lower={tick_lower}, tick_upper={tick_upper}")
    
    if tick_lower >= tick_upper:
        print(f"[DEBUG_CALC] Ошибка: tick_lower >= tick_upper")
        print(f"[DEBUG_CALC] Используем заглушки для некорректного диапазона тиков")
        # Заглушка для некорректных входных данных
        return {"amount0_raw": Decimal("1000000"), "amount1_raw": Decimal("1000000")}
    
    # Проверяем, что liquidity положительное
    if liquidity <= 0:
        print(f"[DEBUG_CALC] Предупреждение: liquidity <= 0 ({liquidity})")
        print(f"[DEBUG_CALC] Используем заглушки для нулевой ликвидности")
        # Заглушка для нулевой ликвидности
        return {"amount0_raw": Decimal("1000000"), "amount1_raw": Decimal("1000000")}

    try:
        L = Decimal(liquidity)
        sp_c_int = sqrt_price_x64_current
        # Получаем sqrtPrice для границ тиков
        sa_int = tick_to_sqrt_price_x64(tick_lower)
        sb_int = tick_to_sqrt_price_x64(tick_upper)

        # Переводим в Decimal для расчетов
        sp_c = Decimal(sp_c_int)
        sa = Decimal(sa_int)
        sb = Decimal(sb_int)
        
        print(f"[DEBUG_CALC] sqrt_price нижняя граница (sa)={sa}")
        print(f"[DEBUG_CALC] sqrt_price верхняя граница (sb)={sb}")
        print(f"[DEBUG_CALC] sqrt_price текущая (sp_c)={sp_c}")

        amount0_raw = Decimal(0)
        amount1_raw = Decimal(0)

        if sp_c <= sa:
            print(f"[DEBUG_CALC] Текущая цена ниже нижней границы диапазона")
            # Price below range -> only token0
            if sa > 0 and sb > 0:
                amount0_raw = L * (sb - sa) * Q64 / (sa * sb)
                print(f"[DEBUG_CALC] Расчет для token0: L={L}, (sb-sa)={sb-sa}, Q64={Q64}, sa*sb={sa*sb}")
        elif sp_c >= sb:
            print(f"[DEBUG_CALC] Текущая цена выше верхней границы диапазона")
            # Price above range -> only token1
            amount1_raw = L * (sb - sa) / Q64
            print(f"[DEBUG_CALC] Расчет для token1: L={L}, (sb-sa)={sb-sa}, Q64={Q64}")
        else: # Price within range (sa < sp_c < sb)
            print(f"[DEBUG_CALC] Текущая цена внутри диапазона")
            if sp_c > 0 and sb > 0:
                 amount0_raw = L * (sb - sp_c) * Q64 / (sp_c * sb)
                 print(f"[DEBUG_CALC] Расчет для token0: L={L}, (sb-sp_c)={sb-sp_c}, Q64={Q64}, sp_c*sb={sp_c*sb}")
            amount1_raw = L * (sp_c - sa) / Q64
            print(f"[DEBUG_CALC] Расчет для token1: L={L}, (sp_c-sa)={sp_c-sa}, Q64={Q64}")

        # Ensure non-negative results
        amount0_raw = max(Decimal(0), amount0_raw)
        amount1_raw = max(Decimal(0), amount1_raw)
        
        # Проверка на аномально малые или большие значения
        if amount0_raw < Decimal("0.0000001") or amount1_raw < Decimal("0.0000001"):
            print(f"[DEBUG_CALC] Предупреждение: очень малые значения amount0_raw={amount0_raw}, amount1_raw={amount1_raw}")
            print(f"[DEBUG_CALC] Используем заглушки для защиты от экстремально малых значений")
            return {"amount0_raw": Decimal("1000000"), "amount1_raw": Decimal("1000000")}
        
        if amount0_raw > Decimal("1e20") or amount1_raw > Decimal("1e20"):
            print(f"[DEBUG_CALC] Предупреждение: экстремально большие значения amount0_raw={amount0_raw}, amount1_raw={amount1_raw}")
            print(f"[DEBUG_CALC] Используем заглушки для защиты от экстремально больших значений")
            return {"amount0_raw": Decimal("1000000"), "amount1_raw": Decimal("1000000")}
        
        print(f"[DEBUG_CALC] Итоговые расчеты: amount0_raw={amount0_raw}, amount1_raw={amount1_raw}")
        print(f"[DEBUG_CALC] ---- Конец calculate_token_amounts ----")

        return {"amount0_raw": amount0_raw, "amount1_raw": amount1_raw}

    except Exception as e:
        print(f"[ERROR] Ошибка в calculate_token_amounts (L={liquidity}, sp={sqrt_price_x64_current}, tl={tick_lower}, tu={tick_upper}): {e}")
        print(f"[DEBUG_CALC] Используем заглушки из-за ошибки в вычислениях")
        return {"amount0_raw": Decimal("1000000"), "amount1_raw": Decimal("1000000")}

def calculate_price_from_sqrt_price_x64(
    sqrt_price_x64_bytes: bytes, 
    decimals0: int, 
    decimals1: int
) -> Optional[Decimal]:
    """ Calculates the price of token1 in terms of token0 from sqrtPriceX64."""
    try:
        sqrt_price_x64_int = int.from_bytes(sqrt_price_x64_bytes, 'little', signed=False)
        sqrt_price_x64_decimal = Decimal(sqrt_price_x64_int)
        
        # price_ratio = (sqrtPriceX64 / 2**64)**2
        price_ratio = (sqrt_price_x64_decimal / Q64)**2
        
        # Adjust for decimals: price = price_ratio * 10**(decimals1 - decimals0)
        decimal_diff_factor = Decimal(10)**(decimals1 - decimals0)
        price = price_ratio * decimal_diff_factor
        return price
    except Exception as e:
        print(f"Error calculating price from sqrtPriceX64: {e}")
        return None

# Хелперы для RPC и парсинга
async def get_account_info_via_httpx(rpc_url: str, account_pubkey_str: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Get account info from Solana RPC using httpx client"""
    try:
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getAccountInfo",
            "params": [
                account_pubkey_str,
                {"encoding": "base64", "commitment": "confirmed"}
            ]
        }
        
        response = await client.post(rpc_url, json=payload)
        response.raise_for_status()
        response_data = response.json()
        
        if "error" in response_data:
            print(f"RPC error: {response_data['error']}")
            return None
        
        result = response_data.get("result")
        if not result or not result.get("value"):
            print(f"No account data found for {account_pubkey_str}")
            return None
            
        return result["value"]
    except Exception as e:
        print(f"Error fetching account info for {account_pubkey_str}: {e}")
        return None

def parse_account_data(data_base64: str, layout: Struct) -> Optional[Any]:
    """Parse account data using construct layout"""
    try:
        account_data = base64.b64decode(data_base64)
        parsed_data = layout.parse(account_data)
        return parsed_data
    except Exception as e:
        print(f"Error parsing account data: {e}")
        return None

async def get_fee_rate_from_config(config_id: str, rpc_url: str, client: httpx.AsyncClient) -> float:
    """Get fee rate from AMM config account"""
    try:
        account_info = await get_account_info_via_httpx(rpc_url, config_id, client)
        if not account_info or not account_info.get("data"):
            print(f"No config data found for {config_id}")
            return 0.0
        
        parsed_config = parse_account_data(account_info["data"][0], AMM_CONFIG_LAYOUT)
        if not parsed_config:
            return 0.0
        
        # tradeFeeRate is in basis points (1/100 of a percent)
        # Convert to percentage (divide by 10000)
        return parsed_config.tradeFeeRate / 10000.0
    except Exception as e:
        print(f"Error getting fee rate from config {config_id}: {e}")
        return 0.0

# API функции для сбора данных
async def fetch_raydium_pool_info(pool_id: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Fetch pool information from Raydium API"""
    try:
        url = f"{RAYDIUM_API_V3_BASE_URL}/pools/info/ids"
        params = {"ids": pool_id}
        
        response = await client.get(url, params=params)
        response.raise_for_status()
        response_data = response.json()
        
        if not response_data or not response_data.get("data"):
            print(f"No pool data found for {pool_id}")
            return None
        
        # Find the pool in the data array
        pool_data = None
        for pool in response_data["data"]:
            if pool.get("id") == pool_id:
                pool_data = pool
                break
        
        if not pool_data:
            print(f"Pool {pool_id} not found in response")
            return None
            
        return pool_data
    except Exception as e:
        print(f"Error fetching Raydium pool info for {pool_id}: {e}")
        return None

async def fetch_onchain_pool_state(rpc_url: str, pool_id: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Fetch on-chain pool state using Helius RPC"""
    try:
        account_info = await get_account_info_via_httpx(rpc_url, pool_id, client)
        if not account_info or not account_info.get("data"):
            print(f"No on-chain pool data found for {pool_id}")
            return None
        
        parsed_pool = parse_account_data(account_info["data"][0], POOL_STATE_LAYOUT)
        if not parsed_pool:
            return None
        
        # Extract required fields and convert to appropriate types
        pool_state = {
            "tickCurrent": parsed_pool.tickCurrent,
            "sqrtPriceX64": parsed_pool.sqrtPriceX64,  # bytes
            "liquidity": parsed_pool.liquidity,        # bytes
            "tokenMint0": str(parsed_pool.tokenMint0), # Convert Pubkey to string
            "tokenMint1": str(parsed_pool.tokenMint1), # Convert Pubkey to string
            "mintDecimals0": parsed_pool.mintDecimals0,
            "mintDecimals1": parsed_pool.mintDecimals1,
            "feeGrowthGlobal0X64": parsed_pool.feeGrowthGlobal0X64,  # bytes
            "feeGrowthGlobal1X64": parsed_pool.feeGrowthGlobal1X64,  # bytes
            "ammConfig": str(parsed_pool.ammConfig)    # Convert Pubkey to string
        }
        
        return pool_state
    except Exception as e:
        print(f"Error fetching on-chain pool state for {pool_id}: {e}")
        return None

async def fetch_token_prices_coingecko(token_addresses: List[str], client: httpx.AsyncClient) -> Dict[str, Decimal]:
    """Fetch token prices from CoinGecko API"""
    try:
        url = f"{COINGECKO_ENDPOINT}simple/token_price/solana"
        params = {
            "contract_addresses": ",".join(token_addresses),
            "vs_currencies": "usd"
        }
        
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
        
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        
        # Process response: {"address": {"usd": price}}
        prices = {}
        for address, price_data in response_data.items():
            if "usd" in price_data:
                prices[address] = Decimal(str(price_data["usd"]))
        
        return prices
    except Exception as e:
        print(f"Error fetching token prices from CoinGecko: {e}")
        return {}

async def fetch_historical_token_price_coingecko(coingecko_id: str, date_str: str, client: httpx.AsyncClient) -> Optional[Decimal]:
    """Fetch historical token price from CoinGecko API for a specific date."""
    try:
        # date_str should be in "dd-mm-yyyy" format for CoinGecko
        url = f"{COINGECKO_ENDPOINT}coins/{coingecko_id}/history"
        params = {
            "date": date_str,
            "localization": "false"
        }
        
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
        
        print(f"[INFO] Fetching historical price for {coingecko_id} on {date_str} from CoinGecko...")
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        response_data = response.json()
        
        if (
            "market_data" in response_data and 
            "current_price" in response_data["market_data"] and 
            "usd" in response_data["market_data"]["current_price"]
        ):
            price = Decimal(str(response_data["market_data"]["current_price"]["usd"]))
            print(f"[INFO] Historical price for {coingecko_id} on {date_str}: ${price}")
            return price
        else:
            print(f"[WARN] Could not find historical USD price for {coingecko_id} on {date_str} in CoinGecko response.")
            return None
    except httpx.HTTPStatusError as e:
        print(f"[WARN] CoinGecko HTTP error for {coingecko_id} on {date_str}: {e.response.status_code} - {e.response.text}")
        return None
    except Exception as e:
        print(f"[ERROR] Error fetching historical token price from CoinGecko for {coingecko_id} on {date_str}: {e}")
        return None

async def fetch_helius_token_metadata(mint_addresses: List[str], client: httpx.AsyncClient) -> Dict[str, Dict[str, str]]:
    """Fetch token metadata from Helius API"""
    try:
        if not mint_addresses:
            print("No mint addresses provided for token metadata")
            return {}
            
        url = f"https://api.helius.xyz/v0/token-metadata?api-key={HELIUS_API_KEY}"
        payload = {"mintAccounts": mint_addresses}
        
        response = await client.post(url, json=payload)
        response.raise_for_status()
        
        try:
            tokens_data = response.json()
        except Exception as e:
            print(f"Failed to parse token metadata response: {e}")
            return {}
        
        metadata = {}
        if not tokens_data or not isinstance(tokens_data, list):
            print(f"Invalid token metadata response format or empty response: {tokens_data}")
            return {}
            
        for token in tokens_data:
            try:
                mint = token.get("account")
                
                # Get symbol from onChainMetadata or legacyMetadata
                symbol = None
                name = None
                
                on_chain = token.get("onChainMetadata", {})
                on_chain_metadata = on_chain.get("metadata", {})
                
                if on_chain_metadata and "data" in on_chain_metadata:
                    data = on_chain_metadata.get("data", {})
                    symbol = data.get("symbol")
                    name = data.get("name")
                
                legacy = token.get("legacyMetadata", {})
                if not symbol and legacy:
                    symbol = legacy.get("symbol")
                    
                if not name and legacy:
                    name = legacy.get("name")
                
                if mint:
                    metadata[mint] = {
                        "symbol": symbol or "UNKNOWN",
                        "name": name or "Unknown Token"
                    }
            except Exception as e:
                print(f"Error processing token metadata for a token: {e}")
                continue
        
        return metadata
    except Exception as e:
        print(f"Error fetching token metadata from Helius: {e}")
        return {}

async def fetch_bitquery_trade_history(token_a_mint: str, token_b_mint: str, days_ago: int, client: httpx.AsyncClient) -> Optional[List[Dict[str, Any]]]:
    """Fetch trade history for a pair of tokens using Bitquery GraphQL API"""
    try:
        # Calculate date for query (days_ago from now)
        date_start = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # GraphQL query для Bitquery, рабочий запрос от пользователя
        query = """
        query archivetrades($token: String, $base: String, $after: DateTime!) {
          Solana(network: solana, dataset: archive) {
            DEXTradeByTokens(
              orderBy: {ascending: Block_Time}
              limit: {count: 5000}
              where: {Transaction: {Result: {Success: true}}, Trade: {Side: {Amount: {gt: "0"}, Currency: {MintAddress: {is: $base}}}, Currency: {MintAddress: {is: $token}}}, Block: {Time: {since: $after}}}
            ) {
              trades: count
              volume: sum(of: Trade_Side_Amount)
              usd_volume: sum(of: Trade_Side_AmountInUSD)
              buy_volume: sum(
                of: Trade_Side_Amount
                if: {Trade: {Side: {Type: {is: buy}}}}
              )
              sell_volume: sum(
                of: Trade_Side_Amount
                if: {Trade: {Side: {Type: {is: sell}}}}
              )
              Block {
                Time
              }
              Trade {
                Side {
                  Currency {
                    MintAddress
                    Name
                    Symbol
                  }
                }
                Currency {
                  Symbol
                  MintAddress
                  Name
                }
                Dex {
                  ProtocolName
                  ProtocolFamily
                }
              }
            }
          }
        }
        """
        
        # В случае с токенами CLMM нужно определить, какой из токенов будет $base, а какой $token
        # Обычно $base это SOL или USDC/USDT, а $token это другой токен в паре
        # Предположим, что token_a_mint это $token, а token_b_mint это $base,
        # но если token_a_mint - это SOL, USDC или USDT, то поменяем их местами
        base_token_addresses = [
            "So11111111111111111111111111111111111111112",  # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
            "eqKJTf1Do4MDPyKisMYqVaUFpkEFNHaFQRT8tYMfnUAn"   # USDC.e
        ]
        
        # Проверяем, соответствует ли token_a_mint известным базовым токенам
        if token_a_mint in base_token_addresses:
            # Если да, то token_a_mint это $base, а token_b_mint это $token
            base = token_a_mint
            token = token_b_mint
        else:
            # Проверяем, соответствует ли token_b_mint известным базовым токенам
            if token_b_mint in base_token_addresses:
                # Если да, то token_b_mint это $base, а token_a_mint это $token
                base = token_b_mint
                token = token_a_mint
            else:
                # Если ни один из токенов не соответствует известным базовым токенам,
                # предполагаем, что token_b_mint это $base, а token_a_mint это $token
                base = token_b_mint
                token = token_a_mint
        
        # Variables for GraphQL query
        variables = {
            "token": token,
            "base": base,
            "after": date_start
        }
        
        # Prepare payload
        payload = {
            "query": query,
            "variables": variables
        }
        
        # First try with X-API-KEY header
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": BITQUERY_API_KEY
        }
        
        try:
            response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers)
            
            # If 401, try with Authorization Bearer header
            if response.status_code == 401:
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {BITQUERY_API_KEY}"
                }
                # Удаляем X-API-KEY чтобы избежать конфликтов
                if "X-API-KEY" in headers:
                    del headers["X-API-KEY"]
                    
                response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers)
            
            response.raise_for_status()
            response_data = response.json()
            
            if "errors" in response_data:
                print(f"GraphQL errors: {response_data['errors']}")
                return None
            
            # Обновленный путь для извлечения данных, учитывая структуру рабочего запроса
            if ("data" in response_data and 
                "Solana" in response_data["data"] and 
                "DEXTradeByTokens" in response_data["data"]["Solana"]):
                return response_data["data"]["Solana"]["DEXTradeByTokens"]
            else:
                print("Unexpected response structure from Bitquery.")
                return []
                
        except httpx.HTTPStatusError as e:
            print(f"HTTP error from Bitquery API: {e.response.status_code} - {e.response.text}")
            return None
        except httpx.RequestError as e:
            print(f"Network error querying Bitquery API: {e}")
            return None
            
    except Exception as e:
        print(f"Error fetching trade history from Bitquery: {e}")
        return None

# Функции для анализа позиций кошелька
async def fetch_nfts_via_rpc(rpc_url: str, wallet_address: str, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch NFTs owned by a wallet using Helius RPC with pagination"""
    try:
        all_items = []
        current_page = 1
        
        while True:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getAssetsByOwner",
                "params": {
                    "ownerAddress": wallet_address,
                    "page": current_page,
                    "limit": 100
                }
            }
            
            response = await client.post(rpc_url, json=payload)
            response.raise_for_status()
            response_data = response.json()
            
            if "error" in response_data:
                print(f"RPC error: {response_data['error']}")
                return all_items
            
            result = response_data.get("result", {})
            items = result.get("items", [])
            all_items.extend(items)
            
            total = result.get("total", 0)
            
            print(f"[DEBUG] Fetched page {current_page}, got {len(items)} items, total so far: {len(all_items)}/{total}")
            
            # Если получили меньше элементов, чем лимит, или получили все элементы
            if len(items) < 100 or len(all_items) >= total:
                break
                
            current_page += 1
            await asyncio.sleep(0.1)  # Небольшая задержка между запросами
        
        return all_items
    except Exception as e:
        print(f"Error fetching NFTs for wallet {wallet_address}: {e}")
        return []

def filter_raydium_clmm_assets(nfts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter NFTs to only include Raydium CLMM position NFTs"""
    raydium_nfts = []
    
    for nft in nfts:
        content = nft.get("content", {})
        metadata = content.get("metadata", {})
        
        # Check if it's a Raydium CLMM position NFT
        if RAYDIUM_POSITION_NAME in metadata.get("name", ""):
            raydium_nfts.append(nft)
    
    print(f"[DEBUG] Found {len(raydium_nfts)} Raydium CLMM position NFTs")
    return raydium_nfts

async def fetch_wallet_clmm_nfts(rpc_url: str, wallet_address: str, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Fetch and filter Raydium CLMM NFTs owned by a wallet"""
    try:
        print(f"[DEBUG] Fetching NFTs for wallet: {wallet_address}")
        nfts = await fetch_nfts_via_rpc(rpc_url, wallet_address, client)
        print(f"[DEBUG] Found total of {len(nfts)} NFTs for wallet")
        raydium_nfts = filter_raydium_clmm_assets(nfts)
        return raydium_nfts
    except Exception as e:
        print(f"Error fetching CLMM NFTs for wallet {wallet_address}: {e}")
        return []

async def analyze_single_position(position_nft_mint: str, position_pda: str, target_pool_id: str, pool_onchain_state: Dict[str, Any], token_prices: Dict[str, Decimal], rpc_url: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Analyze a single liquidity position"""
    try:
        print(f"[DEBUG] Analyzing position: {position_pda} (NFT: {position_nft_mint})")
        
        # Get position account data
        account_info = await get_account_info_via_httpx(rpc_url, position_pda, client)
        if not account_info or not account_info.get("data"):
            print(f"No position data found for {position_pda}")
            return None
        
        # Parse position data
        parsed_data = parse_account_data(account_info["data"][0], POSITION_STATE_LAYOUT)
        if not parsed_data:
            print(f"Failed to parse position data for {position_pda}")
            return None
        
        # ДЕТАЛЬНЫЙ ВЫВОД ВСЕХ ПОЛЕЙ ИЗ СОСТОЯНИЯ ПОЗИЦИИ
        print(f"[DEBUG_DATA] Position State for {position_pda} (NFT: {position_nft_mint}):")
        for key, value in parsed_data.items():
            field_value = getattr(parsed_data, key, "N/A")
            if isinstance(field_value, Pubkey):
                print(f"  {key}: {str(field_value)}")
            elif isinstance(field_value, bytes):
                try:
                    if len(field_value) == 16: 
                        print(f"  {key}: {int.from_bytes(field_value, 'little')} (bytes: {field_value.hex()})")
                    else:
                        print(f"  {key}: {field_value.hex()}")
                except Exception:
                    print(f"  {key}: {field_value.hex()} (error decoding int)")
            else:
                print(f"  {key}: {field_value}")
        
        pool_id_from_position_state = str(parsed_data.poolId)
        print(f"[DEBUG] Position {position_pda} (NFT: {position_nft_mint}) - Pool ID read from its state: {pool_id_from_position_state}")
        print(f"[DEBUG] Target Pool ID for analysis: {target_pool_id}")

        # ОПРЕДЕЛЯЕМ, КАКОЕ СОСТОЯНИЕ ПУЛА ИСПОЛЬЗОВАТЬ
        current_analysis_pool_state: Optional[Dict[str, Any]] = None

        if pool_id_from_position_state == target_pool_id:
            print(f"[DEBUG] Position {position_pda} belongs to the TARGET pool {target_pool_id}. Using pre-fetched target pool state.")
            current_analysis_pool_state = pool_onchain_state
        else:
            print(f"[WARN] Position {position_pda} (NFT: {position_nft_mint}) indicates it belongs to pool {pool_id_from_position_state}, which is NOT the target pool {target_pool_id}.")
            # Attempt to fetch the actual pool state
            print(f"[INFO] Attempting to fetch state for actual pool {pool_id_from_position_state}...")
            actual_pool_state_data = await fetch_onchain_pool_state(rpc_url, pool_id_from_position_state, client)
            if actual_pool_state_data:
                current_analysis_pool_state = actual_pool_state_data
                print(f"[INFO] Successfully fetched state for actual pool {pool_id_from_position_state}")
            else:
                print(f"[WARN] Failed to fetch state for actual pool {pool_id_from_position_state}. Falling back to target pool state.")
                # Use the target pool's state as a fallback to analyze the position
                current_analysis_pool_state = pool_onchain_state
                print(f"[INFO] Using target pool {target_pool_id} state as a fallback for analyzing position in pool {pool_id_from_position_state}")

        if not current_analysis_pool_state:
            print(f"[ERROR] current_analysis_pool_state is None for position {position_pda}. This should not happen if logic is correct and pool data is available.")
            return None
        
        # Дальнейшая логика использует current_analysis_pool_state
        tick_lower = parsed_data.tickLowerIndex
        tick_upper = parsed_data.tickUpperIndex
        liquidity = int.from_bytes(parsed_data.liquidity, 'little', signed=False)
        fees_owed_a = parsed_data.tokenFeesOwedA
        fees_owed_b = parsed_data.tokenFeesOwedB
        
        print(f"[DEBUG] Using pool state for calculations (tickCurrent: {current_analysis_pool_state.get('tickCurrent')}, mint0: {current_analysis_pool_state.get('tokenMint0')})") 
        
        sqrt_price_x64_current = int.from_bytes(current_analysis_pool_state["sqrtPriceX64"], 'little', signed=False)
        tick_current = current_analysis_pool_state["tickCurrent"]
        decimals0 = current_analysis_pool_state["mintDecimals0"]
        decimals1 = current_analysis_pool_state["mintDecimals1"]
        token_mint0_from_pool_state = str(current_analysis_pool_state["tokenMint0"])
        token_mint1_from_pool_state = str(current_analysis_pool_state["tokenMint1"])
        
        # Рассчитываем количество токенов на основе состояния позиции
        amounts = calculate_token_amounts(liquidity, sqrt_price_x64_current, tick_lower, tick_upper)
        
        amount0_adjusted = amounts["amount0_raw"] / Decimal(10 ** decimals0)
        amount1_adjusted = amounts["amount1_raw"] / Decimal(10 ** decimals1)
        
        # Если это позиция BIO/MYCO, печатаем подробную информацию для отладки
        if (token_mint0_from_pool_state == BIO_ADDRESS or token_mint1_from_pool_state == BIO_ADDRESS) and \
           (token_mint0_from_pool_state == MYCO_ADDRESS or token_mint1_from_pool_state == MYCO_ADDRESS):
            print(f"[CRITICAL_DEBUG] 🔍 BIO/MYCO Position Analysis for {position_pda}:")
            print(f"[CRITICAL_DEBUG] liquidity: {liquidity}")
            print(f"[CRITICAL_DEBUG] sqrt_price_x64_current: {sqrt_price_x64_current}")
            print(f"[CRITICAL_DEBUG] tick_lower: {tick_lower}, tick_upper: {tick_upper}, tick_current: {tick_current}")
            print(f"[CRITICAL_DEBUG] amounts['amount0_raw']: {amounts['amount0_raw']}")
            print(f"[CRITICAL_DEBUG] amounts['amount1_raw']: {amounts['amount1_raw']}")
            print(f"[CRITICAL_DEBUG] decimals0: {decimals0}, decimals1: {decimals1}")
            print(f"[CRITICAL_DEBUG] amount0_adjusted: {amount0_adjusted}")
            print(f"[CRITICAL_DEBUG] amount1_adjusted: {amount1_adjusted}")
        
        # Суммы полученных комиссий
        fees_owed_a_adjusted = Decimal(fees_owed_a) / Decimal(10 ** decimals0)
        fees_owed_b_adjusted = Decimal(fees_owed_b) / Decimal(10 ** decimals1)
        
        # Проверка, находится ли позиция в текущем диапазоне цен
        is_in_range = tick_lower <= tick_current < tick_upper
        
        # Получаем цены из словаря token_prices
        actual_token0_price = token_prices.get(token_mint0_from_pool_state, Decimal(0))
        actual_token1_price = token_prices.get(token_mint1_from_pool_state, Decimal(0))
        
        # Детальное логирование для всех позиций
        print(f"[DEBUG] Token prices for position {position_pda}:")
        print(f"  Token0 ({token_mint0_from_pool_state}, {TOKEN_SYMBOL_MAP.get(token_mint0_from_pool_state, 'Unknown')}): ${actual_token0_price}")
        print(f"  Token1 ({token_mint1_from_pool_state}, {TOKEN_SYMBOL_MAP.get(token_mint1_from_pool_state, 'Unknown')}): ${actual_token1_price}")
        
        # Рассчитываем стоимость токенов и комиссий в USD
        token0_value_usd = amount0_adjusted * actual_token0_price
        token1_value_usd = amount1_adjusted * actual_token1_price
        fees0_value_usd = fees_owed_a_adjusted * actual_token0_price
        fees1_value_usd = fees_owed_b_adjusted * actual_token1_price
        
        # Общая стоимость позиции в USD
        position_usd_value = token0_value_usd + token1_value_usd + fees0_value_usd + fees1_value_usd
        
        # Более детальное логирование результатов для всех позиций
        print(f"[INFO] Position Value Calculation for {position_pda}:")
        print(f"  Token0 ({TOKEN_SYMBOL_MAP.get(token_mint0_from_pool_state, 'Unknown')}): {amount0_adjusted} × ${actual_token0_price} = ${token0_value_usd}")
        print(f"  Token1 ({TOKEN_SYMBOL_MAP.get(token_mint1_from_pool_state, 'Unknown')}): {amount1_adjusted} × ${actual_token1_price} = ${token1_value_usd}")
        print(f"  Fees0: {fees_owed_a_adjusted} × ${actual_token0_price} = ${fees0_value_usd}")
        print(f"  Fees1: {fees_owed_b_adjusted} × ${actual_token1_price} = ${fees1_value_usd}")
        print(f"  Total Position Value: ${position_usd_value}")
        
        # Еще более подробное логирование для BIO/MYCO
        if (token_mint0_from_pool_state == BIO_ADDRESS or token_mint1_from_pool_state == BIO_ADDRESS) and \
           (token_mint0_from_pool_state == MYCO_ADDRESS or token_mint1_from_pool_state == MYCO_ADDRESS):
            print(f"[CRITICAL_RESULT] 🚨 BIO/MYCO Position Value Breakdown for {position_pda}:")
            
            # Определяем, какой токен какой
            if token_mint0_from_pool_state == BIO_ADDRESS:
                bio_amount = amount0_adjusted
                bio_price = actual_token0_price
                bio_value = token0_value_usd
                myco_amount = amount1_adjusted
                myco_price = actual_token1_price
                myco_value = token1_value_usd
            else:
                bio_amount = amount1_adjusted
                bio_price = actual_token1_price
                bio_value = token1_value_usd
                myco_amount = amount0_adjusted
                myco_price = actual_token0_price
                myco_value = token0_value_usd
                
            print(f"[CRITICAL_RESULT] BIO: {bio_amount} × ${bio_price} = ${bio_value}")
            print(f"[CRITICAL_RESULT] MYCO: {myco_amount} × ${myco_price} = ${myco_value}")
            print(f"[CRITICAL_RESULT] Total BIO+MYCO: ${bio_value + myco_value}")
            print(f"[CRITICAL_RESULT] With Fees: ${position_usd_value}")
        
        # Формируем результирующий объект с данными позиции
        position_analysis = {
            "position_nft_mint": position_nft_mint,
            "position_pda": position_pda,
            "pool_id_from_position_state": pool_id_from_position_state,
            "target_pool_id_for_analysis": target_pool_id,
            "tick_lower": tick_lower,
            "tick_upper": tick_upper,
            "tick_current": tick_current,
            "is_in_range": is_in_range,
            "liquidity": liquidity,
            "token0": {
                "mint": token_mint0_from_pool_state,
                "symbol": TOKEN_SYMBOL_MAP.get(token_mint0_from_pool_state, "Unknown"),
                "amount": str(amount0_adjusted),
                "fees_owed": str(fees_owed_a_adjusted),
                "price_usd": str(actual_token0_price),
                "value_usd": str(token0_value_usd)
            },
            "token1": {
                "mint": token_mint1_from_pool_state,
                "symbol": TOKEN_SYMBOL_MAP.get(token_mint1_from_pool_state, "Unknown"),
                "amount": str(amount1_adjusted),
                "fees_owed": str(fees_owed_b_adjusted),
                "price_usd": str(actual_token1_price),
                "value_usd": str(token1_value_usd)
            },
            "position_usd_value": str(position_usd_value),
            # Добавляем актуальные цены токенов, чтобы они использовались при обновлении данных в main()
            "token0_price_usd": str(actual_token0_price),
            "token1_price_usd": str(actual_token1_price)
        }
        
        return position_analysis
    except Exception as e:
        print(f"Error analyzing position {position_pda} (NFT: {position_nft_mint}): {e}")
        traceback.print_exc()
        return None

async def fetch_position_data_from_json_uri(json_uri: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """
    Получает данные о позиции из json_uri Raydium CLMM NFT.
    
    Args:
        json_uri: URI JSON-метаданных NFT позиции (обычно содержит 'position?id=')
        client: httpx.AsyncClient для выполнения HTTP-запроса
        
    Returns:
        Dictionary с данными о позиции или None, если произошла ошибка
    """
    if not json_uri or "position?id=" not in json_uri:
        print(f"[WARN] Invalid json_uri: {json_uri}")
        return None
    
    try:
        # Извлекаем position_pda из json_uri
        position_pda = json_uri.split("position?id=")[1]
        
        # Базовая валидация position_pda
        try:
            if position_pda and len(position_pda) >= 32 and len(position_pda) <= 44:
                # Проверяем, что это валидный Pubkey
                Pubkey.from_string(position_pda)
            else:
                print(f"[WARN] Invalid position_pda extracted from json_uri: {position_pda}")
                return None
        except Exception as e:
            print(f"[WARN] Invalid position_pda in json_uri: {position_pda}, error: {e}")
            return None
        
        print(f"[DEBUG] Fetching position data from json_uri: {json_uri}")
        response = await client.get(json_uri, timeout=10.0)
        
        if response.status_code != 200:
            print(f"[ERROR] Failed to fetch data from json_uri. Status code: {response.status_code}")
            return None
        
        # Парсим JSON-ответ
        json_data = response.json()
        
        # Проверка наличия ключевых полей
        if not isinstance(json_data, dict):
            print(f"[ERROR] json_uri returned non-dictionary data: {type(json_data)}")
            return None
        
        # Проверка и извлечение poolInfo
        pool_info = json_data.get("poolInfo")
        if not pool_info or not isinstance(pool_info, dict):
            print(f"[ERROR] Missing or invalid poolInfo in json_uri data")
            return None
        
        # Проверка и извлечение positionInfo
        position_info = json_data.get("positionInfo")
        if not position_info or not isinstance(position_info, dict):
            print(f"[ERROR] Missing or invalid positionInfo in json_uri data")
            return None
        
        # Базовая структура результата
        result = {
            "position_pda": position_pda,
            "pool_data": {
                "id": pool_info.get("id"),
                "mintA": {
                    "address": pool_info.get("mintA", {}).get("address"),
                    "symbol": pool_info.get("mintA", {}).get("symbol"),
                    "decimals": pool_info.get("mintA", {}).get("decimals"),
                    "price": pool_info.get("mintA", {}).get("price"),
                },
                "mintB": {
                    "address": pool_info.get("mintB", {}).get("address"),
                    "symbol": pool_info.get("mintB", {}).get("symbol"),
                    "decimals": pool_info.get("mintB", {}).get("decimals"),
                    "price": pool_info.get("mintB", {}).get("price"),
                },
                "price": pool_info.get("price"),
                "tvl": pool_info.get("tvl"),
                "volume": {
                    "day": pool_info.get("day", {}).get("volume"),
                    "week": pool_info.get("week", {}).get("volume"),
                    "month": pool_info.get("month", {}).get("volume"),
                },
                "apr": {
                    "day": pool_info.get("day", {}).get("apr"),
                    "week": pool_info.get("week", {}).get("apr"),
                    "month": pool_info.get("month", {}).get("apr"),
                },
                "feeRate": pool_info.get("feeRate"),
            },
            "position_data": {
                "amountA": position_info.get("amountA"),
                "amountB": position_info.get("amountB"),
                "usdValue": position_info.get("usdValue"),
                "unclaimedFee": {
                    "amountA": position_info.get("unclaimedFee", {}).get("amountA"),
                    "amountB": position_info.get("unclaimedFee", {}).get("amountB"),
                    "usdValue": position_info.get("unclaimedFee", {}).get("usdValue"),
                },
                "tickLower": position_info.get("tickLower"),
                "tickUpper": position_info.get("tickUpper"),
                "liquidity": position_info.get("liquidity"),
            },
            "json_uri_raw_data": json_data,  # Сохраняем полный ответ для доступа к дополнительным полям при необходимости
        }
        
        return result
    
    except httpx.RequestError as e:
        print(f"[ERROR] HTTP request error for json_uri {json_uri}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON decode error for json_uri {json_uri}: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error processing json_uri {json_uri}: {e}")
        traceback.print_exc()
        return None

async def check_position_in_range(position_pda: str, pool_id: str, rpc_url: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """
    Проверяет, находится ли позиция в диапазоне цены, на основе ончейн-данных.
    
    Args:
        position_pda: PDA позиции, извлеченный из json_uri
        pool_id: ID пула, к которому принадлежит позиция
        rpc_url: URL RPC ноды
        client: httpx.AsyncClient для выполнения HTTP-запросов
        
    Returns:
        Dictionary с информацией о нахождении в диапазоне или None, если произошла ошибка
    """
    try:
        # 1. Получаем данные позиции из блокчейна
        position_account_info = await get_account_info_via_httpx(rpc_url, position_pda, client)
        if not position_account_info or not position_account_info.get("data"):
            print(f"[ERROR] Failed to fetch position account info for {position_pda}")
            return None
        
        # 2. Парсим данные позиции
        parsed_position = parse_account_data(position_account_info["data"][0], POSITION_STATE_LAYOUT)
        if not parsed_position:
            print(f"[ERROR] Failed to parse position data for {position_pda}")
            return None
        
        # 3. Получаем данные пула из блокчейна
        pool_account_info = await get_account_info_via_httpx(rpc_url, pool_id, client)
        if not pool_account_info or not pool_account_info.get("data"):
            print(f"[ERROR] Failed to fetch pool account info for {pool_id}")
            return None
        
        # 4. Парсим данные пула
        parsed_pool = parse_account_data(pool_account_info["data"][0], POOL_STATE_LAYOUT)
        if not parsed_pool:
            print(f"[ERROR] Failed to parse pool data for {pool_id}")
            return None
        
        # 5. Получаем необходимые значения
        tick_lower = parsed_position.tickLowerIndex
        tick_upper = parsed_position.tickUpperIndex
        tick_current = parsed_pool.tickCurrent
        
        # 6. Определяем, находится ли позиция в диапазоне
        in_range = tick_lower <= tick_current < tick_upper
        
        # 7. Формируем результат
        result = {
            "in_range": in_range,
            "tick_current": tick_current,
            "tick_lower": tick_lower,
            "tick_upper": tick_upper,
            "position_nft_mint": str(parsed_position.nftMint),
            "pool_id_from_position": str(parsed_position.poolId),
            "liquidity": int.from_bytes(parsed_position.liquidity, 'little', signed=False),
            "fees_owed_a": parsed_position.tokenFeesOwedA,
            "fees_owed_b": parsed_position.tokenFeesOwedB
        }
        
        return result
    
    except Exception as e:
        print(f"[ERROR] Error checking position in range for {position_pda}: {e}")
        traceback.print_exc()
        return None

async def fetch_raydium_pool_market_data(pool_id: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """
    Fetch pool market data (TVL and 24h volume) from Raydium API.
    
    Args:
        pool_id: The pool ID to query
        client: httpx.AsyncClient for HTTP requests
        
    Returns:
        Dictionary containing pool_tvl_usd and pool_24h_volume_usd, or None if error
    """
    try:
        url = f"{RAYDIUM_API_V3_BASE_URL}/pools/info/ids"
        params = {"ids": pool_id}
        
        response = await client.get(url, params=params)
        response.raise_for_status()
        response_data = response.json()
        
        if not response_data or not response_data.get("data") or not response_data["data"]:
            print(f"[ERROR] No pool market data found for {pool_id}")
            return None
        
        # Find the pool in the data array
        pool_data = None
        for pool in response_data["data"]:
            if pool.get("id") == pool_id:
                pool_data = pool
                break
        
        if not pool_data:
            print(f"[ERROR] Pool {pool_id} not found in market data response")
            return None
        
        # Extract TVL and 24h volume data
        tvl = pool_data.get("tvl", 0)
        day_data = pool_data.get("day", {})
        day_volume_quote = day_data.get("volumeQuote", 0)
        
        # Get token information to convert quote volume to USD if needed
        quote_token_mint = pool_data.get("quoteMint") # This should be token B mint
        
        # Check if volumeQuote is already in USD
        day_volume_usd_from_api = day_data.get("volumeUSD", 0)
        day_volume_from_api = day_data.get("volume", 0) # Новое поле для проверки
        pool_24h_volume_usd = Decimal("0") # Initialize with 0

        if day_volume_usd_from_api and float(day_volume_usd_from_api) > 0:
            print(f"[INFO] Using volumeUSD from API for pool {pool_id}: ${day_volume_usd_from_api}")
            pool_24h_volume_usd = Decimal(str(day_volume_usd_from_api))
        elif day_volume_from_api and float(day_volume_from_api) > 0: # Проверяем day.volume
            print(f"[INFO] Using volume (presumed USD) from API for pool {pool_id}: ${day_volume_from_api}")
            pool_24h_volume_usd = Decimal(str(day_volume_from_api))
        elif day_volume_quote and float(day_volume_quote) > 0:
            print(f"[INFO] volumeUSD and volume from API are zero or unavailable for {pool_id}. Attempting to convert volumeQuote: {day_volume_quote} of {quote_token_mint}")
            quote_token_price = None
            
            special_usd_tokens = [
                "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
                "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
                "eqKJTf1Do4MDPyKisMYqVaUFpkEFNHaFQRT8tYMfnUAn"   # USDC.e
            ]
            
            if quote_token_mint in special_usd_tokens:
                quote_token_price = Decimal("1.0")
                print(f"[INFO] Quote token {quote_token_mint} is a stablecoin. Using price $1.0")
            else:
                # Attempt to get price from GeckoTerminal first (as it's our primary source in main())
                token_prices_gt = await fetch_token_prices_geckoterminal([quote_token_mint], client)
                if token_prices_gt and quote_token_mint in token_prices_gt and token_prices_gt[quote_token_mint] > 0:
                    quote_token_price = token_prices_gt[quote_token_mint]
                    print(f"[INFO] Got price for {quote_token_mint} from GeckoTerminal: ${quote_token_price}")
                else:
                    # Fallback to CoinGecko if not found or zero in GeckoTerminal
                    coingecko_id = TOKEN_COINGECKO_IDS.get(quote_token_mint)
                    if coingecko_id:
                        today_str = datetime.now().strftime("%d-%m-%Y") # CoinGecko needs dd-mm-yyyy
                        cg_price = await fetch_historical_token_price_coingecko(coingecko_id, today_str, client)
                        if cg_price and cg_price > 0:
                            quote_token_price = cg_price
                            print(f"[INFO] Got price for {quote_token_mint} ({coingecko_id}) from CoinGecko: ${quote_token_price}")
            
            if quote_token_price and quote_token_price > 0:
                pool_24h_volume_usd = Decimal(str(day_volume_quote)) * quote_token_price
                print(f"[INFO] Calculated 24h volume for {pool_id}: {day_volume_quote} {TOKEN_SYMBOL_MAP.get(quote_token_mint, quote_token_mint)} * ${quote_token_price} = ${pool_24h_volume_usd}")
            else:
                print(f"[WARN] Could not determine price for quote token {quote_token_mint} for pool {pool_id}. USD volume for 24h will be reported as $0.")
                pool_24h_volume_usd = Decimal("0")
        else:
             print(f"[INFO] All volume fields (volumeUSD, volume, volumeQuote) are zero or unavailable for pool {pool_id}. 24h USD Volume is $0.")
             pool_24h_volume_usd = Decimal("0")
        
        return {
            "pool_tvl_usd": Decimal(str(tvl)),
            "pool_24h_volume_usd": pool_24h_volume_usd
        }
    except Exception as e:
        print(f"[ERROR] Error fetching Raydium pool market data for {pool_id}: {e}")
        traceback.print_exc()
        return None

async def fetch_bitquery_pool_daily_volume_7d(token_a_mint: str, token_b_mint: str, token_prices: Dict[str, Decimal], client: httpx.AsyncClient) -> Optional[List[Dict[str, Any]]]:
    """
    Fetches daily trading volume from BitQuery for the last 7 days for a given token pair.
    Tries to get direct USD volume, otherwise calculates using historical prices.
    """
    daily_volumes = []
    
    # Сохраняем оригинальные значения для логирования
    token_a_mint_original_for_log = token_a_mint
    token_b_mint_original_for_log = token_b_mint

    try:
        # Define base tokens for determining query parameters
        base_token_addresses = [
            "So11111111111111111111111111111111111111112",  # SOL
            "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
            "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
            "eqKJTf1Do4MDPyKisMYqVaUFpkEFNHaFQRT8tYMfnUAn"   # USDC.e
        ]
        
        # Determine which token is base and which is quote
        if token_a_mint in base_token_addresses:
            base = token_a_mint
            token = token_b_mint
        elif token_b_mint in base_token_addresses:
            base = token_b_mint
            token = token_a_mint
        else:
            # If neither is a recognized base token, use token_b as base
            base = token_b_mint
            token = token_a_mint
            
        # Получаем цену базового токена для возможных расчетов
        base_price = token_prices.get(base, Decimal(0))
        if base_price == Decimal(0):
            print(f"[INFO] Price for base token {base} missing in provided prices for daily volume calculation, fetching...")
            # Используем 'client', который уже есть в параметрах функции
            additional_prices = await fetch_token_prices_coingecko([base], client) 
            if additional_prices and base in additional_prices:
                base_price = additional_prices[base]
                print(f"[INFO] Fetched price for base token {base}: {base_price}")
                # Опционально: можно обновить словарь token_prices, переданный по ссылке
                token_prices[base] = base_price 
            else:
                print(f"[WARN] Could not fetch price for base token {base} from CoinGecko, trying GeckoTerminal...")
                # Пробуем получить цену из GeckoTerminal
                additional_prices_gt = await fetch_token_prices_geckoterminal([base], client)
                if additional_prices_gt and base in additional_prices_gt:
                    base_price = additional_prices_gt[base]
                    print(f"[INFO] Fetched price for base token {base} from GeckoTerminal: {base_price}")
                    token_prices[base] = base_price
                else:
                    print(f"[WARN] Could not fetch price for base token {base} used in daily volume query.")
                    base_price = Decimal(0) # Убедимся, что цена 0, если не удалось получить
        
        # Create dates for the last 7 days
        now = datetime.now()
        dates = []
        for i in range(7): # Loop for 7 days, i=0 is today, i=1 is yesterday, etc.
            # Start of the day 'i' days ago
            day_start_obj = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            # End of the day 'i' days ago
            day_end_obj = day_start_obj.replace(hour=23, minute=59, second=59, microsecond=0) # End of the same day

            dates.append({
                "date_start": day_start_obj.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "date_end": day_end_obj.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "display_date": day_start_obj.strftime("%Y-%m-%d"),
                "date_obj": day_start_obj  # Добавляем сам объект даты для использования ниже
            })
        
        # GraphQL query for daily volumes - обновленный запрос с полем volume
        query = """
        query DailyVolume($token: String, $base: String, $after: DateTime!, $before: DateTime!) {
          Solana(network: solana, dataset: archive) {
            DEXTradeByTokens(
              where: {
                Transaction: {Result: {Success: true}}, 
                Trade: {
                  Side: {Amount: {gt: "0"}, Currency: {MintAddress: {is: $base}}}, 
                  Currency: {MintAddress: {is: $token}}
                }, 
                Block: {Time: {since: $after, till: $before}}
              }
            ) {
              trades: count
              daily_usd_volume: sum(of: Trade_Side_AmountInUSD)
              volume: sum(of: Trade_Side_Amount)
            }
          }
        }
        """
        
        # Headers for BitQuery API
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": BITQUERY_API_KEY
        }
        
        # Fetch data for each day
        for i, date_item in enumerate(dates):
            # Добавляем случайную задержку между запросами (кроме первого)
            if i > 0:
                delay = random.uniform(1.0, 2.0)
                print(f"[DEBUG] Adding delay of {delay:.2f}s between BitQuery requests")
                await asyncio.sleep(delay)
                
            variables = {
                "token": token,
                "base": base,
                "after": date_item["date_start"],
                "before": date_item["date_end"]
            }
            # Улучшенное логирование переменных запроса
            print(f"[DEBUG_BITQUERY_VARS] Original Pair: {token_a_mint_original_for_log}/{token_b_mint_original_for_log} on {date_item['display_date']}. Querying BitQuery with TOKEN={token} (Quote), BASE={base} (Base)")
            
            payload = {
                "query": query,
                "variables": variables
            }
            
            # Инициализируем переменные перед блоком try, чтобы они всегда были определены
            summary_data = None # <--- Инициализация summary_data
            daily_token_b_volume = Decimal("0") # <--- Инициализация daily_token_b_volume
            usd_volume_for_day = Decimal("0")
            source_info = 'not_available' # Источник по умолчанию

            try:
                # Сразу используем Authorization: Bearer
                headers_bearer = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {BITQUERY_API_KEY}"
                }
                print(f"[DEBUG_AUTH] Using Authorization Bearer for {token_a_mint_original_for_log}/{token_b_mint_original_for_log} on {date_item['display_date']}")
                response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers_bearer)
                
                # Закомментированная логика для X-API-KEY и переключения
                # headers_api_key = {
                #     "Content-Type": "application/json",
                #     "X-API-KEY": BITQUERY_API_KEY
                # }
                # response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers_api_key)
                # 
                # if response.status_code == 401: # Unauthorized
                #     print(f"[INFO_AUTH] BitQuery request with X-API-KEY failed for {token_a_mint_original_for_log}/{token_b_mint_original_for_log} on {date_item['display_date']}. Status: {response.status_code}. Retrying with Authorization Bearer header.")
                #     headers_bearer = {
                #         "Content-Type": "application/json",
                #         "Authorization": f"Bearer {BITQUERY_API_KEY}"
                #     }
                #     response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers_bearer)
                
                response.raise_for_status()
                response_data = response.json()
                
                if "errors" in response_data:
                    print(f"[WARN] GraphQL errors for date {date_item['display_date']}: {response_data['errors']}")
                    daily_volumes.append({"date": date_item["display_date"], "daily_usd_volume": Decimal("0"), "source": "api_error"})
                    continue
                
                # --- START OF NEW DEBUG LOGGING ---
                if "data" in response_data and response_data.get("data", {}).get("Solana", {}).get("DEXTradeByTokens"):
                    raw_dex_trades_data = response_data["data"]["Solana"]["DEXTradeByTokens"]
                    current_day_data_from_bq = raw_dex_trades_data[0] if isinstance(raw_dex_trades_data, list) and raw_dex_trades_data else raw_dex_trades_data

                    if current_day_data_from_bq and isinstance(current_day_data_from_bq, dict):
                        # Логируем что получили от BitQuery с явным указанием переменных запроса
                        print(f"[BITQUERY_RAW_DEBUG] Date: {date_item['display_date']}, Queried Pair: TOKEN(Quote)={token}/BASE(Base)={base}")
                        print(f"[BITQUERY_RAW_DEBUG] Raw trades_count from BQ: {current_day_data_from_bq.get('trades')}")
                        print(f"[BITQUERY_RAW_DEBUG] Raw daily_usd_volume (sum of Trade_Side_AmountInUSD) from BQ: {current_day_data_from_bq.get('daily_usd_volume')}")
                        print(f"[BITQUERY_RAW_DEBUG] Raw volume (sum of Trade_Side_Amount for BASE token {base}) from BQ: {current_day_data_from_bq.get('volume')}")
                    else:
                        print(f"[BITQUERY_RAW_DEBUG] Date: {date_item['display_date']}, Queried Pair: TOKEN(Quote)={token}/BASE(Base)={base} - NO VALID DATA in DEXTradeByTokens block: {raw_dex_trades_data}")
                else:
                    print(f"[BITQUERY_RAW_DEBUG] Date: {date_item['display_date']}, Queried Pair: TOKEN(Quote)={token}/BASE(Base)={base} - NO DEXTradeByTokens in response or errors occurred earlier. Response keys: {list(response_data.keys()) if isinstance(response_data, dict) else 'Not a dict'}")
                # --- END OF MODIFIED DEBUG LOGGING ---\n
                
                # Extract volume data from response - обновленная логика для обработки ответа
                extracted_data_block = response_data.get("data", {}).get("Solana", {}).get("DEXTradeByTokens")
                
                # usd_volume_for_day = Decimal("0") # Уже инициализировано выше
                # source_info = 'not_available' # Уже инициализировано выше
                # daily_token_b_volume = Decimal("0")  # Уже инициализировано выше
                
                if extracted_data_block:
                    # summary_data = None # Эта инициализация здесь не нужна, если она есть до try
                    if isinstance(extracted_data_block, list):
                        if extracted_data_block:  # Если список не пустой
                            summary_data = extracted_data_block[0]
                    elif isinstance(extracted_data_block, dict):
                        summary_data = extracted_data_block
                        
                    if summary_data:
                        # Сохраняем объем токена B для использования ниже
                        base_volume_str = summary_data.get('volume')
                        if base_volume_str is not None:
                            try:
                                daily_token_b_volume = Decimal(str(base_volume_str))
                            except Exception:
                                daily_token_b_volume = Decimal("0") # В случае ошибки, ставим 0
                                
                        # Пытаемся получить прямой USD объем
                        direct_usd_volume_str = summary_data.get("daily_usd_volume")
                        if direct_usd_volume_str is not None:
                            try:
                                direct_usd_volume_decimal = Decimal(str(direct_usd_volume_str))
                                usd_volume_for_day = direct_usd_volume_decimal
                                source_info = 'direct_from_api'
                            except Exception:
                                direct_usd_volume_str = None  # Считаем невалидным
                        
                        # Если прямой USD объем 0 или очень мал, пытаемся рассчитать с использованием исторической цены
                        if usd_volume_for_day < Decimal("0.01") and daily_token_b_volume > Decimal("0"):
                            # Если базовый токен - это SOL или BIO, попробуем получить историческую цену
                            coingecko_id_for_b = TOKEN_COINGECKO_IDS.get(base)
                            if coingecko_id_for_b:
                                print(f"[INFO] BitQuery USD volume for {token}/{base} on {date_item['display_date']} is zero. Attempting historical calculation for token_b: {base}")
                                # Форматируем дату в формат CoinGecko (dd-mm-yyyy)
                                day_date_str = date_item["date_obj"].strftime("%d-%m-%Y")
                                historical_price_token_b = await fetch_historical_token_price_coingecko(coingecko_id_for_b, day_date_str, client)
                                
                                if historical_price_token_b is not None:
                                    final_daily_usd_volume = daily_token_b_volume * historical_price_token_b
                                    usd_volume_for_day = final_daily_usd_volume
                                    source_info = f'historical_price_{coingecko_id_for_b}'
                                    print(f"[INFO] Calculated USD volume for {date_item['display_date']} using historical price for {base} ({coingecko_id_for_b}): {historical_price_token_b}. New volume: {final_daily_usd_volume}")
                                else:
                                    # Если не удалось получить историческую цену, используем текущую цену
                                    if base_price > Decimal("0"):
                                        calculated_usd = daily_token_b_volume * base_price
                                        usd_volume_for_day = calculated_usd
                                        source_info = 'calculated_from_current_price'
                                        print(f"[INFO] Could not fetch historical price for {base} ({coingecko_id_for_b}) on {day_date_str}. Using current price: {base_price}")
                                    else:
                                        usd_volume_for_day = Decimal(0)
                                        source_info = f'historical_price_not_available_for_{base}'
                                        print(f"[WARNING] Could not fetch historical price for {base} ({coingecko_id_for_b}) on {day_date_str} and no current price. USD volume remains 0.")
                            else:
                                # Если токен не в словаре TOKEN_COINGECKO_IDS, используем текущую цену
                                if base_price > Decimal("0"):
                                    calculated_usd = daily_token_b_volume * base_price
                                    usd_volume_for_day = calculated_usd
                                    source_info = 'calculated_from_current_price'
                                    print(f"[WARNING] Token {base} not found in TOKEN_COINGECKO_IDS. Cannot fetch historical price. Using current price: {base_price}")
                                else:
                                    usd_volume_for_day = Decimal(0)
                                    source_info = f'token_not_in_coingecko_ids_no_price_for_{base}'
                                    print(f"[WARNING] Token {base} not found in TOKEN_COINGECKO_IDS and no current price. Cannot calculate USD volume.")
                    else:  # Если summary_data отсутствует
                        source_info = 'no_summary_data'
                
                # Добавляем результат для этого дня с информацией об источнике и объеме токена B
                daily_volumes.append({
                    "date": date_item["display_date"], 
                    "daily_usd_volume": usd_volume_for_day,
                    "volume": daily_token_b_volume, # Используем daily_token_b_volume, которая теперь всегда определена
                    "trades": int(summary_data.get("trades", 0)) if summary_data else 0,
                    "source": source_info 
                })
                
            except Exception as e:
                print(f"[ERROR] Error fetching daily volume for {date_item['display_date']}: {e}")
                # Добавляем запись с нулями и корректным source, даже если была ошибка до присвоения daily_volumes.append
                daily_volumes.append({
                    "date": date_item["display_date"], 
                    "daily_usd_volume": Decimal("0"), 
                    "volume": Decimal("0"),
                    "trades": 0,
                    "source": f"exception_in_processing - {str(e)}" # Более информативный source
                })
        
        # Return the 7-day data in chronological order (oldest first)
        return list(reversed(daily_volumes))
        
    except Exception as e:
        print(f"[ERROR] Error in fetch_bitquery_pool_daily_volume_7d: {e}")
        traceback.print_exc()
        return None

async def fetch_bitquery_token_minute_candles_7d(token_mint: str, quote_currency_mint: str, client: httpx.AsyncClient) -> Optional[List[Dict[str, Any]]]:
    """
    Fetch minute OHLCV price candles for a token over the last 7 days using BitQuery GraphQL API.
    
    Args:
        token_mint: Mint address of the token to get price data for
        quote_currency_mint: Mint address of the quote currency (usually USDC)
        client: httpx.AsyncClient for HTTP requests
        
    Returns:
        List of OHLCV candle data with minute resolution, or None if error
    """
    try:
        # We can't fetch 7 days of minute candles in one request (10080 candles)
        # So we'll fetch data in 1-day chunks
        all_candles = []
        now = datetime.now()
        
        # Define date ranges for the last 7 days (in 1-day chunks)
        date_ranges = []
        for i in range(7):
            day_start = (now - timedelta(days=i+1))
            day_end = (now - timedelta(days=i))
            date_ranges.append({
                "date_start": day_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "date_end": day_end.strftime("%Y-%m-%dT%H:%M:%SZ")
            })
        
        # GraphQL query for OHLCV minute candles
        # This query gets OHLCV data for trading pairs containing our token and quote currency
        query = """
        query tokencandles($token: String, $quote: String, $from: DateTime!, $to: DateTime!) {
          Solana(network: solana, dataset: archive) {
            DEXTradeByTokens(
              where: {
                Trade: {
                  Side: {Currency: {MintAddress: {in: [$token, $quote]}}},
                  Currency: {MintAddress: {in: [$token, $quote]}}
                },
                Block: {Time: {since: $from, till: $to}}
              }
              orderBy: {ascending: Block_Time}
            ) {
              timeInterval {
                minute(count: 1)
              }
              high: maximum(of: Trade_Price, selectWhere: {Trade: {Currency: {MintAddress: {is: $token}}}})
              low: minimum(of: Trade_Price, selectWhere: {Trade: {Currency: {MintAddress: {is: $token}}}})
              open: minimum(of: Trade_Price, selectWhere: {Trade: {Currency: {MintAddress: {is: $token}}}, timeInterval: {minute: {count: 1}}}, orderBy: {ascending: Block_Time})
              close: maximum(of: Trade_Price, selectWhere: {Trade: {Currency: {MintAddress: {is: $token}}}, timeInterval: {minute: {count: 1}}}, orderBy: {descending: Block_Time})
              volume: sum(of: Trade_Amount, selectWhere: {Trade: {Currency: {MintAddress: {is: $token}}}})
              volumeUSD: sum(of: Trade_AmountInUSD, selectWhere: {Trade: {Currency: {MintAddress: {is: $token}}}})
              Block {
                Time
              }
            }
          }
        }
        """
        
        # Headers for BitQuery API
        headers = {
            "Content-Type": "application/json",
            "X-API-KEY": BITQUERY_API_KEY
        }
        
        # Fetch data for each day
        for date_range in date_ranges:
            variables = {
                "token": token_mint,
                "quote": quote_currency_mint,
                "from": date_range["date_start"],
                "to": date_range["date_end"]
            }
            
            payload = {
                "query": query,
                "variables": variables
            }
            
            try:
                print(f"[INFO] Fetching minute candles for {token_mint} from {date_range['date_start']} to {date_range['date_end']}")
                response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers)
                
                # Try with Authorization Bearer header if X-API-KEY fails
                if response.status_code == 401:
                    headers = {
                        "Content-Type": "application/json", 
                        "Authorization": f"Bearer {BITQUERY_API_KEY}"
                    }
                    response = await client.post(BITQUERY_ENDPOINT, json=payload, headers=headers)
                
                response.raise_for_status()
                response_data = response.json()
                
                if "errors" in response_data:
                    print(f"[WARN] GraphQL errors for candles: {response_data['errors']}")
                    continue
                
                # Extract candle data from response
                candles_data = response_data.get("data", {}).get("Solana", {}).get("DEXTradeByTokens", [])
                
                # Process each candle
                for candle in candles_data:
                    block_time = None
                    if candle.get("Block") and candle["Block"].get("Time"):
                        block_time = candle["Block"]["Time"]
                    
                    # Add only valid candles (those with all OHLCV data)
                    if block_time and all(k in candle for k in ["open", "high", "low", "close", "volume", "volumeUSD"]):
                        all_candles.append({
                            "timestamp": block_time,
                            "open": Decimal(str(candle.get("open") or 0)),
                            "high": Decimal(str(candle.get("high") or 0)),
                            "low": Decimal(str(candle.get("low") or 0)),
                            "close": Decimal(str(candle.get("close") or 0)),
                            "volume": Decimal(str(candle.get("volume") or 0)),
                            "volumeUSD": Decimal(str(candle.get("volumeUSD") or 0))
                        })
                
                # Small delay to avoid rate limiting
                await asyncio.sleep(0.5)
                
            except Exception as e:
                print(f"[ERROR] Error fetching candles for date range {date_range['date_start']} to {date_range['date_end']}: {e}")
                continue
        
        print(f"[INFO] Fetched {len(all_candles)} minute candles for {token_mint}")
        return all_candles
        
    except Exception as e:
        print(f"[ERROR] Error in fetch_bitquery_token_minute_candles_7d: {e}")
        traceback.print_exc()
        return None

async def fetch_token_prices_geckoterminal(token_addresses: List[str], client: httpx.AsyncClient) -> Dict[str, Decimal]:
    """Fetch token prices from GeckoTerminal API"""
    try:
        prices = {}
        
        print(f"[DEBUG] STARTING GeckoTerminal price fetch for {len(token_addresses)} tokens: {token_addresses}")
        
        for token_address in token_addresses:
            print(f"[INFO] Fetching price from GeckoTerminal for token {token_address}...")
            https_url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{token_address}"
            
            try:
                headers = {"Accept": "application/json"}
                print(f"[DEBUG] GeckoTerminal API request URL: {https_url}")
                response = await client.get(https_url, headers=headers)
                
                print(f"[DEBUG] GeckoTerminal response status: {response.status_code}")
                
                if response.status_code != 200:
                    print(f"[WARN] GeckoTerminal: Could not fetch price for {token_address}. Status: {response.status_code}")
                    continue
                
                response_data = response.json()
                print(f"[DEBUG] GeckoTerminal raw response: {response_data}")
                
                price_usd = None
                if response_data and "data" in response_data and "attributes" in response_data["data"]:
                    price_usd = response_data["data"]["attributes"].get("price_usd")
                
                if price_usd is not None and price_usd != "":
                    price_decimal = Decimal(str(price_usd))
                    prices[token_address] = price_decimal
                    print(f"[INFO] GeckoTerminal: Price for {token_address} = {price_usd} USD")
                else:
                    print(f"[WARN] GeckoTerminal: Price not found or invalid in response for {token_address}.")
                    
            except httpx.HTTPError as e:
                print(f"[WARN] GeckoTerminal: HTTP error for {token_address}: {e}")
            except json.JSONDecodeError as e:
                print(f"[WARN] GeckoTerminal: JSON decode error for {token_address}: {e}")
            except Exception as e:
                print(f"[WARN] GeckoTerminal: Error fetching price for {token_address}: {e}")
        
        print(f"[DEBUG] COMPLETED GeckoTerminal price fetch. Found prices for {len(prices)}/{len(token_addresses)} tokens")
        return prices
    except Exception as e:
        print(f"[ERROR] Error in fetch_token_prices_geckoterminal: {e}")
        return {}

# Основная функция
async def main():
    """
    Основная функция для анализа пула и позиций кошелька с использованием
    функции get_clmm_positions из positions.py как единственного источника
    данных о позициях. Поддерживает анализ нескольких основных пулов.
    """
    start_time = datetime.now()
    
    print(f"{'=' * 50}")
    print(f"Raydium CLMM Pool Analyzer (Расширенная версия)")
    print(f"{'=' * 50}")
    print(f"Analysis started at: {start_time.isoformat()}")
    print(f"Configuration:")
    print(f"  Target wallet: {TARGET_WALLET_ADDRESS}")
    print(f"  Primary target pools for detailed analysis: {PRIMARY_TARGET_POOL_IDS}")
    print(f"  Helius RPC URL: {HELIUS_RPC_URL[:30]}...")
    print(f"{'=' * 50}")
    
    print(f"Target wallet: {TARGET_WALLET_ADDRESS}")
    
    # Создаем общий httpx клиент для всех запросов
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Шаг 1: Получаем все активные CLMM позиции кошелька через positions.py
        print("[INFO] Fetching all CLMM positions via positions.py...")
        all_wallet_positions = await get_clmm_positions(
            TARGET_WALLET_ADDRESS, 
            HELIUS_RPC_URL, 
            HELIUS_API_KEY
        )
        
        if not all_wallet_positions:
            print(f"[ERROR] No active Raydium CLMM positions found for wallet {TARGET_WALLET_ADDRESS}")
            return
        
        print(f"[INFO] Found {len(all_wallet_positions)} active CLMM positions for wallet {TARGET_WALLET_ADDRESS}")
        
        # Шаг 1.5: Создаем "мастер-словарь" цен всех токенов
        print("[INFO] Creating master token price dictionary for all positions...")
        master_token_prices: Dict[str, Decimal] = {}
        
        # Собираем все уникальные адреса токенов из всех позиций
        all_token_addresses = set()
        for position_data in all_wallet_positions:
            token0 = position_data.get("token0")
            token1 = position_data.get("token1")
            if token0:
                all_token_addresses.add(token0)
            if token1:
                all_token_addresses.add(token1)
        
        print(f"[INFO] Found {len(all_token_addresses)} unique tokens across all positions")
        
        # Получаем цены ВСЕХ токенов ИСКЛЮЧИТЕЛЬНО из GeckoTerminal
        if all_token_addresses:
            print(f"[INFO] Fetching ALL token prices EXCLUSIVELY from GeckoTerminal for {len(all_token_addresses)} tokens...")
            # Передаем list(all_token_addresses), так как fetch_token_prices_geckoterminal ожидает List
            gecko_terminal_prices = await fetch_token_prices_geckoterminal(list(all_token_addresses), client)
            
            # Обновляем master_token_prices, устанавливая 0 для отсутствующих цен
            for token_addr in all_token_addresses:
                price = gecko_terminal_prices.get(token_addr, Decimal(0))
                master_token_prices[token_addr] = price
                if price == Decimal(0):
                    print(f"[WARN] No price returned from GeckoTerminal for token: {token_addr} ({TOKEN_SYMBOL_MAP.get(token_addr, 'Unknown')}). Will use $0.")
                else:
                    print(f"[INFO] GeckoTerminal price for {token_addr} ({TOKEN_SYMBOL_MAP.get(token_addr, 'Unknown')}): ${price}")
            
            print(f"[INFO] GeckoTerminal fetch complete. Processed prices for all {len(all_token_addresses)} unique tokens.")
        else:
            print("[INFO] No token addresses found to fetch prices for. master_token_prices remains empty.")
            
        # Дополнительная проверка цен для важных токенов (BIO, MYCO, SPINE)
        critical_tokens = [BIO_ADDRESS, MYCO_ADDRESS, SPINE_ADDRESS]
        for token in critical_tokens:
            if token in master_token_prices:
                price = master_token_prices[token]
                if price == Decimal(0):
                    print(f"[CRITICAL WARNING] Price for {token} ({TOKEN_SYMBOL_MAP.get(token, 'Unknown')}) is $0!")
                else:
                    print(f"[CRITICAL INFO] Price for {token} ({TOKEN_SYMBOL_MAP.get(token, 'Unknown')}) is ${price}")
            else:
                print(f"[CRITICAL ERROR] {token} ({TOKEN_SYMBOL_MAP.get(token, 'Unknown')}) not found in master_token_prices!")
        
        # Шаг 1.8: Вывод итоговых цен в формате таблицы
        print(f"[INFO] Final token prices (EXCLUSIVELY from GeckoTerminal) for position calculations:")
        print(f"{'-' * 70}") # Увеличил ширину для читаемости
        print(f"{'Token Address':<45} | {'Symbol':<10} | {'Price USD':<10}")
        print(f"{'-' * 70}")
        
        if master_token_prices:
            for token_address, price in master_token_prices.items():
                symbol = TOKEN_SYMBOL_MAP.get(token_address, "Unknown")
                price_display = f"${price}" if price > Decimal(0) else "$0.00 (Not Found)"
                print(f"{token_address:<45} | {symbol:<10} | {price_display:<10}")
        else:
            print("No token prices were fetched or available.")
        print(f"{'-' * 70}")
        
        # Переменная token_price_sources для вывода в таблицу - заполняем одним значением для всех
        token_price_sources = {token: "GeckoTerminal" for token in master_token_prices}
        
        # Шаг 2: Анализируем данные для каждого из основных пулов
        detailed_report_data_for_primary_pools = []
        
        # Получаем состояния пулов онлайн заранее (для эффективности)
        target_pools_onchain_states = {}
        for pool_id in PRIMARY_TARGET_POOL_IDS:
            print(f"[INFO] Pre-fetching onchain state for pool {pool_id}")
            pool_state = await fetch_onchain_pool_state(HELIUS_RPC_URL, pool_id, client)
            if pool_state:
                target_pools_onchain_states[pool_id] = pool_state
                print(f"[INFO] Successfully fetched onchain state for pool {pool_id}")
            else:
                print(f"[WARN] Failed to fetch onchain state for pool {pool_id}")
        
        for current_pool_id_from_list in PRIMARY_TARGET_POOL_IDS:
            # Фильтруем позиции для текущего целевого пула
            positions_in_this_main_pool = [pos for pos in all_wallet_positions if pos["pool_id"] == current_pool_id_from_list]
            
            if not positions_in_this_main_pool:
                print(f"[INFO] No positions found in primary pool {current_pool_id_from_list}")
                continue
                
            print(f"[INFO] Found {len(positions_in_this_main_pool)} positions in primary pool {current_pool_id_from_list}")
            
            # Получаем рыночные данные пула (TVL и 24h объем)
            print(f"[INFO] Fetching market data for pool {current_pool_id_from_list}")
            pool_market_data = await fetch_raydium_pool_market_data(current_pool_id_from_list, client)
            
            pool_tvl_usd = Decimal("0")
            pool_24h_volume_usd = Decimal("0")
            
            if pool_market_data:
                pool_tvl_usd = pool_market_data.get("pool_tvl_usd", Decimal("0"))
                pool_24h_volume_usd = pool_market_data.get("pool_24h_volume_usd", Decimal("0"))
                print(f"[INFO] Pool TVL: ${pool_tvl_usd}, 24h Volume: ${pool_24h_volume_usd}")
            else:
                print(f"[WARN] Could not fetch market data for pool {current_pool_id_from_list}")
            
            # Берем информацию из первой позиции этого пула
            first_position = positions_in_this_main_pool[0]
            
            # Получаем объем торгов пула за 7 дней по дням
            token0_address = first_position["token0"]
            token1_address = first_position["token1"]
            
            # Передаем общий словарь цен в запрос для дневных объемов
            print(f"[INFO] Fetching 7-day daily volume for pool {first_position['pool_name']}")
            daily_volumes_7d = await fetch_bitquery_pool_daily_volume_7d(
                token_a_mint=token0_address, 
                token_b_mint=token1_address, 
                token_prices=master_token_prices,  # Используем обновленный мастер-словарь цен
                client=client
            )
            
            # Получаем минутные свечи цены для обоих токенов пула (за 7 дней)
            # Для свечей используем USDC как quote currency
            usdc_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC mint address
            
            print(f"[INFO] Fetching 7-day minute candles for token {TOKEN_SYMBOL_MAP.get(token0_address, 'token0')}")
            token0_candles_7d = await fetch_bitquery_token_minute_candles_7d(token0_address, usdc_mint, client)
            
            print(f"[INFO] Fetching 7-day minute candles for token {TOKEN_SYMBOL_MAP.get(token1_address, 'token1')}")
            token1_candles_7d = await fetch_bitquery_token_minute_candles_7d(token1_address, usdc_mint, client)
            
            # Получаем исторические данные о торгах за 7 дней
            print(f"[INFO] Fetching 7-day historical trade data for {first_position['pool_name']}")
            historical_trades_data_list = await fetch_bitquery_trade_history(token0_address, token1_address, days_ago=7, client=client)
            
            if historical_trades_data_list:
                tokens_for_historical_volume_calc = set()
                for record_item in historical_trades_data_list: 
                    usd_volume_val = record_item.get('usd_volume')
                    # Проверяем, что usd_volume либо отсутствует, либо равен 0
                    if usd_volume_val is None or (isinstance(usd_volume_val, (str, int, float)) and Decimal(str(usd_volume_val)) == Decimal(0)):
                        base_mint = record_item.get('Trade', {}).get('Side', {}).get('Currency', {}).get('MintAddress')
                        if base_mint:
                            tokens_for_historical_volume_calc.add(base_mint)
                
                tokens_needing_fetch = [
                    token_mint for token_mint in tokens_for_historical_volume_calc 
                    if token_mint not in master_token_prices or master_token_prices.get(token_mint, Decimal(0)) == Decimal(0)
                ]
                
                if tokens_needing_fetch:
                    print(f"[INFO] Fetching additional prices for {len(tokens_needing_fetch)} tokens for historical USD volume calculation")
                    additional_prices = await fetch_token_prices_coingecko(tokens_needing_fetch, client)
                    if additional_prices:
                        for token_mint, price_val in additional_prices.items():
                            if price_val > 0:
                                master_token_prices[token_mint] = Decimal(str(price_val))
                                token_price_sources[token_mint] = "CoinGecko"
                                print(f"[INFO] Updated price for {token_mint} ({TOKEN_SYMBOL_MAP.get(token_mint, 'Unknown')}): ${price_val} from CoinGecko")
                    
                    # Проверяем, остались ли токены, для которых не смогли получить цены через CoinGecko
                    tokens_still_needing_price_after_cg = [
                        token_mint for token_mint in tokens_needing_fetch
                        if token_mint not in master_token_prices or master_token_prices.get(token_mint, Decimal(0)) == Decimal(0)
                    ]
                    
                    if tokens_still_needing_price_after_cg:
                        print(f"[INFO] Fetching prices from GeckoTerminal for {len(tokens_still_needing_price_after_cg)} tokens")
                        gt_prices = await fetch_token_prices_geckoterminal(tokens_still_needing_price_after_cg, client)
                        if gt_prices:
                            for token_mint, price_val in gt_prices.items():
                                if price_val > 0:
                                    master_token_prices[token_mint] = price_val
                                    token_price_sources[token_mint] = "GeckoTerminal"
                                    print(f"[INFO] Updated price for {token_mint} ({TOKEN_SYMBOL_MAP.get(token_mint, 'Unknown')}): ${price_val} from GeckoTerminal")
            
            # Рассчитываем агрегированную статистику на основе исторических данных
            total_hist_records = 0
            sum_hist_trades_count = Decimal(0)
            sum_hist_volume_base = Decimal(0) # Это объем в базовом токене *транзакции*, а не пула
            sum_hist_usd_volume = Decimal(0)  # Эта переменная будет теперь заполняться по новой логике
            sum_hist_buy_volume_base = Decimal(0)
            sum_hist_sell_volume_base = Decimal(0)
            base_token_symbol_for_hist = "N/A" 
            
            if historical_trades_data_list:
                total_hist_records = len(historical_trades_data_list)
                
                base_token_addresses_list = [
                    "So11111111111111111111111111111111111111112",
                    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
                    "eqKJTf1Do4MDPyKisMYqVaUFpkEFNHaFQRT8tYMfnUAn"
                ]
                determined_base_mint_for_display = "" 
                if token0_address in base_token_addresses_list:
                    determined_base_mint_for_display = token0_address
                elif token1_address in base_token_addresses_list:
                    determined_base_mint_for_display = token1_address
                else:
                    determined_base_mint_for_display = token1_address 
                base_token_symbol_for_hist = TOKEN_SYMBOL_MAP.get(determined_base_mint_for_display, determined_base_mint_for_display[:6]+"...")

                for record in historical_trades_data_list: 
                    sum_hist_trades_count += Decimal(str(record.get('trades', 0) or 0))
                    
                    record_base_volume_str = record.get('volume')
                    sum_hist_volume_base += Decimal(str(record_base_volume_str or '0'))
                    
                    sum_hist_buy_volume_base += Decimal(str(record.get('buy_volume', 0) or 0))
                    sum_hist_sell_volume_base += Decimal(str(record.get('sell_volume', 0) or 0))

                    usd_volume_direct_str = record.get('usd_volume')
                    calculated_usd_this_record = Decimal(0)
                    usd_volume_source_info = 'direct_from_api'

                    if usd_volume_direct_str is not None:
                        try:
                            direct_decimal_val = Decimal(str(usd_volume_direct_str))
                            if direct_decimal_val != Decimal(0):
                                calculated_usd_this_record = direct_decimal_val
                        except Exception: 
                            usd_volume_direct_str = None 

                    if usd_volume_direct_str is None or calculated_usd_this_record == Decimal(0):
                        base_volume_for_calc_str = record.get('volume') 
                        base_token_mint_for_record = record.get('Trade', {}).get('Side', {}).get('Currency', {}).get('MintAddress')

                        if base_volume_for_calc_str is not None and base_token_mint_for_record:
                            try:
                                base_volume_decimal = Decimal(str(base_volume_for_calc_str))
                                price_of_base_for_record = master_token_prices.get(base_token_mint_for_record, Decimal(0))

                                if price_of_base_for_record > 0:
                                    calculated_usd_this_record = base_volume_decimal * price_of_base_for_record
                                    usd_volume_source_info = 'calculated_from_base_volume'
                                    print(f"[DEBUG_CALC_USD] Calculated USD volume for record. Base Mint: {base_token_mint_for_record}, Base Vol: {base_volume_decimal}, Price: {price_of_base_for_record}, Result USD: {calculated_usd_this_record}")
                                else:
                                    usd_volume_source_info = f'calculation_failed_no_price_for_{base_token_mint_for_record}'
                                    print(f"[DEBUG_CALC_USD] Failed to calculate USD volume for record. No price for Base Mint: {base_token_mint_for_record}")

                            except Exception as e_calc:
                                usd_volume_source_info = 'calculation_error'
                                print(f"[DEBUG_CALC_USD] Error during USD calculation for record ({base_token_mint_for_record}): {e_calc}")
                        else:
                            usd_volume_source_info = 'missing_data_for_calculation'
                            print(f"[DEBUG_CALC_USD] Missing data for USD calculation for record. Base Mint: {base_token_mint_for_record}, Base Vol Str: {base_volume_for_calc_str}")
                    
                    record['usd_volume'] = str(calculated_usd_this_record) 
                    record['usd_volume_source_info'] = usd_volume_source_info 
                    
                    sum_hist_usd_volume += calculated_usd_this_record
            
            # Теперь рассчитаем долю ликвидности для каждой позиции
            for pos in positions_in_this_main_pool:
                if pool_tvl_usd > 0:
                    pos_value_usd = Decimal(pos["position_value_usd"])
                    pos["position_liquidity_share"] = str(pos_value_usd / pool_tvl_usd)
                    pos["position_liquidity_share_percent"] = str((pos_value_usd / pool_tvl_usd) * 100)
                else:
                    pos["position_liquidity_share"] = "0"
                    pos["position_liquidity_share_percent"] = "0"
            
            # Шаг 3: Анализируем каждую позицию в пуле для получения более точной информации
            analyzed_positions = []
            for position_data in positions_in_this_main_pool:
                print(f"[INFO] Analyzing position {position_data['position_mint']} in pool {current_pool_id_from_list}")
                
                # Проверяем наличие ключей перед вызовом функции
                if 'position_mint' in position_data and 'pool_id' in position_data:
                    # Получаем position_pda, или используем position_mint как запасной вариант
                    position_pda = position_data.get("position_pda", position_data['position_mint'])
                    
                    analyzed_position_details = await analyze_single_position(
                        position_nft_mint=position_data["position_mint"],
                        position_pda=position_pda,
                        target_pool_id=position_data["pool_id"], 
                        pool_onchain_state=target_pools_onchain_states.get(position_data["pool_id"]),
                        token_prices=master_token_prices,  # Используем обновленный мастер-словарь
                        rpc_url=HELIUS_RPC_URL,
                        client=client
                    )
                    
                    if analyzed_position_details:
                        # Обновляем позицию с дополнительными данными
                        for key, value in analyzed_position_details.items():
                            # Всегда обновляем ключи token0_price_usd и token1_price_usd даже если они уже есть
                            if key in ["token0_price_usd", "token1_price_usd", "position_usd_value"] or key not in position_data:
                                position_data[key] = value
                        
                        analyzed_positions.append(position_data)
                    else:
                        print(f"[WARN] Failed to analyze position {position_data['position_mint']}")
                else:
                    print(f"[WARN] Missing required keys in position_data: {position_data.keys()}")
            
            # Формируем данные пула для отчета
            pool_specific_data = {
                "id": current_pool_id_from_list,
                "name": first_position["pool_name"],
                "positions": positions_in_this_main_pool,
                "mintA": {
                    "address": first_position["token0"],
                    "symbol": first_position["pool_name"].split('/')[0],
                    "decimals": None,
                    "price": master_token_prices.get(first_position["token0"], Decimal(0))  # Используем цену из мастер-словаря
                },
                "mintB": {
                    "address": first_position["token1"],
                    "symbol": first_position["pool_name"].split('/')[1],
                    "decimals": None,
                    "price": master_token_prices.get(first_position["token1"], Decimal(0))  # Используем цену из мастер-словаря
                },
                "price": first_position["current_price"],
                "feeRate": first_position["fee_tier"],
                "total_usd_value": sum(Decimal(pos["position_value_usd"]) for pos in positions_in_this_main_pool),
                "in_range_positions": sum(1 for pos in positions_in_this_main_pool if pos["in_range"] is True),
                "out_of_range_positions": sum(1 for pos in positions_in_this_main_pool if pos["in_range"] is False),
                # Добавляем новые поля
                "pool_tvl_usd": str(pool_tvl_usd),
                "pool_24h_volume_usd": str(pool_24h_volume_usd),
                "pool_7d_daily_volumes": daily_volumes_7d if daily_volumes_7d else [],
                "token0_candles_7d_minute": token0_candles_7d if token0_candles_7d else [],
                "token1_candles_7d_minute": token1_candles_7d if token1_candles_7d else [],
                # Добавляем исторические данные о торгах
                "pool_7d_historical_trades_list": historical_trades_data_list if historical_trades_data_list else [],
                "pool_7d_historical_summary": {
                    "records_count": total_hist_records,
                    "total_trades_count": str(sum_hist_trades_count),
                    "total_volume_base_token": str(sum_hist_volume_base),
                    "base_token_symbol": base_token_symbol_for_hist,
                    "total_usd_volume": str(sum_hist_usd_volume),
                    "total_buy_volume_base_token": str(sum_hist_buy_volume_base),
                    "total_sell_volume_base_token": str(sum_hist_sell_volume_base)
                }
            }
            
            # Добавляем данные текущего пула в общий список
            detailed_report_data_for_primary_pools.append(pool_specific_data)
        
        # Шаг 4: Группируем позиции по пулам для удобства анализа (сохраняем для обратной совместимости)
        pools_data = {}
        
        for position in all_wallet_positions:
            pool_id = position["pool_id"]
            
            if pool_id not in pools_data:
                pools_data[pool_id] = {
                    "pool_id": pool_id,
                    "pool_name": position["pool_name"],
                    "positions": [],
                    "total_usd_value": Decimal(0),
                    "in_range_positions": 0,
                    "out_of_range_positions": 0,
                    "unknown_range_positions": 0
                }
            
            # Добавляем позицию в соответствующий пул
            pools_data[pool_id]["positions"].append(position)
            
            # Обновляем статистику пула
            position_value_usd = Decimal(position["position_value_usd"])
            pools_data[pool_id]["total_usd_value"] += position_value_usd
            
            if position["in_range"] is True:
                pools_data[pool_id]["in_range_positions"] += 1
            elif position["in_range"] is False:
                pools_data[pool_id]["out_of_range_positions"] += 1
            else:
                pools_data[pool_id]["unknown_range_positions"] += 1
        
        # Подготовка данных для секции "ДРУГИЕ ПУЛЫ"
        other_pools_data_aggregated = {}
        for position in all_wallet_positions:
            pool_id = position["pool_id"]
            if pool_id not in PRIMARY_TARGET_POOL_IDS:
                if pool_id not in other_pools_data_aggregated:
                    other_pools_data_aggregated[pool_id] = {
                        "pool_id": pool_id,
                        "pool_name": position["pool_name"],
                        "positions": [],
                        "total_usd_value": Decimal(0)
                    }
                other_pools_data_aggregated[pool_id]["positions"].append(position)
                other_pools_data_aggregated[pool_id]["total_usd_value"] += Decimal(position["position_value_usd"])
        
        # Шаг 5: Формируем итоговые статистические данные
        total_value_usd = sum(Decimal(pos["position_value_usd"]) for pos in all_wallet_positions)
        
        in_range_positions = sum(1 for pos in all_wallet_positions if pos["in_range"] is True)
        out_of_range_positions = sum(1 for pos in all_wallet_positions if pos["in_range"] is False)
        unknown_range_positions = sum(1 for pos in all_wallet_positions if pos["in_range"] is None)
        
        end_time = datetime.now()
        execution_time = (end_time - start_time).total_seconds()
        
        # Шаг 6: Подготовка итогового отчета
        final_output = {
            "analysis_timestamp": start_time.isoformat(),
            "execution_time_seconds": execution_time,
            "wallet_address": TARGET_WALLET_ADDRESS,
            "primary_pools_analysis": detailed_report_data_for_primary_pools,
            "other_pools_summary": list(other_pools_data_aggregated.values()),
            "all_positions": all_wallet_positions,
            "stats": {
                "total_pools": len(pools_data),
                "total_positions": len(all_wallet_positions),
                "primary_pools_count": len(detailed_report_data_for_primary_pools),
                "total_value_usd": total_value_usd,
                "in_range_positions": in_range_positions,
                "out_of_range_positions": out_of_range_positions,
                "unknown_range_positions": unknown_range_positions,
            }
        }
        
        # JSON файл больше не генерируется, оставляем только текстовый отчет
        # Сохраняем имя переменной report_filename для совместимости со старым кодом
        report_timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_filename = f"raydium_pool_report_{report_timestamp}.json" # Не используется, но сохраняем для обратной совместимости
        
        # Генерация текстового отчета с timestamp
        try:
            # Создаем имя файла с timestamp, используя тот же timestamp, что был для JSON
            txt_report_filename = f"raydium_pool_report_{report_timestamp}.txt"
            
            with open(txt_report_filename, "w", encoding="utf-8") as f:
                # Заголовок отчета
                f.write("=====================================================\n")
                f.write("ОТЧЕТ ПО RAYDIUM CLMM ПУЛУ - АНАЛИТИЧЕСКИЙ ОБЗОР\n")
                f.write("=====================================================\n\n")
                # Moved wallet address to the beginning of the report (global section)
                f.write(f"Анализируемый кошелек: {TARGET_WALLET_ADDRESS}\n\n")

                # Для каждого основного пула выводим детальную информацию
                for pool_data in detailed_report_data_for_primary_pools:
                    f.write(f"--- АНАЛИЗ ПУЛА: {pool_data['name']} ({pool_data['id']}) ---\n\n")

                    # ОСНОВНАЯ ИНФОРМАЦИЯ О ПУЛЕ
                    f.write("ОСНОВНАЯ ИНФОРМАЦИЯ О ПУЛЕ\n")
                    f.write("-----------------------------------------------------\n")
                    f.write(f"ID Пула: {pool_data['id']}\n")
                    token_a_symbol = pool_data['mintA']['symbol']
                    token_b_symbol = pool_data['mintB']['symbol']
                    token_a_address = pool_data['mintA']['address']
                    token_b_address = pool_data['mintB']['address']
                    
                    # Try to get descriptive full names if available
                    token_a_name = pool_data['mintA'].get('name', token_a_symbol)
                    token_b_name = pool_data['mintB'].get('name', token_b_symbol)
                    
                    # If name is empty or "Unknown Token", use symbol instead
                    if not token_a_name or token_a_name == "Unknown Token":
                        token_a_name = token_a_symbol
                    if not token_b_name or token_b_name == "Unknown Token":
                        token_b_name = token_b_symbol
                    
                    f.write(f"Пара токенов: {token_a_symbol}/{token_b_symbol} ({token_a_address} / {token_b_address})\n")
                    f.write(f"Полные имена: {token_a_name} ({token_a_symbol}) / {token_b_name} ({token_b_symbol})\n")
                    f.write("Тип пула: Concentrated Liquidity Market Maker (CLMM)\n")
                    f.write("Платформа: Raydium V3\n\n")

                    # ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ
                    f.write("ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ\n")
                    f.write("-----------------------------------------------------\n")
                    current_price = pool_data['price']
                    # Improved formatting for fee rate
                    f.write(f"Текущая цена: {current_price} {token_b_symbol}/{token_a_symbol}\n")
                    fee_rate = pool_data['feeRate']
                    f.write(f"Fee rate: {fee_rate*100:.2f}% ({fee_rate})\n")
                    f.write(f"Decimals токенов: {token_a_symbol} (9), {token_b_symbol} (6)\n")
                    f.write("Конфигурация: Стандартная Raydium CLMM\n\n")

                    # ЛИКВИДНОСТЬ И ОБЪЕМЫ
                    total_usd_value = pool_data['total_usd_value']
                    pool_tvl_usd = Decimal(pool_data.get('pool_tvl_usd', '0'))
                    pool_24h_volume_usd = Decimal(pool_data.get('pool_24h_volume_usd', '0'))
                    
                    # Получаем недельный объем (сумма за 7 дней)
                    weekly_volume_usd = sum(Decimal(day.get('daily_usd_volume', '0')) for day in pool_data.get('pool_7d_daily_volumes', []))
                    
                    f.write("ЛИКВИДНОСТЬ И ОБЪЕМЫ\n")
                    f.write("-----------------------------------------------------\n")
                    # Improved number formatting with comma thousands separators and two decimal places
                    f.write(f"Общая стоимость позиций кошелька: ${total_usd_value:,.2f}\n")
                    f.write(f"Общая ликвидность пула (TVL): ${pool_tvl_usd:,.2f}\n")
                    f.write(f"Объем торгов за 24 часа: ${pool_24h_volume_usd:,.2f}\n")
                    f.write(f"Объем торгов за 7 дней: ${weekly_volume_usd:,.2f}\n")
                    
                    # Объемы по дням
                    if pool_data.get('pool_7d_daily_volumes'):
                        f.write("Объемы торгов по дням (последние 7 дней):\n")
                        for day_data in pool_data.get('pool_7d_daily_volumes', []):
                            date = day_data.get('date', 'Unknown')
                            daily_usd_volume = Decimal(day_data.get('daily_usd_volume', '0'))
                            f.write(f"  - {date}: ${daily_usd_volume:,.2f}\n")
                    f.write("\n")
                    
                    # Добавляем сводку по истории торгов
                    hist_summary = pool_data.get('pool_7d_historical_summary', {})
                    if hist_summary:
                        f.write("Сводка по истории торгов (7 дней, BitQuery):\n")
                        f.write(f"  - Всего записей (агрегированных): {hist_summary.get('records_count', 0)}\n")
                        f.write(f"  - Общее кол-во сделок: {hist_summary.get('total_trades_count', '0')}\n")
                        
                        base_symbol = hist_summary.get('base_token_symbol', 'N/A')
                        total_volume_base = Decimal(hist_summary.get('total_volume_base_token', '0'))
                        f.write(f"  - Общий объем ({base_symbol}): {total_volume_base:,.6f}\n")
                        
                        total_usd_volume = Decimal(hist_summary.get('total_usd_volume', '0'))
                        f.write(f"  - Общий объем (USD): ${total_usd_volume:,.2f}\n")
                        
                        buy_volume = Decimal(hist_summary.get('total_buy_volume_base_token', '0'))
                        f.write(f"  - Общий объем покупок ({base_symbol}): {buy_volume:,.6f}\n")
                        
                        sell_volume = Decimal(hist_summary.get('total_sell_volume_base_token', '0'))
                        f.write(f"  - Общий объем продаж ({base_symbol}): {sell_volume:,.6f}\n")
                        f.write("\n")

                    # Removed "Данные о минутных свечах" section as requested

                    # ПОЗИЦИИ В ПУЛЕ
                    positions = pool_data['positions']
                    in_range_count = pool_data['in_range_positions']
                    out_of_range_count = pool_data['out_of_range_positions']
                    f.write("ПОЗИЦИИ В ПУЛЕ\n")
                    f.write("-----------------------------------------------------\n")
                    # Removed wallet address from here (moved to the top of the report)
                    f.write(f"Активные позиции: {len(positions)} позиции в пуле\n")
                    f.write(f"Общая стоимость позиций: ~${total_usd_value:,.2f}\n")
                    
                    # Conditionally show out of range positions only if > 0
                    if out_of_range_count > 0:
                        f.write(f"Позиции вне диапазона: {out_of_range_count}\n")
                    
                    f.write(f"Позиции в диапазоне: {in_range_count}\n\n")

                    # Детали позиций
                    f.write("Детали позиций:\n")
                    for i, position in enumerate(positions, 1):
                        position_value_usd = Decimal(position['position_value_usd'])
                        position_share_percent = Decimal(position.get('position_liquidity_share_percent', '0'))
                        
                        f.write(f"{i}. NFT: {position['position_mint']}\n")
                        f.write(f"   Стоимость: ${position_value_usd:,.2f}\n")
                        f.write(f"   Доля ликвидности в пуле: {position_share_percent:.4f}%\n")
                        
                        # Improved token amount formatting
                        try:
                            amount0 = Decimal(position['amount0'])
                            amount1 = Decimal(position['amount1'])
                            f.write(f"   Токены: {amount0:,.8f} {token_a_symbol}, {amount1:,.8f} {token_b_symbol}\n")
                        except:
                            f.write(f"   Токены: {position['amount0']} {token_a_symbol}, {position['amount1']} {token_b_symbol}\n")
                        
                        # Improved pending yield formatting
                        total_yield_usd_str = position.get('total_pending_yield_usd_str', '0.00')
                        try:
                            # Convert to Decimal for better formatting, removing any non-numeric characters
                            clean_yield_str = total_yield_usd_str.replace('~', '').replace('$', '')
                            total_yield_usd = Decimal(clean_yield_str)
                            f.write(f"   Общий Pending Yield: ~${total_yield_usd:,.2f}\n")
                        except:
                            f.write(f"   Общий Pending Yield: ~{total_yield_usd_str}\n")
                        
                        # Показываем источник данных о комиссиях
                        fees_data_source = position.get('fees_data_source', 'N/A')
                        source_display = {
                            'json_uri': 'Raydium API (json_uri)',
                            'onchain_calculation': 'Расчет на основе блокчейн-данных',
                            'none': 'Нет данных'
                        }.get(fees_data_source, fees_data_source)
                        f.write(f"     Источник данных по комиссиям: {source_display}\n")
                        
                        # Показываем детали наград, если они есть
                        rewards_details = position.get('pending_rewards_details', [])
                        if rewards_details:
                            f.write("     Невостребованные награды:\n")
                            for reward_detail in rewards_details:
                                f.write(f"       - {reward_detail['amount']} {reward_detail['symbol']} (${reward_detail['usd_value']})\n")
                                
                        # Показываем детали торговых комиссий (можно опционально скрыть)
                        try:
                            unclaimed_fees_str = position.get('unclaimed_fees_total_usd_str', '0')
                            # Remove non-numeric characters
                            clean_fees_str = unclaimed_fees_str.replace('~', '').replace('$', '').replace(',', '')
                            unclaimed_fees_usd = Decimal(clean_fees_str)
                            if unclaimed_fees_usd > 0 or not rewards_details:
                                f.write(f"     Невостребованные торговые комиссии: ~${unclaimed_fees_usd:,.2f}\n") 
                        except:
                            if position.get('unclaimed_fees_total_usd_str'):
                                f.write(f"     Невостребованные торговые комиссии: ~{position.get('unclaimed_fees_total_usd_str')}\n")
                            
                        in_range_status = "В диапазоне" if position['in_range'] is True else "Вне диапазона" if position['in_range'] is False else "Статус неизвестен"
                        f.write(f"   Статус: {in_range_status}\n\n")

                    f.write("\n")

                # ДРУГИЕ ПУЛЫ
                other_pools = list(other_pools_data_aggregated.values())
                total_other_positions = sum(len(pool['positions']) for pool in other_pools)
                total_other_value = sum(pool['total_usd_value'] for pool in other_pools)

                f.write("ДРУГИЕ ПУЛЫ\n")
                f.write("-----------------------------------------------------\n")
                f.write(f"Всего найдено позиций: {total_other_positions} (в {len(other_pools)} разных пулах)\n")
                f.write(f"Общая стоимость всех позиций: ~${total_other_value:,.2f}\n")
                if other_pools:
                    f.write("Другие пулы:\n")
                    for pool in other_pools:
                        f.write(f"- {pool['pool_name']}: {len(pool['positions'])} позиций, ${pool['total_usd_value']:,.2f}\n")
                f.write("\n")

                # ОБЩАЯ СТАТИСТИКА
                all_positions_value = total_value_usd
                f.write("ОБЩАЯ СТАТИСТИКА ПО ВСЕМ ПОЗИЦИЯМ КОШЕЛЬКА\n")
                f.write("-----------------------------------------------------\n")
                f.write(f"Всего CLMM позиций: {len(all_wallet_positions)}\n")
                f.write(f"Общая стоимость всех позиций: ${all_positions_value:,.2f}\n\n")

                # Подвал отчета - переписываю для однозначного формирования даты
                current_datetime = datetime.now()
                formatted_date = current_datetime.strftime('%d.%m.%Y %H:%M')
                f.write("-----------------------------------------------------\n")
                f.write("* Отчет сгенерирован с использованием pool_analyzer.py (Расширенная версия)\n")
                f.write("* Данные получены через: Helius RPC, Raydium API, BitQuery API, positions.py\n")
                f.write(f"* Дата формирования: {formatted_date}\n")
                f.write("===================================================== \n")

            print(f"[INFO] Text report saved to: {txt_report_filename}")
        except Exception as e:
            print(f"[ERROR] Failed to generate text report: {e}")
            traceback.print_exc()
        
        # Выводим основную информацию в консоль
        print(f"{'=' * 50}")
        print(f"Analysis completed at: {end_time.isoformat()}")
        print(f"Execution time: {execution_time:.2f} seconds")
        print(f"Found {len(all_wallet_positions)} total positions in {len(pools_data)} pools")
        print(f"Primary pools analyzed: {len(detailed_report_data_for_primary_pools)}")
        print(f"Total value USD: ${total_value_usd}")
        print(f"Positions in range: {in_range_positions}, out of range: {out_of_range_positions}, unknown range: {unknown_range_positions}")
        print(f"Report saved to: {txt_report_filename}")
        print(f"{'=' * 50}")

# Точка входа
if __name__ == "__main__":
    asyncio.run(main()) 