import asyncio
import base64
import json
import math
import traceback  # Добавляем для логирования ошибок
from typing import List, Dict, Optional, Set, Any
from decimal import Decimal, getcontext, ROUND_DOWN # Добавляем Decimal и ROUND_DOWN

import httpx
from construct import Struct, Int8ul, Int16ul, Int32sl, Int32ul, Int64ul, Bytes, Array, Pass, Adapter
from solders.pubkey import Pubkey
import os
from dotenv import load_dotenv  # Добавляем импорт load_dotenv

# Устанавливаем точность для Decimal
getcontext().prec = 78 # Достаточно для u256

# --- Хелпер для PublicKey ---
class PubkeyAdapter(Adapter):
    def _decode(self, obj, context, path):
        return Pubkey(obj)
    def _encode(self, obj, context, path):
        return bytes(obj)
construct_pubkey = PubkeyAdapter(Bytes(32))
# --- Конец хелпера ---

# --- Layouts (из IDL/SDK) ---
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
# --- Конец Layouts ---

# --- Константы и настройки --- 
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
MOCK_OUTPUT_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'wallet_positions.json')

# Нужен для фильтрации по имени, если update_authority не найден/не совпадает
RAYDIUM_POSITION_NAME = "Raydium Concentrated Liquidity" 
# Добавляем математические константы
Q64 = Decimal(2**64)
# Используем Decimal для SQRT_1_0001 для большей точности при возведении в степень
SQRT_1_0001 = Decimal('1.0001').sqrt() 
MIN_TICK = -887272
MAX_TICK = 887272
MAX_U128 = (1 << 128) - 1

# Трешхолды для рекомендаций 
WIDE_RANGE_THRESHOLD_TICKS = 5000  # Если диапазон тиков больше этого значения, рекомендуем сузить диапазон
LOW_TVL_THRESHOLD_USD = 500  # Если TVL позиции меньше этого значения, рекомендуем добавить ликвидность

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
    "spinezMPKxkBpf4Q9xET2587fehM3LuKe4xoAoXtSjR": "SPINE",
    "GJtJuWD9qYcCkrwMBmtY1tpapV1sKfB2zUv9Q4aqpump": "RIF",
    "FvgqHMfL9yn39V79huDPy3YUNDoYJpuLWng2JfmQpump": "URO"
}
# --- Конец Констант ---

# --- Новые математические хелперы ---
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
    WARNING: Formulas require careful validation.
    """
    if tick_lower >= tick_upper:
        return {"amount0_raw": Decimal(0), "amount1_raw": Decimal(0)}

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

        amount0_raw = Decimal(0)
        amount1_raw = Decimal(0)

        if sp_c <= sa:
            # Price below range -> only token0
            if sa > 0 and sb > 0:
                amount0_raw = L * (sb - sa) * Q64 / (sa * sb)
        elif sp_c >= sb:
            # Price above range -> only token1
            amount1_raw = L * (sb - sa) / Q64
        else: # Price within range (sa < sp_c < sb)
            if sp_c > 0 and sb > 0:
                 amount0_raw = L * (sb - sp_c) * Q64 / (sp_c * sb)
            amount1_raw = L * (sp_c - sa) / Q64

        # Ensure non-negative results
        amount0_raw = max(Decimal(0), amount0_raw)
        amount1_raw = max(Decimal(0), amount1_raw)

        return {"amount0_raw": amount0_raw, "amount1_raw": amount1_raw}

    except Exception as e:
        print(f"Error in calculate_token_amounts (L={liquidity}, sp={sqrt_price_x64_current}, tl={tick_lower}, tu={tick_upper}): {e}")
        return {"amount0_raw": Decimal(0), "amount1_raw": Decimal(0)}

def calculate_price_from_sqrt_price_x64(
    sqrt_price_x64_bytes: bytes, 
    decimals0: int, 
    decimals1: int
) -> Optional[Decimal]:
    """ Calculates the price of token1 in terms of token0 from sqrtPriceX64."""
    try:
        sqrt_price_x64_int = int.from_bytes(sqrt_price_x64_bytes, 'little')
        sqrt_price_x64_decimal = Decimal(sqrt_price_x64_int)
        
        # price_ratio = (sqrtPriceX64 / 2**64)**2
        price_ratio = (sqrt_price_x64_decimal / Q64)**2
        
        # ИСПРАВЛЕНИЕ: правильная формула для decimals
        # Цена token1 в единицах token0 с учетом decimals
        decimal_diff_factor = Decimal(10)**(decimals0 - decimals1)
        price = price_ratio * decimal_diff_factor
        return price
    except Exception as e:
        print(f"Error calculating price from sqrtPriceX64: {e}")
        return None

def get_price_from_tick(tick: int, decimals0: int = 9, decimals1: int = 9) -> Decimal:
    """
    Конвертирует tick в цену для Solana/Raydium (аналог функции из Ethereum)
    
    Args:
        tick: Tick value
        decimals0: Decimal places token0
        decimals1: Decimal places token1
        
    Returns:
        Цена token1 в единицах token0 с правильными decimals
    """
    try:
        sqrt_price_x64 = tick_to_sqrt_price_x64(tick)
        sqrt_price_x64_decimal = Decimal(sqrt_price_x64)
        
        # price_ratio = (sqrtPriceX64 / 2**64)**2 
        price_ratio = (sqrt_price_x64_decimal / Q64)**2
        
        # ИСПРАВЛЕНИЕ: правильная формула для decimals
        # Цена token1 в единицах token0 с учетом decimals
        decimal_diff_factor = Decimal(10)**(decimals0 - decimals1)
        price = price_ratio * decimal_diff_factor
        
        return price
    except Exception as e:
        print(f"Error getting price from tick {tick}: {e}")
        return Decimal(0)

def calculate_price_range(tick_lower: int, tick_upper: int, decimals0: int = 9, decimals1: int = 9) -> Dict[str, Decimal]:
    """
    Рассчитывает диапазон цен для позиции Solana/Raydium
    
    Args:
        tick_lower: Нижний tick
        tick_upper: Верхний tick  
        decimals0: Decimal places token0
        decimals1: Decimal places token1
        
    Returns:
        Dict с price_lower и price_upper
    """
    try:
        price_lower = get_price_from_tick(tick_lower, decimals0, decimals1)
        price_upper = get_price_from_tick(tick_upper, decimals0, decimals1)
        
        return {
            "price_lower": price_lower,
            "price_upper": price_upper,
            "range_width": price_upper - price_lower
        }
        
    except Exception as e:
        print(f"Error calculating price range: {e}")
        return {"price_lower": Decimal(0), "price_upper": Decimal(0), "range_width": Decimal(0)}

# --- Хелперы для API и парсинга ---

async def get_account_info_via_httpx(rpc_url: str, account_pubkey_str: str) -> Optional[Dict[str, Any]]:
    """Fetches account info using raw JSON RPC call via httpx."""
    if not rpc_url: return None
    try: Pubkey.from_string(account_pubkey_str)
    except ValueError: return None

    payload = {
        "jsonrpc": "2.0", "id": f"acc-{account_pubkey_str[:5]}", "method": "getAccountInfo",
        "params": [account_pubkey_str, {"encoding": "base64"}]
    }
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(rpc_url, json=payload, timeout=30.0)
            response.raise_for_status()
            data = response.json()
            if "error" in data: return None
            result = data.get('result', {})
            return result.get('value') if result and result.get('value') else None
    except Exception:
        return None # Возвращаем None при любых ошибках

def parse_account_data(data_base64: str, layout: Struct) -> Optional[Any]:
    """Generic parser for account data using a construct layout."""
    try:
        data_bytes = base64.b64decode(data_base64)
        if len(data_bytes) < 8: return None # Need at least discriminator
        return layout.parse(data_bytes[8:]) # Skip 8-byte discriminator
    except Exception:
        return None

async def get_fee_rate_from_config(config_id: str, rpc_url: str) -> float:
    """ Fetches AmmConfig account, parses it, and returns the trade fee rate."""
    account_info = await get_account_info_via_httpx(rpc_url, config_id)
    if not account_info:
        print(f"Warning: Could not fetch AmmConfig account {config_id}")
        return 0.0 # Возвращаем 0 если не нашли аккаунт

    raw_data_b64 = account_info.get('data')
    if isinstance(raw_data_b64, list):
        raw_data_b64 = raw_data_b64[0]
        
    if not raw_data_b64 or not isinstance(raw_data_b64, str):
        print(f"Warning: No data found in AmmConfig account {config_id}")
        return 0.0
        
    parsed_config = parse_account_data(raw_data_b64, AMM_CONFIG_LAYOUT)
    if not parsed_config:
        print(f"Warning: Failed to parse AmmConfig account {config_id}")
        return 0.0
        
    try:
        # tradeFeeRate хранится как u32, делим на 1,000,000 для получения доли
        trade_fee_ppm = parsed_config.tradeFeeRate
        fee_rate = float(trade_fee_ppm) / 1_000_000.0
        print(f"[Debug] Fetched fee rate {fee_rate:.6f} for config {config_id}")
        return fee_rate
    except Exception as e:
        print(f"Error extracting fee rate from parsed AmmConfig {config_id}: {e}")
        return 0.0

async def fetch_nfts_via_rpc(rpc_url: str, wallet: str) -> Optional[List[Dict[str, Any]]]:
    """Fetches assets (including NFTs) for a wallet using Helius RPC getAssetsByOwner."""
    if not rpc_url: return None
    payload = {
        "jsonrpc": "2.0", "id": f"assets-{wallet[:5]}", "method": "getAssetsByOwner",
        "params": {"ownerAddress": wallet, "page": 1, "limit": 1000}
    }
    all_assets = []
    current_page = 1
    try:
        async with httpx.AsyncClient() as client:
            while True:
                payload["params"]["page"] = current_page
                response = await client.post(rpc_url, json=payload, timeout=60.0)
                response.raise_for_status()
                data = response.json()
                if "error" in data: return None
                result = data.get('result', {})
                assets = result.get('items', [])
                all_assets.extend(assets)
                total_items = result.get('total')
                limit = result.get('limit')
                if len(all_assets) >= total_items or len(assets) < limit: break
                current_page += 1
                await asyncio.sleep(0.1)
        return all_assets
    except Exception:
        return None

def filter_raydium_clmm_assets(assets: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filters assets to find potential Raydium CLMM NFTs by name."""
    clmm_assets = []
    if not assets: return clmm_assets
    for asset in assets:
        name = asset.get('content', {}).get('metadata', {}).get('name', '')
        # Основной метод - проверка имени, т.к. update_authority может отличаться
        if RAYDIUM_POSITION_NAME in name:
            clmm_assets.append(asset)
    return clmm_assets

