#!/usr/bin/env python3
"""
Реализация поддержки Standard AMM пулов Raydium для pools-analyzer
"""

import asyncio
import base64
from typing import Dict, List, Optional, Any
from construct import Struct, Int8ul, Int16ul, Int32ul, Int64ul, Bytes, Pass, Adapter
from solders.pubkey import Pubkey
from decimal import Decimal
import httpx

# Константы для Standard AMM
STANDARD_AMM_PROGRAM_ID = "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C"
RAYDIUM_API_V3_BASE_URL = "https://api-v3.raydium.io"

# Хелпер для PublicKey
class PubkeyAdapter(Adapter):
    def _decode(self, obj, context, path):
        return Pubkey(obj)
    def _encode(self, obj, context, path):
        return bytes(obj)

construct_pubkey = PubkeyAdapter(Bytes(32))

# Упрощенная структура CPMM пула основанная на найденных смещениях
# Discriminator (8) + множество полей до первого ключевого Pubkey (LP mint на 136)
CPMM_POOL_LAYOUT = Struct(
    "discriminator" / Bytes(8),              # 0-8: Discriminator
    "status" / Int64ul,                      # 8-16: Status
    "nonce" / Int64ul,                       # 16-24: Nonce 
    "orderNum" / Int64ul,                    # 24-32: Order number
    "depth" / Int64ul,                       # 32-40: Depth
    "coinDecimals" / Int64ul,                # 40-48: Coin decimals
    "pcDecimals" / Int64ul,                  # 48-56: PC decimals
    "state" / Int64ul,                       # 56-64: State
    "resetFlag" / Int64ul,                   # 64-72: Reset flag
    "minSize" / Int64ul,                     # 72-80: Min size
    "volMaxCutRatio" / Int64ul,              # 80-88: Volume max cut ratio
    "amountWaveRatio" / Int64ul,             # 88-96: Amount wave ratio
    "coinLotSize" / Int64ul,                 # 96-104: Coin lot size
    "pcLotSize" / Int64ul,                   # 104-112: PC lot size
    "minPriceMultiplier" / Int64ul,          # 112-120: Min price multiplier
    "maxPriceMultiplier" / Int64ul,          # 120-128: Max price multiplier
    "systemDecimalsValue" / Int64ul,         # 128-136: System decimals value
    
    # Pubkey поля начинаются с offset 136
    "lpMint" / construct_pubkey,             # 136-168: LP mint
    "coinMint" / construct_pubkey,           # 168-200: Coin mint (BIO)
    "pcMint" / construct_pubkey,             # 200-232: PC mint (VITA)
    
    # Оставшиеся поля можем заполнить по мере необходимости
    "poolCoinTokenAccount" / construct_pubkey,   # 232-264: Pool coin token account
    "poolPcTokenAccount" / construct_pubkey,     # 264-296: Pool PC token account
    "withdrawQueue" / construct_pubkey,          # 296-328: Withdraw queue
    "ammTargetOrders" / construct_pubkey,        # 328-360: AMM target orders
    "poolTempLpTokenAccount" / construct_pubkey, # 360-392: Pool temp LP account
    "ammOpenOrders" / construct_pubkey,          # 392-424: AMM open orders
    "serumMarket" / construct_pubkey,            # 424-456: Serum market
    "serumProgramId" / construct_pubkey,         # 456-488: Serum program ID
    "ammOwner" / construct_pubkey,               # 488-520: AMM owner
    "pnlOwner" / construct_pubkey,               # 520-552: PnL owner
)

async def get_account_info(rpc_url: str, account_address: str, client: httpx.AsyncClient) -> dict:
    """Получить информацию об аккаунте через RPC"""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [account_address, {"encoding": "base64", "commitment": "confirmed"}]
    }
    
    response = await client.post(rpc_url, json=payload)
    response.raise_for_status()
    return response.json()