# --- Хелпер для получения метаданных токенов ---
async def fetch_token_metadata_bulk(mint_addresses: List[str], api_key: str) -> Dict[str, Dict[str, Any]]:
    """Fetches token metadata for multiple mints using Helius Token Metadata API."""
    if not mint_addresses or not api_key:
        return {}

    url = f"https://api.helius.xyz/v0/token-metadata?api-key={api_key}"
    payload = {"mintAccounts": mint_addresses}
    metadata_map: Dict[str, Dict[str, Any]] = {}

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=30.0)
            response.raise_for_status() 
            results = response.json()
 
            if not isinstance(results, list):
                print(f"Warning: Unexpected response format from Helius Token Metadata API: {results}")
                return {}
 
            for item in results:
                account = item.get('account') # Это адрес минта
                # Данные могут быть в onChainMetadata или legacyMetadata
                # В v0 API поле offChainMetadata обычно пустое для fungible токенов
                metadata_container = None
                if item.get('onChainMetadata') and item['onChainMetadata'].get('metadata'):
                    metadata_container = item['onChainMetadata']['metadata']
                elif item.get('legacyMetadata'): # Проверяем legacy для старых токенов
                     metadata_container = item['legacyMetadata']
                     
                if account and metadata_container:
                    # Извлекаем символ и имя
                    # В onChainMetadata V0 символ и имя находятся внутри 'data'
                    data_field = metadata_container.get('data', metadata_container) # Используем сам контейнер, если нет 'data' (для legacy)
                    symbol = data_field.get("symbol", "???")
                    name = data_field.get("name", "Unknown Token")
                    
                    # Извлекаем децималы (новое)
                    decimals = item.get('decimals', None) # Децималы обычно находятся на верхнем уровне ответа для минта
                    if decimals is None and item.get('onChainMetadata'): # Проверяем внутри onChainMetadata, если не нашли
                        decimals = item['onChainMetadata'].get('decimals', None)
                 
                    metadata_map[account] = {"symbol": symbol, "name": name, "decimals": decimals} # Добавляем децималы
 
    except httpx.HTTPStatusError as e:
        print(f"HTTP error fetching token metadata: {e.response.status_code} - {e.response.text}")
    except Exception as e:
        print(f"Error fetching or processing token metadata: {e}")
        
    return metadata_map
# --- Конец хелпера ---    

# --- Хелпер для получения цен токенов (Обновленный - GeckoTerminal API) ---
async def fetch_token_price(mint_address: str) -> Decimal:
    """Fetches USD price for a single Solana mint address using GeckoTerminal API.
       Returns price as Decimal. Returns Decimal(0) if not found or error."""
    if not mint_address:
        return Decimal(0)
    
    token_symbol = TOKEN_SYMBOL_MAP.get(mint_address, "Unknown")
    
    print(f"[Debug] Fetching GeckoTerminal price for: {mint_address} ({token_symbol})")
    
    price = Decimal(0) # Default to 0
    
    try:
        # GeckoTerminal API URL для получения цены токена на Solana
        url = f"https://api.geckoterminal.com/api/v2/networks/solana/tokens/{mint_address}"
        print(f"[Debug] Request URL: {url}")
        
        async with httpx.AsyncClient() as client:
            # Используем таймаут в 15 секунд
            response = await client.get(url, timeout=15.0)
            
            if response.status_code == 200:
                try:
                    gt_data = response.json()
                    
                    # Структура данных GeckoTerminal: {"data": {"attributes": {"price_usd": price}}}
                    if "data" in gt_data and "attributes" in gt_data["data"]:
                        usd_price = gt_data["data"]["attributes"].get("price_usd")
                        if usd_price is not None:
                            try:
                                price = Decimal(str(usd_price))
                                print(f"[Success] Found price: ${price} for {token_symbol}")
                            except Exception as conv_err:
                                print(f"[Warning] Could not convert GeckoTerminal price '{usd_price}' for {token_symbol} to Decimal: {conv_err}")
                                # Price remains Decimal(0)
                        else:
                            print(f"[Warning] No USD price found in GeckoTerminal response for {token_symbol}")
                    else:
                        print(f"[Warning] Token {token_symbol} ({mint_address}) not found or invalid response format from GeckoTerminal")
                        if gt_data:
                            print(f"[Debug] Response keys: {gt_data.keys()}")
                except Exception as json_err:
                    print(f"[Error] Failed to parse GeckoTerminal JSON response: {json_err}")
                    try:
                        print(f"[Debug] Raw response text: {response.text[:200]}...")
                    except:
                        pass
                        
            elif response.status_code == 429:
                print(f"[Warning] GeckoTerminal rate limit hit while fetching {token_symbol}. Waiting 30 seconds and retrying...")
                # Попытка повтора после ожидания для rate limit
                await asyncio.sleep(30)
                try:
                    async with httpx.AsyncClient() as retry_client:
                        retry_response = await retry_client.get(url, timeout=15.0)
                        if retry_response.status_code == 200:
                            try:
                                retry_data = retry_response.json()
                                if "data" in retry_data and "attributes" in retry_data["data"]:
                                    usd_price = retry_data["data"]["attributes"].get("price_usd")
                                    if usd_price is not None:
                                        price = Decimal(str(usd_price))
                                        print(f"[Success] Found price after retry: ${price} for {token_symbol}")
                            except Exception as retry_err:
                                print(f"[Error] Failed on retry for {token_symbol}: {retry_err}")
                except Exception as retry_ex:
                    print(f"[Error] Exception during retry for {token_symbol}: {retry_ex}")
            
            elif response.status_code == 404:
                print(f"[Warning] Token {token_symbol} ({mint_address}) not found in GeckoTerminal (404)")
            
            elif response.status_code >= 400:
                print(f"[Warning] GeckoTerminal API request failed for {token_symbol} with status {response.status_code}.")
                try:
                    print(f"[Debug] Response text: {response.text[:200]}...")
                except:
                    pass

    except httpx.TimeoutException:
        print(f"[Error] GeckoTerminal API request timed out for {token_symbol}.")
    except Exception as e:
        print(f"[Error] Unexpected error fetching GeckoTerminal price for {token_symbol}: {e}")
    
            # Manual price overrides for critical tokens only if API fails
        if price == Decimal(0):
            # As a last resort, use fallback static values ONLY for critical tokens
            critical_tokens = {"BIO", "CURES", "QBIO", "SOL", "MYCO"}
        
        if token_symbol in critical_tokens:
            if token_symbol == "BIO":
                price = Decimal("0.059183")  # Updated fallback price
                print(f"[FALLBACK WARN] Using static fallback price for {token_symbol}: ${price}")
            elif token_symbol == "CURES":
                price = Decimal("0.02269721")  # Updated fallback price
                print(f"[FALLBACK WARN] Using static fallback price for {token_symbol}: ${price}")
            elif token_symbol == "QBIO":
                price = Decimal("0.00484962")  # Updated fallback price
                print(f"[FALLBACK WARN] Using static fallback price for {token_symbol}: ${price}")
            elif token_symbol == "SOL":
                price = Decimal("147.12")  # Updated fallback price
                print(f"[FALLBACK WARN] Using static fallback price for {token_symbol}: ${price}")
        else:
            # For non-critical tokens, return 0 if no price from API
            print(f"[Info] No fallback price available for {token_symbol}, returning 0")
    
    return price
# --- Конец хелпера ---