async def parse_cpmm_pool_state(pool_id: str, rpc_url: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Парсинг состояния CPMM пула"""
    try:
        result = await get_account_info(rpc_url, pool_id, client)
        account_info = result.get("result", {}).get("value")
        
        if not account_info:
            print(f"❌ CPMM pool account {pool_id} не найден")
            return None
        
        if account_info.get('owner') != STANDARD_AMM_PROGRAM_ID:
            print(f"❌ Неправильный owner для CPMM пула: {account_info.get('owner')}")
            return None
        
        # Парсим данные
        raw_data = base64.b64decode(account_info['data'][0])
        parsed = CPMM_POOL_LAYOUT.parse(raw_data)
        
        return {
            "discriminator": parsed.discriminator.hex(),
            "status": parsed.status,
            "nonce": parsed.nonce,
            "orderNum": parsed.orderNum,
            "depth": parsed.depth,
            "coinDecimals": parsed.coinDecimals,
            "pcDecimals": parsed.pcDecimals,
            "state": parsed.state,
            "resetFlag": parsed.resetFlag,
            "minSize": parsed.minSize,
            "volMaxCutRatio": parsed.volMaxCutRatio,
            "amountWaveRatio": parsed.amountWaveRatio,
            "coinLotSize": parsed.coinLotSize,
            "pcLotSize": parsed.pcLotSize,
            "minPriceMultiplier": parsed.minPriceMultiplier,
            "maxPriceMultiplier": parsed.maxPriceMultiplier,
            "systemDecimalsValue": parsed.systemDecimalsValue,
            
            # Pubkey поля
            "lpMint": str(parsed.lpMint),
            "coinMint": str(parsed.coinMint),
            "pcMint": str(parsed.pcMint),
            "poolCoinTokenAccount": str(parsed.poolCoinTokenAccount),
            "poolPcTokenAccount": str(parsed.poolPcTokenAccount),
            "withdrawQueue": str(parsed.withdrawQueue),
            "ammTargetOrders": str(parsed.ammTargetOrders),
            "poolTempLpTokenAccount": str(parsed.poolTempLpTokenAccount),
            "ammOpenOrders": str(parsed.ammOpenOrders),
            "serumMarket": str(parsed.serumMarket),
            "serumProgramId": str(parsed.serumProgramId),
            "ammOwner": str(parsed.ammOwner),
            "pnlOwner": str(parsed.pnlOwner),
        }
        
    except Exception as e:
        print(f"❌ Ошибка парсинга CPMM пула {pool_id}: {e}")
        return None

async def get_cpmm_pool_market_data(pool_id: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
    """Получение рыночных данных CPMM пула через Raydium API"""
    try:
        url = f"{RAYDIUM_API_V3_BASE_URL}/pools/info/ids"
        params = {"ids": pool_id}
        
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data and "data" in data and data["data"]:
            pool_data = data["data"][0]
            
            return {
                "pool_id": pool_data.get("id"),
                "type": pool_data.get("type"),
                "program_id": pool_data.get("programId"),
                "tvl_usd": pool_data.get("tvl", 0),
                "volume_24h_usd": pool_data.get("day", {}).get("volume", 0),
                "volume_24h_quote": pool_data.get("day", {}).get("volumeQuote", 0),
                "mint_a": {
                    "address": pool_data.get("mintA", {}).get("address"),
                    "symbol": pool_data.get("mintA", {}).get("symbol"),
                    "decimals": pool_data.get("mintA", {}).get("decimals"),
                },
                "mint_b": {
                    "address": pool_data.get("mintB", {}).get("address"),
                    "symbol": pool_data.get("mintB", {}).get("symbol"),
                    "decimals": pool_data.get("mintB", {}).get("decimals"),
                },
                "lp_mint": {
                    "address": pool_data.get("lpMint", {}).get("address"),
                    "decimals": pool_data.get("lpMint", {}).get("decimals"),
                }
            }
    except Exception as e:
        print(f"❌ Ошибка получения рыночных данных CPMM пула {pool_id}: {e}")
        return None

async def detect_standard_amm_positions(wallet_address: str, rpc_url: str, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
    """Обнаружение позиций в Standard AMM пулах
    
    Standard AMM позиции представлены как LP токены в кошельке пользователя.
    В отличие от CLMM, где позиции - это NFT, здесь позиции - это обычные токены.
    """
    positions = []
    
    try:
        # Получаем все токен аккаунты кошелька
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getTokenAccountsByOwner",
            "params": [
                wallet_address,
                {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
                {"encoding": "jsonParsed"}
            ]
        }
        
        response = await client.post(rpc_url, json=payload)
        response.raise_for_status()
        result = response.json()
        
        if "result" not in result or "value" not in result["result"]:
            return positions
        
        token_accounts = result["result"]["value"]
        print(f"🔍 Найдено {len(token_accounts)} токен аккаунтов для кошелька {wallet_address}")
        
        # Для каждого токен аккаунта проверяем, является ли он LP токеном
        for account in token_accounts:
            try:
                account_info = account["account"]["data"]["parsed"]["info"]
                token_amount = float(account_info["tokenAmount"]["uiAmount"] or 0)
                
                if token_amount <= 0:
                    continue  # Пропускаем пустые аккаунты
                
                mint_address = account_info["mint"]
                
                # Проверяем через API, является ли этот минт LP токеном
                lp_pool_data = await check_if_lp_token(mint_address, client)
                
                if lp_pool_data:
                    print(f"✅ Найдена Standard AMM позиция: {mint_address}")
                    
                    # Получаем данные пула
                    pool_state = await parse_cpmm_pool_state(lp_pool_data["pool_id"], rpc_url, client)
                    pool_market_data = await get_cpmm_pool_market_data(lp_pool_data["pool_id"], client)
                    
                    position = {
                        "position_type": "standard_amm",
                        "position_mint": mint_address,
                        "pool_id": lp_pool_data["pool_id"],
                        "lp_amount": token_amount,
                        "lp_amount_raw": int(account_info["tokenAmount"]["amount"]),
                        "pool_state": pool_state,
                        "market_data": pool_market_data,
                        "token_account": account["pubkey"],
                    }
                    
                    positions.append(position)
                    
            except Exception as e:
                print(f"❌ Ошибка обработки токен аккаунта: {e}")
                continue
        
        print(f"✅ Найдено {len(positions)} Standard AMM позиций")
        return positions
        
    except Exception as e:
        print(f"❌ Ошибка поиска Standard AMM позиций: {e}")
        return []

async def check_if_lp_token(mint_address: str, client: httpx.AsyncClient) -> Optional[Dict[str, str]]:
    """Проверяет, является ли токен LP токеном Standard AMM пула"""
    try:
        # Ищем пулы, где этот минт является LP токеном
        url = f"{RAYDIUM_API_V3_BASE_URL}/pools/info/mint"
        params = {"mint1": mint_address, "poolType": "Standard"}
        
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data and "data" in data and "data" in data["data"]:
            pools = data["data"]["data"]
            
            for pool in pools:
                lp_mint = pool.get("lpMint", {}).get("address")
                if lp_mint == mint_address:
                    return {
                        "pool_id": pool.get("id"),
                        "lp_mint": lp_mint
                    }
        
        return None
        
    except Exception as e:
        print(f"❌ Ошибка проверки LP токена {mint_address}: {e}")
        return None

# Основная функция для тестирования
async def test_standard_amm_support():
    """Тестирование поддержки Standard AMM"""
    print("🚀 Тестирование поддержки Standard AMM...")
    
    # Тестовые данные
    bio_vita_pool_id = "J6jUwNvCUme9ma7DMsHiWVXic4B6zovVdr2GfCrozauB"
    test_wallet = "BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD"
    rpc_url = "https://mainnet.helius-rpc.com/?api-key=d4af7b72-f199-4d77-91a9-11d8512c5e42"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        print("\n1. Тестирование парсинга CPMM пула...")
        pool_state = await parse_cpmm_pool_state(bio_vita_pool_id, rpc_url, client)
        
        if pool_state:
            print("✅ Успешно распарсили CPMM пул:")
            print(f"   Coin Mint: {pool_state['coinMint']}")
            print(f"   PC Mint: {pool_state['pcMint']}")
            print(f"   LP Mint: {pool_state['lpMint']}")
            print(f"   Status: {pool_state['status']}")
            
        print("\n2. Тестирование получения рыночных данных...")
        market_data = await get_cpmm_pool_market_data(bio_vita_pool_id, client)
        
        if market_data:
            print("✅ Успешно получили рыночные данные:")
            print(f"   TVL: ${market_data['tvl_usd']:,.2f}")
            print(f"   Volume 24h: ${market_data['volume_24h_usd']:,.2f}")
            print(f"   Type: {market_data['type']}")
            
        print("\n3. Тестирование поиска Standard AMM позиций...")
        positions = await detect_standard_amm_positions(test_wallet, rpc_url, client)
        
        print(f"✅ Найдено {len(positions)} Standard AMM позиций")
        for pos in positions:
            print(f"   LP Mint: {pos['position_mint']}")
            print(f"   Pool ID: {pos['pool_id']}")
            print(f"   LP Amount: {pos['lp_amount']}")

if __name__ == "__main__":
    asyncio.run(test_standard_amm_support())