# --- Хелпер для получения данных пула с Raydium API ---
async def fetch_pool_details_from_raydium_api(pool_id: str) -> Optional[Dict[str, Any]]:
    """
    Получает данные о пуле (объем, TVL) из Raydium API V3.
    
    Args:
        pool_id: ID пула (mint адрес пула)
        
    Returns:
        Dictionary с ключами 'daily_volume_usd' и 'pool_tvl_usd' или None при ошибке
    """
    if not pool_id:
        print(f"Warning: fetch_pool_details_from_raydium_api called with empty pool_id")
        return None
    
    url = f"https://api-v3.raydium.io/pools/info/mint/{pool_id}"
    print(f"[Debug] Fetching pool details from Raydium API for pool: {pool_id}")
    
    # Максимальное количество попыток запроса
    max_attempts = 3
    retry_delay = 1.0  # Начальная задержка между попытками в секундах
    
    for attempt in range(max_attempts):
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, timeout=10.0)
                
                if response.status_code == 200:
                    try:
                        pool_data = response.json()
                        
                        # Check if we have a valid JSON response
                        if not isinstance(pool_data, dict):
                            print(f"[Error] Invalid response format for pool {pool_id} - expected dict, got {type(pool_data)}")
                            # Попробуем еще раз, если это не последняя попытка
                            if attempt < max_attempts - 1:
                                await asyncio.sleep(retry_delay * (attempt + 1))
                                continue
                            return None
                        
                        # Extract volume and TVL values with proper error checking
                        daily_volume_usd = 0
                        pool_tvl_usd = 0
                        
                        if 'day' in pool_data and isinstance(pool_data['day'], dict):
                            try:
                                daily_volume_usd = float(pool_data['day'].get('volume', 0))
                            except (ValueError, TypeError) as e:
                                print(f"[Error] Invalid volume value for pool {pool_id}: {e}")
                        
                        if 'tvl' in pool_data:
                            try:
                                pool_tvl_usd = float(pool_data.get('tvl', 0))
                            except (ValueError, TypeError) as e:
                                print(f"[Error] Invalid TVL value for pool {pool_id}: {e}")
                        
                        # Ensure non-negative values
                        daily_volume_usd = max(0, daily_volume_usd)
                        pool_tvl_usd = max(0, pool_tvl_usd)
                        
                        # Проверим, не слишком ли малы значения, что может указывать на ошибку API
                        if daily_volume_usd < 0.01 and pool_tvl_usd < 0.01:
                            print(f"[Warning] Suspiciously low values returned for pool {pool_id}: volume={daily_volume_usd}, tvl={pool_tvl_usd}")
                            # Но все равно возвращаем то, что получили
                        
                        print(f"[Debug] Pool {pool_id}: daily_volume_usd=${daily_volume_usd}, pool_tvl_usd=${pool_tvl_usd}")
                        
                        return {
                            'daily_volume_usd': daily_volume_usd,
                            'pool_tvl_usd': pool_tvl_usd
                        }
                    except Exception as parse_error:
                        print(f"[Error] Failed to parse response data for pool {pool_id}: {parse_error}")
                        if attempt < max_attempts - 1:
                            await asyncio.sleep(retry_delay * (attempt + 1))
                            continue
                        return None
                elif response.status_code == 404:
                    print(f"[Debug] Pool {pool_id} not found in Raydium API (404)")
                    # 404 означает, что пул не найден - тут повторные попытки не помогут
                    return None
                elif response.status_code == 429:
                    # Rate limit, нужно подождать дольше
                    print(f"[Warning] Rate limit (429) hit for Raydium API. Pool: {pool_id}, attempt: {attempt+1}")
                    if attempt < max_attempts - 1:
                        # Экспоненциальная задержка при повторе для rate limit
                        await asyncio.sleep(retry_delay * (2 ** attempt))
                        continue
                    return None
                else:
                    print(f"[Debug] Failed to fetch pool data for {pool_id}. Status: {response.status_code}")
                    try:
                        error_body = response.text[:200]  # Log a portion of the error response
                        print(f"[Debug] Error response: {error_body}")
                    except:
                        pass
                    
                    # Попробуем еще раз, если это не последняя попытка
                    if attempt < max_attempts - 1:
                        await asyncio.sleep(retry_delay * (attempt + 1))
                        continue
                    return None
                    
        except httpx.RequestError as e:
            print(f"[Error] Request error fetching pool details from Raydium API for {pool_id}: {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            return None
        except Exception as e:
            print(f"[Error] Unexpected error fetching pool details from Raydium API for {pool_id}: {e}")
            if attempt < max_attempts - 1:
                await asyncio.sleep(retry_delay * (attempt + 1))
                continue
            return None
    
    print(f"[Error] All {max_attempts} attempts to fetch pool data for {pool_id} failed")
    return None
# --- Конец хелпера ---

# --- Хелпер для получения данных из json_uri ---
async def _fetch_data_from_uri(uri: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """
    Получает данные из json_uri, обычно ассоциированного с NFT CLMM-позиции.
    
    Args:
        uri: URI JSON-данных
        client: httpx.AsyncClient для выполнения HTTP-запроса
        
    Returns:
        Dictionary с данными из URI или None, если произошла ошибка
    """
    if not uri:
        print(f"[WARN] Empty URI provided to _fetch_data_from_uri")
        return None
    
    try:
        print(f"[DEBUG] Fetching data from URI: {uri}")
        response = await client.get(uri, timeout=10.0)
        
        if response.status_code != 200:
            print(f"[ERROR] Failed to fetch data from URI. Status code: {response.status_code}")
            return None
        
        # Парсим JSON-ответ
        json_data = response.json()
        
        if not isinstance(json_data, dict):
            print(f"[ERROR] URI returned non-dictionary data: {type(json_data)}")
            return None
            
        return json_data
    
    except httpx.RequestError as e:
        print(f"[ERROR] HTTP request error for URI {uri}: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"[ERROR] JSON decode error for URI {uri}: {e}")
        return None
    except Exception as e:
        print(f"[ERROR] Unexpected error processing URI {uri}: {e}")
        traceback.print_exc()
        return None
# --- Конец хелпера ---

# --- Основная функция ---

async def get_clmm_positions(
    wallet_address: str, 
    helius_rpc_url: str, 
    helius_api_key: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Fetches and processes Raydium CLMM positions for a given wallet address.

    Args:
        wallet_address: The Solana wallet address (base58).
        helius_rpc_url: The Helius RPC URL (including API key).
        helius_api_key: The Helius API key (needed for token metadata).

    Returns:
        A list of dictionaries, each representing a CLMM position 
        with parsed details like poolId, ticks, liquidity, and in_range status.
        Returns an empty list if no positions are found or an error occurs.
    """
    
    # --- Отладка: Проверка URL ---
    if not helius_rpc_url:
        print("FATAL: Helius RPC URL is empty!")
        return []
    # --- Конец отладки ---
    
    # 1. Fetch all assets for the wallet
    all_assets = await fetch_nfts_via_rpc(helius_rpc_url, wallet_address)
    if not all_assets:
        print(f"Could not fetch assets for wallet {wallet_address}")
        return []

    # 2. Filter for potential Raydium CLMM NFTs
    clmm_assets = filter_raydium_clmm_assets(all_assets)
    if not clmm_assets:
        print(f"No potential Raydium CLMM assets found for wallet {wallet_address}")
        return []
    
    # 3. Extract Position PDAs
    position_pdas_to_fetch = []
    position_mint_map = {} # map PDA -> NFT Mint
    for asset in clmm_assets:
        mint_id = asset.get('id')
        json_uri = asset.get('content', {}).get('json_uri', '')
        if 'position?id=' in json_uri:
            try:
                pda = json_uri.split('position?id=')[1]
                if pda and mint_id:
                    # Basic validation of PDA string before adding
                    if len(pda) > 30 and len(pda) < 50 and pda.isalnum(): 
                        position_pdas_to_fetch.append(pda)
                        position_mint_map[pda] = mint_id
                    else:
                         print(f"Warning: Skipping potentially invalid PDA extracted from URI '{json_uri}': {pda}")
            except Exception as e:
                print(f"Error parsing json_uri '{json_uri}': {e}")
                continue # Ignore errors parsing URI

    if not position_pdas_to_fetch:
         print("Could not extract any valid position PDAs from CLMM assets.")
         return []

    # 4. Fetch and Parse Position PDA Account Info
    position_tasks = [get_account_info_via_httpx(helius_rpc_url, pda) for pda in position_pdas_to_fetch]
    position_results = await asyncio.gather(*position_tasks)
    
    parsed_positions = []
    pool_ids_to_fetch: Set[str] = set()
    
    for i, pda in enumerate(position_pdas_to_fetch):
        account_value = position_results[i]
        mint_nft = position_mint_map.get(pda)
        if account_value and mint_nft:
            raw_data_b64 = account_value.get('data')
            if isinstance(raw_data_b64, list): raw_data_b64 = raw_data_b64[0]
            
            if raw_data_b64 and isinstance(raw_data_b64, str):
                parsed_data = parse_account_data(raw_data_b64, POSITION_STATE_LAYOUT)
                if parsed_data:
                    try:
                        pool_id = str(parsed_data.poolId)
                        # Сохраняем байты ликвидности для последующего расчета
                        parsed_positions.append({
                            "position_mint": mint_nft,
                            "position_pda": pda,
                            "poolId": pool_id,
                            "tickLowerIndex": parsed_data.tickLowerIndex,
                            "tickUpperIndex": parsed_data.tickUpperIndex,
                            "liquidity_bytes": parsed_data.liquidity, # Храним bytes (16)
                            "tokenFeesOwedA": parsed_data.tokenFeesOwedA,  # Дополнительно сохраняем невостребованные комиссии
                            "tokenFeesOwedB": parsed_data.tokenFeesOwedB,  # Дополнительно сохраняем невостребованные комиссии
                        })
                        pool_ids_to_fetch.add(pool_id)
                    except Exception as parse_err:
                         print(f"Error processing parsed position data for PDA {pda}: {parse_err}")
    
    if not parsed_positions:
        print("No position PDAs could be successfully parsed.")
        return []

    # 5. Fetch and Parse Pool Account Info
    pool_data_map: Dict[str, Dict[str, Any]] = {}
    unique_mints: Set[str] = set() # Собираем все минты для запроса метаданных
    
    if pool_ids_to_fetch:
        pool_tasks = [get_account_info_via_httpx(helius_rpc_url, pool_id) for pool_id in pool_ids_to_fetch]
        pool_results = await asyncio.gather(*pool_tasks)
        
        # Cache for AmmConfig fee rates to avoid redundant fetches
        fee_rate_cache: Dict[str, float] = {}
        
        for i, pool_id in enumerate(pool_ids_to_fetch):
            pool_account_value = pool_results[i]
            if pool_account_value:
                pool_raw_data_b64 = pool_account_value.get('data')
                if isinstance(pool_raw_data_b64, list): pool_raw_data_b64 = pool_raw_data_b64[0]
                
                if pool_raw_data_b64 and isinstance(pool_raw_data_b64, str):
                    parsed_pool_data = parse_account_data(pool_raw_data_b64, POOL_STATE_LAYOUT)
                    if parsed_pool_data:
                        try:
                            config_id = str(parsed_pool_data.ammConfig)
                            fee_rate = fee_rate_cache.get(config_id)
                            if fee_rate is None:
                                fee_rate = await get_fee_rate_from_config(config_id, helius_rpc_url)
                                fee_rate_cache[config_id] = fee_rate # Cache the result
                            
                            mintA = str(parsed_pool_data.tokenMint0)
                            mintB = str(parsed_pool_data.tokenMint1)
                            # Добавляем минты в сет для запроса метаданных
                            unique_mints.add(mintA)
                            unique_mints.add(mintB)
                            
                            # Сохраняем информацию о наградах пула
                            pool_reward_infos = []
                            for reward_info in parsed_pool_data.rewardInfos:
                                reward_mint = str(reward_info.tokenMint)
                                pool_reward_infos.append({
                                    "mint": reward_mint,
                                    "state": reward_info.rewardState
                                })
                                if reward_info.rewardState != 0: # Состояние 0 обычно означает неактивную награду
                                    unique_mints.add(reward_mint) # Добавляем минт награды для запроса метаданных
                            
                            pool_data_map[pool_id] = {
                                 "tickCurrent": parsed_pool_data.tickCurrent,
                                 "mintA": mintA,
                                 "mintB": mintB,
                                 "decimals0": parsed_pool_data.mintDecimals0,
                                 "decimals1": parsed_pool_data.mintDecimals1,
                                 "sqrtPriceX64_bytes": parsed_pool_data.sqrtPriceX64, # Храним bytes (16)
                                 "feeRate": fee_rate,
                                 "ammConfig": config_id,
                                 "poolRewardInfos": pool_reward_infos # Добавляем информацию о наградах пула
                             }
                        except Exception as pool_proc_err:
                             print(f"Error processing parsed pool data for pool {pool_id}: {pool_proc_err}")
                    
    # 5.1 Fetch Token Metadata (если есть API ключ и минты)
    token_metadata = {}
    if helius_api_key and unique_mints:
        print(f"Fetching metadata for {len(unique_mints)} unique mints...")
        token_metadata = await fetch_token_metadata_bulk(list(unique_mints), helius_api_key)
        print(f"Fetched metadata for {len(token_metadata)} mints.")
         
    # 5.2 Define Token Price Cache
    token_prices_cache: Dict[str, Decimal] = {} 
    
    # 5.3 Define Raydium API Cache
    raydium_api_cache: Dict[str, Dict[str, Any]] = {}
    
    # 6. Combine Position and Pool Data, Calculate In-Range, Token Amounts, and USD Value
    final_positions_output: List[Dict[str, Any]] = []
    print(f"Processing {len(parsed_positions)} positions...")
    for pos_index, pos in enumerate(parsed_positions):
        pool_info = pool_data_map.get(pos["poolId"])
        mintA_addr = "Unknown" # Default values
        mintB_addr = "Unknown"
        amount0_final = Decimal(0)
        amount1_final = Decimal(0)
        liquidity_str = "0"
        current_price_str = "N/A"
        fee_tier_val = None
        position_value_usd = Decimal(0) # Initialize USD value as Decimal
        in_range = None
        pool_name = "Unknown/Unknown"
        apr_estimate = "0.00%"  # Значение по умолчанию
        recommendation = "❓ Недостаточно данных"  # Значение по умолчанию
        
        # Для данных из json_uri - инициализируем флаг и переменные
        used_json_uri_for_fees = False
        uri_unclaimed_fee_token_a_amount = Decimal(0)
        uri_unclaimed_fee_token_b_amount = Decimal(0)
        uri_unclaimed_fee_usd_value = Decimal(0)

        if pool_info:
            try:
                mintA_addr = pool_info["mintA"]
                mintB_addr = pool_info["mintB"]
                fee_tier_val = pool_info["feeRate"]
                tick_current = pool_info["tickCurrent"]
                in_range = pos["tickLowerIndex"] <= tick_current < pos["tickUpperIndex"]
                
                # Рассчитываем количество токенов (как Decimal)
                try:
                    liquidity_bytes = pos["liquidity_bytes"]
                    sqrt_price_bytes = pool_info["sqrtPriceX64_bytes"]
                    decimals0 = pool_info["decimals0"]
                    decimals1 = pool_info["decimals1"]
                    
                    liquidity_int = int.from_bytes(liquidity_bytes, 'little', signed=False)
                    sqrt_price_int = int.from_bytes(sqrt_price_bytes, 'little', signed=False)
                    liquidity_str = str(liquidity_int) # Сохраняем строковое представление u128
                    
                    amounts_raw = calculate_token_amounts(
                        liquidity_int,
                        sqrt_price_int,
                        pos["tickLowerIndex"],
                        pos["tickUpperIndex"]
                    )
                    
                    amount0_final = amounts_raw["amount0_raw"] / (Decimal(10) ** decimals0)
                    amount1_final = amounts_raw["amount1_raw"] / (Decimal(10) ** decimals1)
                    
                    # -------- НАЧАЛО НОВОЙ СЕКЦИИ: Получение данных из json_uri --------
                    # Находим NFT-позицию среди исходных активов кошелька
                    position_nft_mint = pos.get("position_mint")
                    helius_nft_data = None
                    
                    for asset in clmm_assets:
                        if asset.get('id') == position_nft_mint:
                            helius_nft_data = asset
                            break
                    
                    # Если нашли NFT и у него есть json_uri, пытаемся получить данные оттуда
                    json_uri_data = None
                    if helius_nft_data:
                        json_uri = helius_nft_data.get("content", {}).get("json_uri")
                        
                        if json_uri:
                            # Создаем временный клиент httpx для запроса
                            async with httpx.AsyncClient() as uri_client:
                                try:
                                    json_uri_data = await _fetch_data_from_uri(json_uri, uri_client)
                                except Exception as uri_err:
                                    print(f"[ERROR] Failed to fetch data from json_uri for position {position_nft_mint}: {uri_err}")
                    
                    # Если успешно получили данные из json_uri, извлекаем ВСЮ информацию о позиции
                    uri_has_position_data = False
                    uri_amount_a = Decimal(0)
                    uri_amount_b = Decimal(0)
                    uri_position_usd_value = Decimal(0)
                    
                    if json_uri_data and isinstance(json_uri_data, dict):
                        try:
                            position_info = json_uri_data.get("positionInfo", {})
                            
                            # Извлекаем ОСНОВНЫЕ данные позиции
                            uri_amount_a = Decimal(str(position_info.get("amountA", 0)))
                            uri_amount_b = Decimal(str(position_info.get("amountB", 0)))
                            uri_position_usd_value = Decimal(str(position_info.get("usdValue", 0)))
                            
                            # Извлекаем данные о комиссиях
                            unclaimed_fee_data = position_info.get("unclaimedFee", {})
                            uri_unclaimed_fee_token_a_amount = Decimal(str(unclaimed_fee_data.get("amountA", 0)))
                            uri_unclaimed_fee_token_b_amount = Decimal(str(unclaimed_fee_data.get("amountB", 0)))
                            uri_unclaimed_fee_usd_value = Decimal(str(unclaimed_fee_data.get("usdValue", 0)))
                            
                            # Проверяем, есть ли валидные данные позиции
                            if uri_position_usd_value > 0 or uri_amount_a > 0 or uri_amount_b > 0:
                                uri_has_position_data = True
                                print(f"[INFO] Using FULL position data from json_uri for {position_nft_mint}: A={uri_amount_a}, B={uri_amount_b}, USD={uri_position_usd_value}")
                                
                                # Переписываем расчетные значения на данные из json_uri
                                amount0_final = uri_amount_a
                                amount1_final = uri_amount_b
                                position_value_usd = uri_position_usd_value
                            
                            # Устанавливаем флаг для комиссий
                            if uri_unclaimed_fee_usd_value > 0:
                                used_json_uri_for_fees = True
                                print(f"[INFO] Using fee data from json_uri for position {position_nft_mint}. usdValue: {uri_unclaimed_fee_usd_value}")
                        except Exception as parse_uri_err:
                            print(f"[ERROR] Failed to parse data from json_uri for position {position_nft_mint}: {parse_uri_err}")
                    # -------- КОНЕЦ НОВОЙ СЕКЦИИ: Получение данных из json_uri --------
                    
                    # Расчет невостребованных комиссий и их стоимости на основе ончейн-данных
                    # (будет использоваться как fallback, если данные из json_uri недоступны)
                    fees0_amount = Decimal(pos.get("tokenFeesOwedA", 0)) / (Decimal(10) ** decimals0)
                    fees1_amount = Decimal(pos.get("tokenFeesOwedB", 0)) / (Decimal(10) ** decimals1)
                    
                except Exception as e:
                    print(f"Error calculating token amounts for position {pos.get('position_mint', 'N/A')}: {e}")
                
                # Рассчитываем текущую цену (как строку)
                try:
                    price_decimal = calculate_price_from_sqrt_price_x64(
                        pool_info["sqrtPriceX64_bytes"],
                        pool_info["decimals0"],
                        pool_info["decimals1"]
                    )
                    if price_decimal is not None:
                        if price_decimal == 0:
                            current_price_str = "0.0"
                        elif price_decimal < Decimal('0.000001'):
                             price_format = '.18f' 
                        elif price_decimal < Decimal('1'):
                             price_format = '.9f'
                        else:
                             price_format = '.6f'
                        current_price_str = format(price_decimal, price_format).rstrip('0').rstrip('.')
                        if current_price_str == "": current_price_str = "0"
                except Exception as e:
                     print(f"Error calculating price for pool {pos.get('poolId', 'N/A')}: {e}")
                
                # Fetch/Cache Token Prices and Calculate USD Value
                try:
                    # --- Price Fetching with Cache --- 
                    price0_usd = token_prices_cache.get(mintA_addr)
                    if price0_usd is None:
                        price0_usd = await fetch_token_price(mintA_addr)
                        token_prices_cache[mintA_addr] = price0_usd
                        await asyncio.sleep(0.1) # Small delay after fetch
                    
                    price1_usd = token_prices_cache.get(mintB_addr)
                    if price1_usd is None:
                        price1_usd = await fetch_token_price(mintB_addr)
                        token_prices_cache[mintB_addr] = price1_usd
                        await asyncio.sleep(0.1)
                    
                    # -------- НАЧАЛО МОДИФИЦИРОВАННОЙ СЕКЦИИ: Расчет USD-стоимости комиссий --------
                    # Отладочный вывод перед расчетом USD стоимости комиссий
                    print(f"[DEBUG FEES CALC] Position: {pos.get('position_mint', 'N/A')}, Pool: {pos.get('poolId', 'N/A')}")
                    
                    # Определяем, какие данные использовать для расчета комиссий
                    if used_json_uri_for_fees:
                        # Используем данные из json_uri
                        fees0_amount_for_report = uri_unclaimed_fee_token_a_amount
                        fees1_amount_for_report = uri_unclaimed_fee_token_b_amount
                        unclaimed_fees_usd_val = uri_unclaimed_fee_usd_value
                        
                        print(f"[DEBUG FEES CALC] Using json_uri data: amountA={fees0_amount_for_report}, amountB={fees1_amount_for_report}, usdValue={unclaimed_fees_usd_val}")
                    else:
                        # Используем ончейн-данные
                        fees0_amount_for_report = fees0_amount
                        fees1_amount_for_report = fees1_amount
                        unclaimed_fees_usd_val = (fees0_amount * price0_usd) + (fees1_amount * price1_usd)
                        
                        print(f"[DEBUG FEES CALC] Using onchain data:")
                        print(f"[DEBUG FEES CALC]   Token A ({mintA_addr}): fees_amount={fees0_amount}, price_usd={price0_usd}")
                        print(f"[DEBUG FEES CALC]   Token B ({mintB_addr}): fees_amount={fees1_amount}, price_usd={price1_usd}")
                        print(f"[DEBUG FEES CALC]   Calculated USD value: {unclaimed_fees_usd_val}")
                    
                    # Стоимость позиции: если есть данные из json_uri, используем их, иначе рассчитываем
                    if not uri_has_position_data:
                        position_value_usd = (amount0_final * price0_usd) + (amount1_final * price1_usd)
                        print(f"[DEBUG] Calculated USD value from onchain data: ${position_value_usd}")
                    else:
                        print(f"[DEBUG] Using USD value from json_uri: ${position_value_usd}")
                    
                    # Форматируем значения в строки для отчета
                    fees0_amount_str = fees0_amount_for_report.quantize(Decimal('1e-9'), rounding=ROUND_DOWN).to_eng_string().rstrip('0').rstrip('.')
                    if fees0_amount_str == "": fees0_amount_str = "0"
                    
                    fees1_amount_str = fees1_amount_for_report.quantize(Decimal('1e-9'), rounding=ROUND_DOWN).to_eng_string().rstrip('0').rstrip('.')
                    if fees1_amount_str == "": fees1_amount_str = "0"
                    
                    # Форматируем стоимость комиссий в строку
                    fees_total_usd_str = format(unclaimed_fees_usd_val.quantize(Decimal('0.01')), '.2f')
                    # -------- КОНЕЦ МОДИФИЦИРОВАННОЙ СЕКЦИИ: Расчет USD-стоимости комиссий --------

                except Exception as e:
                    print(f"Error fetching prices or calculating USD value for position {pos.get('position_mint', 'N/A')}: {e}")
                    # Гарантируем определение переменных в случае ошибки
                    unclaimed_fees_usd_val = Decimal(0)
                    position_value_usd = Decimal(0)
                    fees_total_usd_str = "0.00"
                    # fees0_amount_str и fees1_amount_str должны быть уже определены выше,
                    # но на всякий случай, если и там была ошибка, можно добавить:
                    if 'fees0_amount_str' not in locals(): fees0_amount_str = "0"
                    if 'fees1_amount_str' not in locals(): fees1_amount_str = "0"
                
                # --- Расчет невостребованных НАГРАД --- 
                total_rewards_usd_val = Decimal(0)
                position_reward_details = [] # Для хранения деталей по каждой награде
                
                # Получаем информацию о наградах пула
                pool_rewards_info_list = pool_info.get("poolRewardInfos", [])
                
                # Получаем данные о наградах для ЭТОЙ позиции
                position_rewards_data = parsed_data.rewardInfos if parsed_data else [] # Используем parsed_data из начала цикла
                
                for i in range(len(pool_rewards_info_list)):
                    if i >= len(position_rewards_data):
                        continue # Пропускаем, если для этой позиции нет данных награды
                        
                    pool_reward_info = pool_rewards_info_list[i]
                    pos_reward_data = position_rewards_data[i]
                    
                    reward_mint = pool_reward_info.get("mint")
                    reward_state = pool_reward_info.get("state")
                    reward_amount_owed_raw = pos_reward_data.amountOwed
                    
                    reward_token_symbol = "???"
                    reward_token_decimals = None
                    reward_price_usd = Decimal(0)
                    reward_usd_value = Decimal(0)
                    
                    if reward_state != 0 and reward_amount_owed_raw > 0 and reward_mint:
                        # Получаем метаданные и цену токена награды
                        reward_metadata = token_metadata.get(reward_mint, {})
                        reward_token_symbol = reward_metadata.get("symbol", "???")
                        reward_token_decimals = reward_metadata.get("decimals")
                        
                        reward_price_usd = token_prices_cache.get(reward_mint)
                        if reward_price_usd is None:
                            print(f"[Debug] Fetching price for reward token: {reward_mint} ({reward_token_symbol})")
                            reward_price_usd = await fetch_token_price(reward_mint)
                            token_prices_cache[reward_mint] = reward_price_usd
                            await asyncio.sleep(0.1)
                        
                        if reward_token_decimals is not None and reward_price_usd > 0:
                            try:
                                reward_amount = Decimal(reward_amount_owed_raw) / (Decimal(10) ** reward_token_decimals)
                                reward_usd_value = reward_amount * reward_price_usd
                                total_rewards_usd_val += reward_usd_value
                                
                                # Сохраняем детали этой награды
                                position_reward_details.append({
                                    "mint": reward_mint,
                                    "symbol": reward_token_symbol,
                                    "amount": reward_amount.quantize(Decimal('1e-9'), rounding=ROUND_DOWN).to_eng_string(),
                                    "usd_value": format(reward_usd_value.quantize(Decimal('0.01')), '.2f')
                                })
                            except Exception as reward_calc_err:
                                print(f"[Error] Calculating reward value for {reward_token_symbol} ({reward_mint}): {reward_calc_err}")
                        else:
                            print(f"[Warning] Cannot calculate USD value for reward {reward_token_symbol} ({reward_mint}). Decimals: {reward_token_decimals}, Price: {reward_price_usd}")
                # --- Конец расчета наград --- 

                # --- Общий Pending Yield (Комиссии + Награды) --- 
                total_pending_yield_usd_val = unclaimed_fees_usd_val + total_rewards_usd_val
                total_pending_yield_usd_str = format(total_pending_yield_usd_val.quantize(Decimal('0.01')), '.2f')
                # --- Конец Общий Pending Yield --- 

                # Получение данных пула из Raydium API (с кэшированием)
                pool_id = pos["poolId"]
                pool_api_data = raydium_api_cache.get(pool_id)
                if pool_api_data is None:
                    try:
                        pool_api_data = await fetch_pool_details_from_raydium_api(pool_id)
                        raydium_api_cache[pool_id] = pool_api_data if pool_api_data else {}
                        await asyncio.sleep(0.1)  # Небольшая задержка после запроса к API
                    except Exception as api_error:
                        print(f"Error fetching Raydium API data for pool {pool_id}: {api_error}")
                        pool_api_data = {}
                
                # Убедимся, что у нас есть словарь даже если API вернул None
                if pool_api_data is None:
                    pool_api_data = {}
                
                # Расчет APR
                try:
                    daily_volume_usd = Decimal(str(pool_api_data.get('daily_volume_usd', 0)))
                    pool_tvl_usd = Decimal(str(pool_api_data.get('pool_tvl_usd', 0)))
                    
                    # Рассчитываем долю позиции в пуле
                    position_share = Decimal(0)
                    if pool_tvl_usd > 0:
                        position_share = position_value_usd / pool_tvl_usd
                    
                    # Рассчитываем годовой APR
                    apr_decimal = Decimal(0)
                    if position_value_usd > 0 and daily_volume_usd > 0:
                        # Формула: daily_volume_usd * fee_tier * position_share / position_value_usd * 365
                        apr_decimal = daily_volume_usd * Decimal(str(fee_tier_val)) * position_share / position_value_usd * 365
                        apr_decimal = apr_decimal * 100  # Конвертируем в проценты
                        
                    # Форматируем APR как строку с 2 знаками после запятой
                    apr_estimate = f"{apr_decimal:.2f}%"
                except Exception as apr_err:
                    print(f"Error calculating APR for position {pos.get('position_mint', 'N/A')}: {apr_err}")
                    apr_estimate = "0.00%"  # Значение по умолчанию
                
                # Формирование рекомендации
                try:
                    tick_range = pos["tickUpperIndex"] - pos["tickLowerIndex"]
                    
                    if not in_range:
                        recommendation = "💤 Вне диапазона — Рассмотрите ребалансировку"
                    elif tick_range > WIDE_RANGE_THRESHOLD_TICKS:
                        recommendation = "🎯 Широкий диапазон — Рассмотрите концентрацию"
                    elif position_value_usd < Decimal(LOW_TVL_THRESHOLD_USD):
                        recommendation = "⚠️ Низкий TVL — Рассмотрите объединение"
                    else:
                        recommendation = "✅ Активна"
                except Exception as rec_err:
                    print(f"Error determining recommendation for position {pos.get('position_mint', 'N/A')}: {rec_err}")
                    recommendation = "❓ Недостаточно данных"  # Значение по умолчанию
                
                # Формируем имя пула, приоритет: TOKEN_SYMBOL_MAP → token_metadata → "???"
                symbolA = TOKEN_SYMBOL_MAP.get(mintA_addr, token_metadata.get(mintA_addr, {}).get("symbol", "???"))
                symbolB = TOKEN_SYMBOL_MAP.get(mintB_addr, token_metadata.get(mintB_addr, {}).get("symbol", "???"))
                pool_name = f"{symbolA}/{symbolB}"

            except Exception as main_pos_proc_err:
                 print(f"Unhandled error processing position {pos.get('position_mint', 'N/A')} with pool {pos.get('poolId', 'N/A')}: {main_pos_proc_err}")
                 # Use default values set at the start of the loop
            
            # Форматируем финальные значения в строки для вывода
            amount0_str = amount0_final.quantize(Decimal('1e-9'), rounding=ROUND_DOWN).to_eng_string().rstrip('0').rstrip('.')
            if amount0_str == "": amount0_str = "0" 
            
            amount1_str = amount1_final.quantize(Decimal('1e-9'), rounding=ROUND_DOWN).to_eng_string().rstrip('0').rstrip('.')
            if amount1_str == "": amount1_str = "0"

            position_value_usd_str = format(position_value_usd.quantize(Decimal('0.01')), '.2f')
            
            # Форматируем цены токенов для вывода
            price0_usd_str = format(price0_usd.quantize(Decimal('0.000001')), '.6f').rstrip('0').rstrip('.')
            price1_usd_str = format(price1_usd.quantize(Decimal('0.000001')), '.6f').rstrip('0').rstrip('.')

            final_positions_output.append({
                "position_mint": pos["position_mint"],
                "pool_id": pos["poolId"], 
                "pool_name": pool_name, 
                "tick_lower": pos["tickLowerIndex"],
                "tick_upper": pos["tickUpperIndex"],
                "liquidity": liquidity_str, 
                "amount0": amount0_str,
                "amount1": amount1_str,
                "in_range": in_range,
                "current_price": current_price_str,
                "position_value_usd": position_value_usd_str,
                "token0": mintA_addr,
                "token1": mintB_addr,
                "token0_price_usd": price0_usd_str,
                "token1_price_usd": price1_usd_str,
                "fee_tier": fee_tier_val,
                "apr_estimate": apr_estimate,
                "recommendation": recommendation,
                "unclaimed_fees_token0_amount_str": fees0_amount_str,
                "unclaimed_fees_token1_amount_str": fees1_amount_str,
                "unclaimed_fees_total_usd_str": fees_total_usd_str,
                "pending_rewards_details": position_reward_details,
                "total_pending_yield_usd_str": total_pending_yield_usd_str,
                "fees_data_source": "json_uri" if used_json_uri_for_fees else "onchain_calculation"  # Новое поле
            })
            
            # Add a delay *between processing positions* to further mitigate rate limits
            if pos_index < len(parsed_positions) - 1: # Don't sleep after the last one
                 await asyncio.sleep(0.2) # Increased delay slightly

        else: # Case where pool_info was not found for the position
             liquidity_str_fallback = "0"
             if pos.get("liquidity_bytes"):
                 try:
                     liquidity_str_fallback = str(int.from_bytes(pos["liquidity_bytes"], 'little', signed=False))
                 except: pass 
                 
             final_positions_output.append({
                 "position_mint": pos.get("position_mint", "N/A"),
                 "pool_id": pos.get("poolId", "N/A"),
                 "pool_name": "Unknown/Unknown",
                 "tick_lower": pos.get("tickLowerIndex", None),
                 "tick_upper": pos.get("tickUpperIndex", None),
                 "liquidity": liquidity_str_fallback,
                 "amount0": "0",
                 "amount1": "0",
                 "in_range": None, 
                 "current_price": "N/A",
                 "position_value_usd": "0.00",
                 "token0": "Unknown",
                 "token1": "Unknown",
                 "fee_tier": None,
                 "apr_estimate": "0.00%",
                 "recommendation": "❓ Недостаточно данных",
                 "unclaimed_fees_token0_amount_str": "0",
                 "unclaimed_fees_token1_amount_str": "0",
                 "unclaimed_fees_total_usd_str": "0.00",
                 "pending_rewards_details": [],
                 "total_pending_yield_usd_str": "0.00",
                 "fees_data_source": "none",  # Новое поле
                 "error": "Failed to fetch or process pool data"
             })


    print(f"Successfully processed {len(final_positions_output)} CLMM positions for wallet {wallet_address}")
    return final_positions_output

# Пример вызова (для тестирования внутри этого файла)
async def _test_positions():
     from dotenv import load_dotenv
     import os
     load_dotenv(dotenv_path='../.env') # Ищем .env на уровень выше

     helius_rpc = os.getenv("HELIUS_RPC_URL")
     helius_key = os.getenv("HELIUS_API_KEY") # Получаем ключ API
     wallet = "BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD"
     
     if not helius_rpc:
         print("FATAL: HELIUS_RPC_URL is not set in .env file")
         return
     if not helius_key:
         print("FATAL: HELIUS_API_KEY is not set in .env file")
         return

     print(f"--- Testing get_clmm_positions for wallet {wallet} ---")
     positions = await get_clmm_positions(wallet, helius_rpc, helius_key)
     
     if positions:
         print("\n--- First Position Found ---")
         print(json.dumps(positions[0], indent=2))
         print(f"\nTotal positions found: {len(positions)}")
     else:
         print("No positions found or an error occurred.")

if __name__ == "__main__":
     asyncio.run(_test_positions()) 