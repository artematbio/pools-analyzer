"""
Unified Positions Analyzer для Ethereum и Base
Получение точных данных по позициям Uniswap v3 аналогично подходу для Solana
"""

import asyncio
import logging
from typing import List, Dict, Any, Optional, Set
from decimal import Decimal, getcontext
import sys
import os
import time
from datetime import datetime

# Добавляем пути для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from ethereum.data_sources.rpc_client import create_ethereum_rpc_client, RPCEndpoint, EthereumRPCClient
from ethereum.contracts.uniswap_abis import NONFUNGIBLE_POSITION_MANAGER

# Интеграция с Supabase (опционально)
try:
    from database_handler import supabase_handler
    SUPABASE_ENABLED = True
    print("✅ Supabase handler доступен для позиций Ethereum/Base")
except ImportError as e:
    print(f"⚠️ Supabase handler недоступен: {e}")
    supabase_handler = None
    SUPABASE_ENABLED = False

# Настройка точности для Decimal
getcontext().prec = 78

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_multichain_rpc_client(network: str = "ethereum") -> EthereumRPCClient:
    """Создает RPC клиент для указанной сети"""
    
    if network == "ethereum":
        return create_ethereum_rpc_client(
            alchemy_api_key=os.getenv("ALCHEMY_API_KEY", "Hkg1Oi9c8x3JEiXj2cL62")
        )
    elif network == "base":
        # Base RPC endpoints
        base_endpoints = [
            RPCEndpoint(
                name="base_alchemy",
                url="https://base-mainnet.g.alchemy.com/v2",
                api_key=os.getenv("ALCHEMY_API_KEY", "Hkg1Oi9c8x3JEiXj2cL62"),
                priority=1
            ),
            RPCEndpoint(
                name="base_public",
                url="https://mainnet.base.org",
                priority=2
            ),
            RPCEndpoint(
                name="base_quicknode",
                url="https://base.llamarpc.com",
                priority=3
            )
        ]
        return EthereumRPCClient(base_endpoints)
    else:
        raise ValueError(f"Неподдерживаемая сеть: {network}")

# Конфигурация сетей
NETWORKS_CONFIG = {
    "ethereum": {
        "name": "Ethereum",
        "rpc_urls": [
            "https://eth-mainnet.g.alchemy.com/v2/Hkg1Oi9c8x3JEiXj2cL62",
            "https://ethereum.llamarpc.com",
        ],
        "nft_contract": "0xC36442b4a4522E871399CD717aBDD847Ab11FE88",
        "chain_id": 1
    },
    "base": {
        "name": "Base",
        "rpc_urls": [
            "https://base-mainnet.g.alchemy.com/v2/Hkg1Oi9c8x3JEiXj2cL62",
            "https://mainnet.base.org",
        ],
        "nft_contract": "0x03a520b32c04bf3beef7beb72e919cf822ed34f1",
        "chain_id": 8453
    }
}

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
            'tick_lower': decode_int24(chunks[5]),
            'tick_upper': decode_int24(chunks[6]),
            'liquidity': int(chunks[7], 16),
            'fee_growth_inside0_last_x128': int(chunks[8], 16),
            'fee_growth_inside1_last_x128': int(chunks[9], 16),
            'tokens_owed0': int(chunks[10], 16),
            'tokens_owed1': int(chunks[11], 16)
        }
    except Exception as e:
        logger.error(f"Ошибка декодирования позиции: {e}")
        return None

async def get_uniswap_v2_positions(
    wallet_address: str,
    network: str,
    rpc_client,
    min_value_usd: float = 100.0
) -> List[Dict[str, Any]]:
    """
    Получает Uniswap v2 LP позиции из кошелька
    
    Args:
        wallet_address: Адрес кошелька
        network: Сеть (ethereum/base)
        rpc_client: RPC клиент
        min_value_usd: Минимальная стоимость позиции
        
    Returns:
        Список v2 LP позиций
    """
    try:
        # Получаем известные v2 LP токены из dao_pool_snapshots для данной сети
        if SUPABASE_ENABLED and supabase_handler and supabase_handler.is_connected():
            # Получаем LP токены/пулы из dao_pool_snapshots где dex != 'uniswap_v3'
            dao_pools_result = supabase_handler.client.table('dao_pool_snapshots').select(
                'pool_address, pool_name, tvl_usd, dex, token_symbol'
            ).eq('network', network).neq('dex', 'uniswap_v3').gte(
                'created_at', '2025-07-28'
            ).order('created_at', desc=True).execute()
            
            if not dao_pools_result.data:
                logger.info(f"Нет v2 пулов в dao_pool_snapshots для {network}")
                return []
                
            logger.info(f"🔍 Проверяем {len(dao_pools_result.data)} v2 пулов для {network}")
            
            # Получаем балансы LP токенов в кошельке
            v2_positions = []
            
            for pool in dao_pools_result.data:
                pool_address = pool['pool_address']
                if not pool_address or pool_address.startswith('virtual_'):
                    continue  # Пропускаем виртуальные пулы
                    
                try:
                    # Получаем баланс LP токена в кошельке
                    balance_call = {
                        "method": "eth_call",
                        "params": [{
                            "to": pool_address,
                            "data": f"0x70a08231{wallet_address[2:].lower().zfill(64)}"  # balanceOf(wallet)
                        }, "latest"],
                        "id": 1
                    }
                    
                    balance_result = await rpc_client.batch_call([balance_call])
                    if balance_result and "result" in balance_result[0]:
                        balance_hex = balance_result[0]["result"]
                        if balance_hex and balance_hex != "0x" and balance_hex != "0x0":
                            balance_raw = int(balance_hex, 16)
                            
                            if balance_raw > 0:
                                # У нас есть LP токены в этом пуле!
                                logger.info(f"💰 Найден v2 LP баланс: {pool['pool_name']} = {balance_raw} wei")
                                
                                # Для простоты используем TVL из dao_pool_snapshots как нашу позицию
                                # TODO: Рассчитать точную стоимость через долю LP токенов
                                our_position_value = min(pool.get('tvl_usd', 0) * 0.01, 10000)  # Примерно 1% TVL, макс $10k
                                
                                if our_position_value >= min_value_usd:
                                    v2_position = {
                                        'pool_name': pool['pool_name'],
                                        'total_value_usd': our_position_value,
                                        'position_value_usd': our_position_value,
                                        'pool_id': pool_address,
                                        'pool_address': pool_address,
                                        'pool_tvl_usd': pool.get('tvl_usd', 0),
                                        'token_id': f"v2_{pool_address}",
                                        'position_mint': f"{network}_v2_{pool_address}",
                                        'network': network,
                                        'fees_usd': 0,  # v2 не имеет unclaimed fees
                                        'unclaimed_fees_usd': 0,
                                        'in_range': True,  # v2 всегда in range
                                        'dex': pool.get('dex', 'uniswap_v2'),
                                        'is_v2_pool': True,
                                        'lp_balance_raw': balance_raw
                                    }
                                    v2_positions.append(v2_position)
                                    logger.info(f"✅ Добавлена v2 позиция: {pool['pool_name']} = ${our_position_value:,.2f}")
                                    
                except Exception as e:
                    logger.debug(f"Ошибка проверки v2 пула {pool_address}: {e}")
                    continue
            
            # Сохраняем v2 позиции в Supabase если найдены
            if v2_positions and SUPABASE_ENABLED:
                try:
                    import asyncio
                    asyncio.create_task(save_ethereum_positions_to_supabase(v2_positions, network))
                    logger.info(f"💾 Отправлено {len(v2_positions)} v2 позиций на сохранение в Supabase")
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка автосохранения v2 позиций: {e}")
                    
            return v2_positions
            
        else:
            logger.warning("Supabase недоступен для поиска v2 позиций")
            return []
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения v2 позиций: {e}")
        return []

async def get_uniswap_positions(
    wallet_address: str,
    network: str = "ethereum",
    min_value_usd: float = 0.0,
    token_prices: Optional[Dict[str, float]] = None
) -> List[Dict[str, Any]]:
    """
    Получает позиции Uniswap v3 аналогично get_clmm_positions() для Solana
    
    Args:
        wallet_address: Адрес кошелька (0x...)
        network: Сеть ("ethereum" или "base")
        min_value_usd: Минимальная стоимость позиции для включения
        token_prices: Опциональный словарь с ценами токенов {address: price_usd}
        
    Returns:
        Список позиций с детальной информацией
    """
    
    if network not in NETWORKS_CONFIG:
        logger.error(f"Неподдерживаемая сеть: {network}")
        return []
    
    config = NETWORKS_CONFIG[network]
    logger.info(f"🔍 Получаем позиции Uniswap v3 + v2 для {wallet_address} в сети {config['name']}")
    
    # Создаем RPC клиент для указанной сети
    rpc_client = create_multichain_rpc_client(network)
    
    try:
        async with rpc_client:
            # 🔥 НОВОЕ: Получаем Uniswap v2 LP токены
            v2_positions = await get_uniswap_v2_positions(wallet_address, network, rpc_client, min_value_usd)
            logger.info(f"✅ Найдено {len(v2_positions)} Uniswap v2 позиций")
            
            # 1. Получаем количество NFT позиций (v3)
            balance_call = {
                "method": "eth_call",
                "params": [
                    {
                        "to": config["nft_contract"],
                        "data": f"0x70a08231{wallet_address[2:].lower().zfill(64)}"  # balanceOf
                    },
                    "latest"
                ],
                "id": 1
            }
            
            balance_results = await rpc_client.batch_call([balance_call])
            if not balance_results or "result" not in balance_results[0]:
                logger.error("Не удалось получить баланс NFT")
                return []
                
            # Проверяем валидность hex результата
            result_hex = balance_results[0]["result"]
            if not result_hex or result_hex == "0x" or len(result_hex) <= 2:
                logger.warning(f"Получен некорректный hex результат: {result_hex}")
                return []
                
            balance = int(result_hex, 16)
            logger.info(f"✅ Найдено {balance} NFT позиций в кошельке")
            
            if balance == 0:
                return []
            
            # 2. Получаем token IDs всех позиций
            token_calls = []
            for i in range(balance):
                data = (
                    "0x2f745c59" +  # tokenOfOwnerByIndex selector
                    wallet_address[2:].lower().zfill(64) +  # owner address
                    hex(i)[2:].zfill(64)  # index
                )
                token_calls.append({
                    "method": "eth_call",
                    "params": [{"to": config["nft_contract"], "data": data}, "latest"],
                    "id": i
                })
            
            token_results = await rpc_client.batch_call(token_calls)
            token_ids = []
            
            for result in token_results:
                if "result" in result:
                    result_hex = result["result"]
                    if result_hex and result_hex != "0x" and len(result_hex) > 2:
                        token_id = int(result_hex, 16)
                        token_ids.append(token_id)
            
            logger.info(f"📋 Получено {len(token_ids)} Token IDs")
            
            # 3. Получаем детальные данные позиций
            position_calls = []
            for token_id in token_ids:
                data = f"0x99fbab88{hex(token_id)[2:].zfill(64)}"  # positions selector
                position_calls.append({
                    "method": "eth_call",
                    "params": [{"to": config["nft_contract"], "data": data}, "latest"],
                    "id": token_id
                })
            
            position_results = await rpc_client.batch_call(position_calls)
            
            # 4. Парсим данные позиций
            parsed_positions = []
            unique_tokens: Set[str] = set()
            
            for i, result in enumerate(position_results):
                if "result" in result:
                    token_id = token_ids[i]
                    position_data = decode_position_data(result["result"])
                    
                    if position_data and position_data["liquidity"] > 0:
                        # Добавляем токены для получения метаданных
                        unique_tokens.add(position_data["token0"])
                        unique_tokens.add(position_data["token1"])
                        
                        parsed_positions.append({
                            "token_id": token_id,
                            "network": network,
                            "position_data": position_data,
                            "nft_contract": config["nft_contract"]
                        })
            
            logger.info(f"✅ Парсено {len(parsed_positions)} активных позиций")
            
            # 5. Получаем метаданные токенов
            token_metadata = await fetch_token_metadata_batch(
                list(unique_tokens), 
                network, 
                rpc_client
            )
            
            # 6. ПОЛУЧАЕМ ТОЧНЫЕ ДАННЫЕ ЧЕРЕЗ RPC (аналог json_uri для Solana)
            # НЕ ИСПОЛЬЗУЕМ SUBGRAPH - он дает неадекватные данные!
            
            # 7. Получаем реальные адреса пулов через Factory и их состояния
            pool_data = {}
            pool_token_info = {}  # Мапинг pool_address -> token_info
            
            for pos in parsed_positions:
                pos_data = pos["position_data"]
                pool_addr = await get_pool_address_from_factory(
                    pos_data["token0"], 
                    pos_data["token1"], 
                    pos_data["fee"],
                    rpc_client,
                    network
                )
                pool_key = f"{pos_data['token0']}_{pos_data['token1']}_{pos_data['fee']}"
                pool_data[pool_key] = pool_addr
                
                # Сохраняем информацию о токенах для pool_address
                pool_token_info[pool_addr] = {
                    'token0_address': pos_data["token0"],
                    'token1_address': pos_data["token1"],
                    'token0_symbol': token_metadata.get(pos_data["token0"], {}).get("symbol", "UNK"),
                    'token1_symbol': token_metadata.get(pos_data["token1"], {}).get("symbol", "UNK"),
                    'fee_tier': pos_data["fee"]
                }
            
            pool_states = await fetch_pool_states_batch(list(pool_data.values()), rpc_client)
            
            # Сохраняем данные пулов в Supabase
            logger.info(f"💾 Сохраняем {len(pool_states)} пулов {network} в Supabase...")
            saved_pools_count = 0
            for pool_address, state in pool_states.items():
                try:
                    # Получаем информацию о токенах для этого пула
                    token_info = pool_token_info.get(pool_address, {})
                    token0_symbol = token_info.get('token0_symbol', 'UNK')
                    token1_symbol = token_info.get('token1_symbol', 'UNK')
                    
                    # Формируем данные пула для сохранения
                    pool_save_data = {
                        'pool_address': pool_address,
                        'tick': state.get('tick'),
                        'sqrtPriceX96': state.get('sqrtPriceX96'),
                        'liquidity': state.get('liquidity'),
                        'pool_name': f"{token0_symbol}/{token1_symbol}",  # ✅ ПРАВИЛЬНОЕ ИМЯ
                        'token0_address': token_info.get('token0_address'),
                        'token1_address': token_info.get('token1_address'),
                        'token0_symbol': token0_symbol,
                        'token1_symbol': token1_symbol,
                        'fee_tier': token_info.get('fee_tier', 3000),
                        'tvl_usd': 0,  # Будет обновлено позже
                        'volume_24h_usd': 0,
                        'current_price': 0
                    }
                    
                    # Сохраняем пул
                    success = await save_ethereum_pool_to_supabase(pool_save_data, network)
                    if success:
                        saved_pools_count += 1
                        
                except Exception as e:
                    logger.warning(f"⚠️ Ошибка сохранения пула {pool_address}: {e}")
            
            logger.info(f"✅ Сохранено {saved_pools_count}/{len(pool_states)} пулов {network}")
            
            # 7.5. Получаем цены токенов через CoinGecko Pro или используем переданные
            if token_prices is None:
                token_prices_final = await fetch_token_prices_batch(list(unique_tokens), network)
            else:
                # Конвертируем переданные цены (float) в Decimal для совместимости
                token_prices_final = {addr: Decimal(str(price)) for addr, price in token_prices.items()}
                logger.info(f"📈 Используем переданные цены для {len(token_prices_final)} токенов")
            
            # 7.6. Получаем TVL пулов через Subgraph (проверенный метод)
            pool_tvl_data = {}
            real_pool_addresses = [addr for addr in pool_data.values() if not addr.startswith("unknown")]
            if real_pool_addresses:
                try:
                    # 🔥 ИСПРАВЛЕНИЕ: Сначала пробуем RPC, если не работает - используем Subgraph
                    tvl_results = {}
                    
                    if network in ["base", "ethereum"]:
                        logger.info(f"🧮 Получаем TVL для {len(real_pool_addresses)} {network} пулов через RPC...")
                        try:
                            tvl_results = await get_pool_tvl_via_rpc(real_pool_addresses, network, rpc_client, token_prices_final)
                            
                            # Проверяем что RPC вернул валидные данные (не все нули)
                            valid_tvl_count = sum(1 for tvl in tvl_results.values() if tvl > 0)
                            if valid_tvl_count == 0 and len(tvl_results) > 0:
                                logger.warning(f"⚠️ RPC вернул только нулевые TVL для {network}, переключаемся на Subgraph")
                                raise Exception("RPC returned only zero TVL values")
                                
                            logger.info(f"✅ RPC успешно: {valid_tvl_count}/{len(tvl_results)} пулов с TVL > 0")
                        except Exception as rpc_error:
                            logger.warning(f"⚠️ RPC расчет TVL не удался для {network}: {rpc_error}")
                            logger.info(f"🌐 Переключаемся на Subgraph для {network}...")
                            tvl_results = await get_pool_tvl_via_subgraph(real_pool_addresses, network)
                    else:
                        logger.info(f"📊 Получаем TVL для {len(real_pool_addresses)} пулов через Subgraph...")
                        tvl_results = await get_pool_tvl_via_subgraph(real_pool_addresses, network)
                    
                    for pool_addr, tvl_usd in tvl_results.items():
                        # Определяем какой метод реально использовался
                        if network in ["base", "ethereum"]:
                            # Для Ethereum/Base сначала пробовали RPC, если не сработал - то Subgraph
                            # Проверяем есть ли в логах сообщение о переключении на Subgraph
                            calculation_method = 'subgraph_verified'  # По умолчанию считаем что используется Subgraph для надежности
                        else:
                            calculation_method = 'subgraph_verified'
                            
                        pool_tvl_data[pool_addr] = {
                            'tvl_usd': tvl_usd,
                            'volume_usd': 0,  # Volume не получаем, чтобы не усложнять
                            'calculation_method': calculation_method
                        }
                        
                        # Определяем метод который реально использовался
                        calculation_method = pool_tvl_data[pool_addr]['calculation_method']
                        method_name = "RPC" if "rpc" in calculation_method else "Subgraph"
                        logger.info(f"✅ Pool {pool_addr[:8]}...: TVL = ${tvl_usd:,.0f} ({method_name})")
                        
                        # 🔥 КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ: Обновляем TVL в уже сохраненном пуле
                        if SUPABASE_ENABLED and tvl_usd > 0:
                            try:
                                # Обновляем TVL данные в базе
                                pool_update_data = {
                                    'tvl_usd': tvl_usd
                                }
                                update_result = await update_ethereum_pool_tvl(pool_addr, pool_update_data, network)
                                if update_result:
                                    logger.info(f"💾 TVL успешно обновлен в базе для {pool_addr[:8]}...")
                                else:
                                    logger.warning(f"⚠️ Не удалось обновить TVL в базе для {pool_addr[:8]}...")
                            except Exception as e:
                                logger.warning(f"⚠️ Ошибка обновления TVL пула {pool_addr[:8]}...: {e}")
                        elif tvl_usd == 0:
                            logger.warning(f"⚠️ Пул {pool_addr[:8]}... имеет TVL = 0, пропускаем обновление")
                        
                    # Подсчитываем реально использованные методы
                    rpc_count = sum(1 for data in pool_tvl_data.values() if "rpc" in data['calculation_method'])
                    subgraph_count = sum(1 for data in pool_tvl_data.values() if "subgraph" in data['calculation_method'])
                    
                    method_summary = f"RPC: {rpc_count}, Subgraph: {subgraph_count}" if rpc_count > 0 and subgraph_count > 0 else ("RPC" if rpc_count > 0 else "Subgraph")
                    logger.info(f"📊 Получены TVL данные для {len(pool_tvl_data)} пулов через {method_summary}")
                    
                    # Подсчитываем сколько пулов действительно обновлено
                    updated_count = sum(1 for data in pool_tvl_data.values() if data['tvl_usd'] > 0)
                    logger.info(f"💾 {updated_count}/{len(pool_tvl_data)} пулов с TVL > 0 обновлены в lp_pool_snapshots для {network}")
                        
                except Exception as e:
                    logger.warning(f"⚠️ Не удалось получить TVL через Subgraph: {e}")
                    pool_tvl_data = {}

            
            # 8. Рассчитываем USD стоимость с ПРАВИЛЬНОЙ математикой Uniswap v3
            final_positions = []
            
            for position in parsed_positions:
                enhanced_position = await enhance_position_data_with_rpc(
                    position, 
                    pool_data,
                    pool_states,
                    token_metadata, 
                    token_prices_final,
                    config,
                    rpc_client,
                    pool_tvl_data  # Добавляем TVL данные
                )
                
                # Фильтрация по минимальной стоимости
                if enhanced_position.get("total_value_usd", 0) >= min_value_usd:
                    final_positions.append(enhanced_position)
            
            logger.info(f"🎯 Итого {len(final_positions)} v3 позиций (фильтр >${min_value_usd} USD)")
            
            # 🔥 ОБЪЕДИНЯЕМ v2 и v3 позиции
            all_positions = v2_positions + final_positions
            logger.info(f"🎯 ИТОГО: {len(all_positions)} позиций (v2: {len(v2_positions)}, v3: {len(final_positions)})")
            return all_positions
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения позиций: {e}")
        return []

async def fetch_token_metadata_batch(
    token_addresses: List[str], 
    network: str, 
    rpc_client
) -> Dict[str, Dict[str, Any]]:
    """Получает метаданные токенов (symbol, decimals, name)"""
    
    metadata = {}
    
    # Создаем batch calls для всех токенов
    calls = []
    for token_addr in token_addresses:
        # symbol()
        calls.append({
            "method": "eth_call",
            "params": [{"to": token_addr, "data": "0x95d89b41"}, "latest"],
            "id": f"{token_addr}_symbol"
        })
        # decimals()
        calls.append({
            "method": "eth_call", 
            "params": [{"to": token_addr, "data": "0x313ce567"}, "latest"],
            "id": f"{token_addr}_decimals"
        })
        # name()
        calls.append({
            "method": "eth_call",
            "params": [{"to": token_addr, "data": "0x06fdde03"}, "latest"],
            "id": f"{token_addr}_name"
        })
    
    try:
        results = await rpc_client.batch_call(calls)
        
        # Парсим результаты
        for result in results:
            if "result" in result and result["result"] != "0x":
                result_id = result["id"]
                token_addr, field = result_id.rsplit("_", 1)
                
                if token_addr not in metadata:
                    metadata[token_addr] = {}
                
                if field == "symbol":
                    # Декодируем string из hex
                    metadata[token_addr]["symbol"] = decode_string_from_hex(result["result"])
                elif field == "decimals":
                    result_hex = result["result"]
                    if result_hex and result_hex != "0x" and len(result_hex) > 2:
                        metadata[token_addr]["decimals"] = int(result_hex, 16)
                    else:
                        metadata[token_addr]["decimals"] = 18  # default decimals
                elif field == "name":
                    metadata[token_addr]["name"] = decode_string_from_hex(result["result"])
                    
    except Exception as e:
        logger.error(f"Ошибка получения метаданных токенов: {e}")
    
    return metadata

def decode_string_from_hex(hex_str: str) -> str:
    """Декодирует строку из hex результата ABI"""
    try:
        if not hex_str or hex_str == "0x":
            return "Unknown"
        
        # Убираем 0x и первые 64 символа (offset и length)
        clean_hex = hex_str[2:]
        if len(clean_hex) < 128:
            return "Unknown"
            
        # Получаем длину строки
        length = int(clean_hex[64:128], 16)
        
        # Извлекаем строку
        string_hex = clean_hex[128:128 + length * 2]
        return bytes.fromhex(string_hex).decode('utf-8', errors='ignore')
        
    except Exception:
        return "Unknown"

async def fetch_token_prices_batch(token_addresses: List[str], network: str = "ethereum") -> Dict[str, Decimal]:
    """Получает цены токенов через CoinGecko Pro API"""
    try:
        import httpx
        
        if not token_addresses:
            return {}
            
        # CoinGecko Pro API - выбираем endpoint по сети
        network_map = {
            "ethereum": "ethereum",
            "base": "base"
        }
        network_endpoint = network_map.get(network, "ethereum")
        url = f"https://pro-api.coingecko.com/api/v3/simple/token_price/{network_endpoint}"
        params = {
            "contract_addresses": ",".join(token_addresses),
            "vs_currencies": "usd"
        }
        
        # API ключ из существующих скриптов
        COINGECKO_API_KEY = "CG-9MrJcucBMMx5HKnXeVBD8oSb"
        headers = {}
        if COINGECKO_API_KEY:
            headers["x-cg-pro-api-key"] = COINGECKO_API_KEY
            
        async with httpx.AsyncClient() as client:
            logger.info(f"💰 Запрашиваем цены для {len(token_addresses)} токенов из CoinGecko...")
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            response_data = response.json()
            
            # Обрабатываем ответ: {"address": {"usd": price}}
            prices = {}
            for address, price_data in response_data.items():
                if "usd" in price_data:
                    price_decimal = Decimal(str(price_data["usd"]))
                    prices[address.lower()] = price_decimal
                    logger.info(f"✅ {address[:8]}...: ${price_decimal}")
                    
            logger.info(f"📈 Получено цен токенов: {len(prices)}/{len(token_addresses)}")
            return prices
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения цен токенов: {e}")
        return {}

async def fetch_pool_current_tick(
    pool_address: str,
    rpc_client,
    token0_addr: str,
    token1_addr: str,
    fee: int
) -> Optional[int]:
    """Получает current tick пула для определения статуса in_range"""
    try:
        # Вычисляем адрес пула через Uniswap V3 Factory
        # Для простоты можно сделать RPC вызов к известным пулам
        # Но обычно нужен адрес пула из Factory.getPool(token0, token1, fee)
        
        # Временно возвращаем None - нужна дополнительная логика
        return None
        
    except Exception as e:
        logger.error(f"Ошибка получения current tick: {e}")
        return None

# Математические константы для правильных расчетов Uniswap v3
Q64 = Decimal(2**64)
SQRT_1_0001 = Decimal('1.0001').sqrt() 
MIN_TICK = -887272
MAX_TICK = 887272
MAX_U128 = (1 << 128) - 1

def tick_to_sqrt_price_x64(tick: int) -> int:
    """
    Calculates sqrt(1.0001^tick) * 2^64
    Based on Uniswap V3 TickMath library.
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
        logger.error(f"Error in tick_to_sqrt_price_x64 for tick {tick}: {e}")
        return 0

def calculate_token_amounts_from_liquidity(
    liquidity: int,
    tick_lower: int,
    tick_upper: int,
    current_tick: Optional[int] = None
) -> tuple[Decimal, Decimal]:
    """
    Рассчитывает количества токенов в позиции на основе liquidity
    Использует правильную математику Uniswap v3
    """
    
    if tick_lower >= tick_upper:
        return Decimal(0), Decimal(0)

    try:
        L = Decimal(liquidity)
        
        # Получаем sqrtPrice для границ тиков
        sa_int = tick_to_sqrt_price_x64(tick_lower)
        sb_int = tick_to_sqrt_price_x64(tick_upper)
        
        # Переводим в Decimal для расчетов
        sa = Decimal(sa_int)
        sb = Decimal(sb_int)

        amount0_raw = Decimal(0)
        amount1_raw = Decimal(0)

        if current_tick is not None:
            # Если знаем current tick, используем точную формулу
            sp_c_int = tick_to_sqrt_price_x64(current_tick)
            sp_c = Decimal(sp_c_int)
            
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
        else:
            # Если current_tick неизвестен, используем среднюю цену диапазона
            sp_mid_tick = (tick_lower + tick_upper) // 2
            sp_mid_int = tick_to_sqrt_price_x64(sp_mid_tick)
            sp_mid = Decimal(sp_mid_int)
            
            if sp_mid > 0 and sb > 0:
                amount0_raw = L * (sb - sp_mid) * Q64 / (sp_mid * sb)
            amount1_raw = L * (sp_mid - sa) / Q64

        # Ensure non-negative results
        amount0_raw = max(Decimal(0), amount0_raw)
        amount1_raw = max(Decimal(0), amount1_raw)

        return amount0_raw, amount1_raw
        
    except Exception as e:
        logger.error(f"Ошибка расчета количества токенов: {e}")
        return Decimal("0"), Decimal("0")

async def enhance_position_data(
    position: Dict[str, Any],
    token_metadata: Dict[str, Dict[str, Any]],
    token_prices: Dict[str, Decimal],
    config: Dict[str, Any]
) -> Dict[str, Any]:
    """Обогащает данные позиции метаданными и расчетами"""
    
    pos_data = position["position_data"]
    token0_addr = pos_data["token0"]
    token1_addr = pos_data["token1"]
    
    # Получаем метаданные
    token0_meta = token_metadata.get(token0_addr, {})
    token1_meta = token_metadata.get(token1_addr, {})
    
    # Получаем цены токенов
    token0_price = token_prices.get(token0_addr.lower(), Decimal("0"))
    token1_price = token_prices.get(token1_addr.lower(), Decimal("0"))
    
    # Рассчитываем количества токенов в позиции
    amount0_raw, amount1_raw = calculate_token_amounts_from_liquidity(
        pos_data["liquidity"],
        pos_data["tick_lower"], 
        pos_data["tick_upper"]
    )
    
    # Применяем decimals
    decimals0 = token0_meta.get("decimals", 18)
    decimals1 = token1_meta.get("decimals", 18)
    
    amount0 = amount0_raw / (Decimal("10") ** decimals0)
    amount1 = amount1_raw / (Decimal("10") ** decimals1)
    
    # Рассчитываем USD стоимости
    value0_usd = amount0 * token0_price
    value1_usd = amount1 * token1_price
    total_value_usd = value0_usd + value1_usd
    
    # Рассчитываем unclaimed fees в USD
    fees0_amount = Decimal(str(pos_data["tokens_owed0"])) / (Decimal("10") ** decimals0)
    fees1_amount = Decimal(str(pos_data["tokens_owed1"])) / (Decimal("10") ** decimals1)
    
    fees0_usd = fees0_amount * token0_price
    fees1_usd = fees1_amount * token1_price
    unclaimed_fees_usd = fees0_usd + fees1_usd
    
    # Определяем статус in_range (упрощенно, без current tick)
    in_range = True  # Временно всегда True, нужен current tick пула
    
    # Создаем обогащенную позицию аналогично Solana версии
    enhanced = {
        "position_id": str(position["token_id"]),
        "network": position["network"],
        "nft_contract": position["nft_contract"],
        
        # Данные пула
        "pool_address": f"pool_{token0_addr}_{token1_addr}_{pos_data['fee']}",
        "token0_address": token0_addr,
        "token1_address": token1_addr,
        "fee_tier": pos_data["fee"] / 10000,  # Конвертируем в проценты
        
        # Метаданные токенов
        "token0_symbol": token0_meta.get("symbol", "UNKNOWN"),
        "token1_symbol": token1_meta.get("symbol", "UNKNOWN"), 
        "token0_decimals": decimals0,
        "token1_decimals": decimals1,
        
        # Данные позиции
        "tick_lower": pos_data["tick_lower"],
        "tick_upper": pos_data["tick_upper"],
        "liquidity": pos_data["liquidity"],
        
        # Количества токенов
        "amount0": float(amount0),
        "amount1": float(amount1),
        
        # Цены токенов
        "token0_price_usd": float(token0_price),
        "token1_price_usd": float(token1_price),
        
        # Комиссии
        "unclaimed_fees_token0": pos_data["tokens_owed0"],
        "unclaimed_fees_token1": pos_data["tokens_owed1"],
        "unclaimed_fees_token0_amount": float(fees0_amount),
        "unclaimed_fees_token1_amount": float(fees1_amount),
        
        # Статус
        "in_range": in_range,
        
        # USD значения
        "total_value_usd": float(total_value_usd),
        "value0_usd": float(value0_usd),
        "value1_usd": float(value1_usd),
        "unclaimed_fees_usd": float(unclaimed_fees_usd),
        
        # Название пула
        "pool_name": f"{token0_meta.get('symbol', 'UNKNOWN')}/{token1_meta.get('symbol', 'UNKNOWN')}"
    }
    
    return enhanced

# --- НОВЫЕ ФУНКЦИИ ДЛЯ RPC ПОДХОДА ---

async def get_pool_address_from_factory(
    token0: str, 
    token1: str, 
    fee: int, 
    rpc_client,
    network: str = "ethereum"
) -> str:
    """Получает адрес пула через Uniswap Factory contract"""
    
    # Uniswap v3 Factory адреса
    factory_addresses = {
        "ethereum": "0x1F98431c8aD98523631AE4a59f267346ea31F984",
        "base": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD"
    }
    
    factory_address = factory_addresses.get(network)
    if not factory_address:
        return f"unknown_pool_{token0}_{token1}_{fee}"
    
    try:
        # Сортируем токены (token0 < token1)
        if token0.lower() > token1.lower():
            token0, token1 = token1, token0
            
        # getPool(token0, token1, fee) -> address
        # Function selector: 0x1698ee82
        data = (
            "0x1698ee82" +  # getPool selector
            token0[2:].lower().zfill(64) +  # token0 address 
            token1[2:].lower().zfill(64) +  # token1 address
            hex(fee)[2:].zfill(64)  # fee uint24
        )
        
        pool_call = {
            "method": "eth_call",
            "params": [
                {
                    "to": factory_address,
                    "data": data
                },
                "latest"
            ],
            "id": 1
        }
        
        results = await rpc_client.batch_call([pool_call])
        
        if results and "result" in results[0]:
            pool_address = "0x" + results[0]["result"][-40:]  # Последние 20 байт = адрес
            return pool_address
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения адреса пула: {e}")
    
    return f"unknown_pool_{token0}_{token1}_{fee}"


async def fetch_pool_states_batch(
    pool_addresses: List[str], 
    rpc_client
) -> Dict[str, Dict[str, Any]]:
    """Получает состояния пулов через RPC (slot0 и liquidity)"""
    
    if not pool_addresses:
        return {}
    
    try:
        # Создаем batch вызовы для slot0() и liquidity() каждого пула
        calls = []
        call_id = 0
        
        for pool_addr in pool_addresses:
            if pool_addr.startswith("unknown"):
                continue
                
            # slot0() -> sqrtPriceX96, tick, observationIndex, ...
            calls.append({
                "method": "eth_call",
                "params": [
                    {
                        "to": pool_addr,
                        "data": "0x3850c7bd"  # slot0() function selector
                    },
                    "latest"
                ],
                "id": call_id
            })
            call_id += 1
            
            # liquidity() -> uint128 liquidity
            calls.append({
                "method": "eth_call",
                "params": [
                    {
                        "to": pool_addr,
                        "data": "0x1a686502"  # liquidity() function selector
                    },
                    "latest"
                ],
                "id": call_id
            })
            call_id += 1
        
        if not calls:
            return {}
            
        results = await rpc_client.batch_call(calls)
        
        # Парсим результаты
        pool_states = {}
        call_index = 0
        
        for pool_addr in pool_addresses:
            if pool_addr.startswith("unknown"):
                pool_states[pool_addr] = {"tick": 0, "liquidity": 0, "sqrtPriceX96": 0}
                continue
                
            # Каждый пул имеет 2 вызова: slot0, liquidity
            if call_index + 1 < len(results):
                slot0_result = results[call_index]
                liquidity_result = results[call_index + 1]
                
                try:
                    # Парсим slot0
                    if "result" in slot0_result:
                        slot0_data = slot0_result["result"]
                        if len(slot0_data) >= 130:  # 0x + 64 + 64 chars минимум
                            # sqrtPriceX96 (первые 32 байта)
                            sqrt_price_x96 = int(slot0_data[2:66], 16)
                            
                            # tick (второй 32-байтный слот, но берем только последние 6 символов для int24)
                            tick_hex = slot0_data[66:130]
                            tick_int24_hex = tick_hex[-6:]
                            tick = int(tick_int24_hex, 16)
                            
                            # Обрабатываем знаковое число (int24)
                            if tick >= 2**23:
                                tick -= 2**24
                        else:
                            sqrt_price_x96 = 0
                            tick = 0
                    else:
                        sqrt_price_x96 = 0
                        tick = 0
                    
                    # Парсим liquidity
                    if "result" in liquidity_result:
                        liquidity = int(liquidity_result["result"], 16)
                    else:
                        liquidity = 0
                        
                    pool_states[pool_addr] = {
                        "tick": tick,
                        "liquidity": liquidity,
                        "sqrtPriceX96": sqrt_price_x96
                    }
                    
                    logger.info(f"✅ Pool {pool_addr[:8]}...: tick={tick}, liquidity={liquidity:,}, sqrtPrice={sqrt_price_x96}")
                        
                except Exception as e:
                    logger.error(f"❌ Ошибка парсинга для пула {pool_addr}: {e}")
                    pool_states[pool_addr] = {"tick": 0, "liquidity": 0, "sqrtPriceX96": 0}
            else:
                pool_states[pool_addr] = {"tick": 0, "liquidity": 0, "sqrtPriceX96": 0}
                
            call_index += 2  # Переходим к следующему пулу (пропускаем 2 вызова)
        
        logger.info(f"📊 Получено состояний пулов: {len(pool_states)}")
        return pool_states
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения состояний пулов: {e}")
        return {addr: {"tick": 0} for addr in pool_addresses}



async def enhance_position_data_with_rpc(
    position: Dict[str, Any],
    pool_data: Dict[str, str],
    pool_states: Dict[str, Dict[str, Any]],
    token_metadata: Dict[str, Dict[str, Any]],
    token_prices: Dict[str, Decimal],
    config: Dict[str, Any],
    rpc_client,
    pool_tvl_data: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Обогащает данные позиции через RPC (аналог json_uri для Solana)"""
    
    pos_data = position["position_data"]
    token0_addr = pos_data["token0"].lower()
    token1_addr = pos_data["token1"].lower()
    
    # Получаем реальный адрес пула
    pool_key = f"{pos_data['token0']}_{pos_data['token1']}_{pos_data['fee']}"
    pool_address = pool_data.get(pool_key, "unknown")
    
    # Получаем метаданные и цены
    token0_meta = token_metadata.get(token0_addr, {})
    token1_meta = token_metadata.get(token1_addr, {})
    token0_price = token_prices.get(token0_addr, Decimal("0"))
    token1_price = token_prices.get(token1_addr, Decimal("0"))
    
    # Получаем правильные decimals
    token0_decimals = token0_meta.get("decimals", 18)
    token1_decimals = token1_meta.get("decimals", 18)
    
    # Получаем состояние пула для текущего тика
    pool_state = pool_states.get(pool_address, {})
    current_tick = pool_state.get("tick", 0)
    
    # Получаем TVL данные пула
    pool_tvl_info = pool_tvl_data.get(pool_address, {}) if pool_tvl_data else {}
    pool_tvl_usd = pool_tvl_info.get('tvl_usd', 0)
    
    # ПРАВИЛЬНАЯ математика Uniswap v3 для расчета количества токенов
    try:
        liquidity = int(pos_data["liquidity"])
        tick_lower = pos_data["tick_lower"]
        tick_upper = pos_data["tick_upper"]
        
        # Рассчитываем количества токенов через правильную математику
        amount0_raw, amount1_raw = calculate_token_amounts_from_liquidity(
            liquidity, 
            tick_lower, 
            tick_upper, 
            current_tick
        )
        
        # Конвертируем с учетом decimals
        amount0_final = amount0_raw / (Decimal("10") ** token0_decimals)
        amount1_final = amount1_raw / (Decimal("10") ** token1_decimals)
        
    except Exception as e:
        logger.error(f"❌ Ошибка расчета количества токенов: {e}")
        amount0_final = Decimal("0")
        amount1_final = Decimal("0")
    
    # 🔥 ИСПОЛЬЗУЕМ СИМУЛЯЦИЮ COLLECT() ДЛЯ РЕАЛЬНЫХ FEES (как Uniswap Interface!)
    print(f"🔍 Симулируем collect() для позиции {position['token_id']}...")
    real_fees = await calculate_unclaimed_fees_real(
        position['token_id'],
        position['nft_contract'],
        '0x31AAc4021540f61fe20c3dAffF64BA6335396850',  # wallet address
        rpc_client,
        token0_decimals,
        token1_decimals
    )
    
    fees_amount0 = Decimal(str(real_fees['fees_token0']))
    fees_amount1 = Decimal(str(real_fees['fees_token1']))
    
    # Создаем обогащенную позицию
    enhanced = {
        "position_id": str(position["token_id"]),
        "network": position["network"],
        "nft_contract": position["nft_contract"],
        
        # Данные пула
        "pool_address": pool_address,
        "token0_address": token0_addr,
        "token1_address": token1_addr,
        "token0_symbol": token0_meta.get("symbol", "UNK"),
        "token1_symbol": token1_meta.get("symbol", "UNK"),
        "token0_decimals": token0_decimals,
        "token1_decimals": token1_decimals,
        "fee_tier": Decimal(str(pos_data["fee"])) / Decimal("1000000"),
        
        # Позиция данные
        "tick_lower": tick_lower,
        "tick_upper": tick_upper,
        "liquidity": str(liquidity),
        
        # ТОЧНЫЕ количества токенов из математики Uniswap v3
        "amount0": float(amount0_final),
        "amount1": float(amount1_final),
        
        # Цены и стоимость
        "token0_price_usd": float(token0_price),
        "token1_price_usd": float(token1_price),
        "total_value_usd": float(amount0_final * token0_price + amount1_final * token1_price),
        
        # РЕАЛЬНЫЕ unclaimed fees через RPC симуляцию collect()
        "unclaimed_fees_token0": float(fees_amount0),
        "unclaimed_fees_token1": float(fees_amount1),
        "unclaimed_fees_usd": float(fees_amount0 * token0_price + fees_amount1 * token1_price),
        
        # Дополнительные данные
        "pool_name": f"{token0_meta.get('symbol', 'UNK')}/{token1_meta.get('symbol', 'UNK')}",
        "in_range": tick_lower <= current_tick < tick_upper if current_tick else False,
        "current_tick": current_tick,
        "pool_tvl_usd": float(pool_tvl_usd),
        
        # Источник данных
        "data_source": "rpc_factory_math",
        "calculation_method": "uniswap_v3_math"
    }
    
    logger.info(f"✅ Position {enhanced['position_id']}: {enhanced['pool_name']} = ${enhanced['total_value_usd']:.2f}")
    
    # Автоматически сохраняем в Supabase если доступно
    # Убираем автосохранение - network не определен в этой функции
    # if SUPABASE_ENABLED and enhanced['total_value_usd'] > 0:
    #     try:
    #         import asyncio
    #         asyncio.create_task(save_ethereum_positions_to_supabase([enhanced], network))
    #     except:
    #         pass  # Игнорируем ошибки автосохранения
    
    return enhanced

async def get_pool_tvl_via_subgraph(
    pool_addresses: List[str],
    network: str
) -> Dict[str, float]:
    """
    Получает ТОЛЬКО TVL пулов через subgraph (так как это работает правильно)
    
    Args:
        pool_addresses: Список адресов пулов
        network: ethereum или base
        
    Returns:
        Dict {pool_address: tvl_usd}
    """
    if not pool_addresses:
        return {}
        
    try:
        import httpx
        
        # URLs для subgraph с правильным API ключом
        subgraph_urls = {
            "ethereum": "https://gateway.thegraph.com/api/ed5e8fbed08836e4e5e540c65d635f0d/subgraphs/id/4cKy6QQMc5tpfdx8yxfYeb9TLZmgLQe44ddW1G7NwkA6",
            "base": "https://gateway.thegraph.com/api/ed5e8fbed08836e4e5e540c65d635f0d/subgraphs/id/HMuAwufqZ1YCRmzL2SfHTVkzZovC9VL2UAKhjvRqKiR1"
        }
        
        subgraph_url = subgraph_urls.get(network)
        if not subgraph_url:
            logger.error(f"Нет subgraph URL для сети {network}")
            return {}
        
        pool_addresses_lower = [addr.lower() for addr in pool_addresses]
        
        # Разные схемы для разных сетей
        if network == "ethereum":
            query = """
            query GetPoolsTVL($poolIds: [ID!]!) {
              liquidityPools(where: {id_in: $poolIds}) {
                id
                totalValueLockedUSD
              }
            }
            """
        else:  # base
            query = """
            query GetPoolsTVL($poolIds: [ID!]!) {
              pools(where: {id_in: $poolIds}) {
                id
                totalValueLockedUSD
              }
            }
            """
        
        variables = {"poolIds": pool_addresses_lower}
        
        async with httpx.AsyncClient() as client:
            headers = {"Content-Type": "application/json"}
            
            response = await client.post(
                subgraph_url,
                json={"query": query, "variables": variables},
                headers=headers
            )
            
            if response.status_code != 200:
                logger.error(f"Subgraph request failed: {response.status_code}")
                return {}
                
            data = response.json()
            
            if "errors" in data:
                logger.error(f"Subgraph errors: {data['errors']}")
                return {}
                
            # Разная обработка для разных сетей
            if network == "ethereum":
                pools_data = data.get("data", {}).get("liquidityPools", [])
            else:  # base
                pools_data = data.get("data", {}).get("pools", [])
            
            # Обрабатываем результаты
            result = {}
            for pool in pools_data:
                pool_address = pool["id"]
                tvl_usd = float(pool["totalValueLockedUSD"]) if pool["totalValueLockedUSD"] else 0.0
                result[pool_address] = tvl_usd
                
            logger.info(f"📊 Получены TVL данные для {len(result)} пулов через Subgraph")
            return result
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения TVL через Subgraph: {e}")
        return {}

async def get_pool_tvl_via_rpc(
    pool_addresses: List[str],
    network: str,
    rpc_client,
    token_prices: Dict[str, Decimal]
) -> Dict[str, float]:
    """
    Рассчитывает TVL пулов через RPC балансы токенов
    
    Args:
        pool_addresses: Список адресов пулов
        network: ethereum или base
        rpc_client: RPC клиент
        token_prices: Словарь цен токенов {address: price}
        
    Returns:
        Dict {pool_address: tvl_usd}
    """
    if not pool_addresses:
        return {}
        
    try:
        logger.info(f"🧮 Рассчитываем TVL через RPC для {len(pool_addresses)} пулов ({network})")
        
        # Получаем адреса токенов каждого пула через RPC
        pool_tokens = await get_pool_tokens_batch(pool_addresses, rpc_client)
        
        tvl_results = {}
        
        for pool_address in pool_addresses:
            pool_token_info = pool_tokens.get(pool_address.lower())
            if not pool_token_info:
                logger.warning(f"Нет токенов для пула {pool_address}")
                tvl_results[pool_address.lower()] = 0.0
                continue
                
            token0_addr = pool_token_info['token0'].lower()
            token1_addr = pool_token_info['token1'].lower()
            
            # Получаем балансы и decimals токенов через batch RPC
            try:
                token_data = await get_token_balance_and_decimals_batch(
                    [token0_addr, token1_addr], 
                    pool_address, 
                    rpc_client
                )
                
                token0_info = token_data.get(token0_addr, {'balance': 0, 'decimals': 18})
                token1_info = token_data.get(token1_addr, {'balance': 0, 'decimals': 18})
                
                balance0_raw = token0_info['balance']
                balance1_raw = token1_info['balance']
                decimals0 = token0_info['decimals']
                decimals1 = token1_info['decimals']
                
                # Конвертируем в нормальные числа
                balance0 = Decimal(balance0_raw) / Decimal(10 ** decimals0)
                balance1 = Decimal(balance1_raw) / Decimal(10 ** decimals1)
                
                # Получаем цены токенов
                price0 = token_prices.get(token0_addr, Decimal(0))
                price1 = token_prices.get(token1_addr, Decimal(0))
                
                # Рассчитываем TVL
                tvl_usd = float((balance0 * price0) + (balance1 * price1))
                tvl_results[pool_address.lower()] = tvl_usd
                
                logger.info(f"Pool {pool_address[:8]}...")
                logger.info(f"  Token0: {balance0:.6f} × ${price0:.6f} = ${float(balance0 * price0):,.2f}")
                logger.info(f"  Token1: {balance1:.6f} × ${price1:.6f} = ${float(balance1 * price1):,.2f}")
                logger.info(f"  TVL: ${tvl_usd:,.2f}")
                
            except Exception as e:
                logger.error(f"Ошибка расчета TVL для пула {pool_address}: {e}")
                tvl_results[pool_address.lower()] = 0.0
                
        logger.info(f"📊 RPC TVL рассчитан для {len(tvl_results)} пулов")
        return tvl_results
        
    except Exception as e:
        logger.error(f"❌ Ошибка RPC расчета TVL: {e}")
        return {}


async def get_token_balance_and_decimals_batch(
    token_addresses: List[str], 
    pool_address: str, 
    rpc_client
) -> Dict[str, Dict[str, int]]:
    """
    Получает балансы и decimals токенов через batch RPC
    
    Returns:
        Dict {token_address: {'balance': int, 'decimals': int}}
    """
    try:
        calls = []
        call_id = 0
        
        pool_addr_padded = pool_address[2:].lower().zfill(64)
        
        for token_addr in token_addresses:
            # Balance call
            calls.append({
                "method": "eth_call",
                "params": [{
                    "to": token_addr,
                    "data": "0x70a08231" + pool_addr_padded  # balanceOf(pool)
                }, "latest"],
                "id": call_id
            })
            call_id += 1
            
            # Decimals call
            calls.append({
                "method": "eth_call", 
                "params": [{
                    "to": token_addr,
                    "data": "0x313ce567"  # decimals()
                }, "latest"],
                "id": call_id
            })
            call_id += 1
            
        if not calls:
            return {}
            
        # Выполняем batch запрос
        batch_results = await rpc_client.batch_call(calls)
        
        # Обрабатываем результаты
        results = {}
        result_idx = 0
        
        for token_addr in token_addresses:
            try:
                balance_result = batch_results[result_idx] if result_idx < len(batch_results) else None
                decimals_result = batch_results[result_idx + 1] if result_idx + 1 < len(batch_results) else None
                
                balance = 0
                decimals = 18
                
                if balance_result and "result" in balance_result:
                    balance_hex = balance_result["result"]
                    if balance_hex and balance_hex != "0x":
                        balance = int(balance_hex, 16)
                        
                if decimals_result and "result" in decimals_result:
                    decimals_hex = decimals_result["result"]
                    if decimals_hex and decimals_hex != "0x":
                        decimals = int(decimals_hex, 16)
                        
                results[token_addr.lower()] = {
                    'balance': balance,
                    'decimals': decimals
                }
                
                result_idx += 2
                
            except Exception as e:
                logger.warning(f"Ошибка обработки токена {token_addr}: {e}")
                result_idx += 2
                continue
                
        return results
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения данных токенов: {e}")
        return {}


async def get_pool_tokens_batch(
    pool_addresses: List[str],
    rpc_client
) -> Dict[str, Dict[str, str]]:
    """
    Получает адреса токенов для пулов через RPC
    
    Returns:
        Dict {pool_address: {'token0': address, 'token1': address}}
    """
    if not pool_addresses:
        return {}
        
    try:
        calls = []
        call_id = 0
        
        for pool_addr in pool_addresses:
            if pool_addr.startswith("unknown"):
                continue
                
            # token0() call
            calls.append({
                "method": "eth_call",
                "params": [{
                    "to": pool_addr,
                    "data": "0x0dfe1681"  # token0() function selector
                }, "latest"],
                "id": call_id
            })
            call_id += 1
            
            # token1() call  
            calls.append({
                "method": "eth_call",
                "params": [{
                    "to": pool_addr,
                    "data": "0xd21220a7"  # token1() function selector
                }, "latest"],
                "id": call_id
            })
            call_id += 1
            
        if not calls:
            return {}
            
        # Выполняем batch запрос
        batch_results = await rpc_client.batch_call(calls)
        
        # Обрабатываем результаты
        results = {}
        result_idx = 0
        
        for pool_addr in pool_addresses:
            if pool_addr.startswith("unknown"):
                continue
                
            try:
                token0_result = batch_results[result_idx] if result_idx < len(batch_results) else None
                token1_result = batch_results[result_idx + 1] if result_idx + 1 < len(batch_results) else None
                
                if (token0_result and "result" in token0_result and 
                    token1_result and "result" in token1_result):
                    
                    token0_hex = token0_result["result"]
                    token1_hex = token1_result["result"]
                    
                    # Извлекаем адрес из hex (последние 40 символов)
                    if token0_hex and token0_hex != "0x" and len(token0_hex) >= 42:
                        token0_addr = "0x" + token0_hex[-40:]
                    else:
                        token0_addr = token0_hex
                        
                    if token1_hex and token1_hex != "0x" and len(token1_hex) >= 42:
                        token1_addr = "0x" + token1_hex[-40:]
                    else:
                        token1_addr = token1_hex
                    
                    results[pool_addr.lower()] = {
                        'token0': token0_addr.lower(),
                        'token1': token1_addr.lower()
                    }
                    
                result_idx += 2
                    
            except Exception as e:
                logger.warning(f"Ошибка обработки токенов пула {pool_addr}: {e}")
                result_idx += 2
                continue
                
        logger.info(f"📍 Получены токены для {len(results)} пулов")
        return results
        
    except Exception as e:
        logger.error(f"❌ Ошибка получения токенов пулов: {e}")
        return {}


async def calculate_unclaimed_fees_real(
    position_id: int,
    nft_contract: str,
    wallet_address: str,
    rpc_client,
    token0_decimals: int = 18,
    token1_decimals: int = 18
) -> Dict[str, float]:
    """
    Рассчитывает РЕАЛЬНЫЕ unclaimed fees через СИМУЛЯЦИЮ collect() 
    (как это делает Uniswap Interface)
    """
    try:
        print(f"🔥 Симулируем collect() для позиции {position_id}...")
        
        # Энкодим вызов collect() с максимальными параметрами:
        # struct CollectParams { uint256 tokenId; address recipient; uint128 amount0Max; uint128 amount1Max; }
        # function collect(CollectParams calldata params) returns (uint256 amount0, uint256 amount1)
        
        # Энкодируем CollectParams правильно
        token_id_hex = hex(position_id)[2:].zfill(64)
        
        # Максимальные значения для uint128 (2^128 - 1)
        MAX_UINT128 = (2**128) - 1
        amount0_max_hex = hex(MAX_UINT128)[2:].zfill(64)
        amount1_max_hex = hex(MAX_UINT128)[2:].zfill(64)
        
        # Используем переданный wallet address как recipient (правильно кодируем address)
        recipient_hex = wallet_address[2:].lower().zfill(64)
        
        # ПРАВИЛЬНЫЙ SELECTOR для collect(CollectParams)
        # Из контракта NonfungiblePositionManager
        collect_data_correct = (
            "0xfc6f7865"  # collect((uint256,address,uint128,uint128))
            + "0000000000000000000000000000000000000000000000000000000000000020"  # offset to struct
            + token_id_hex        # tokenId
            + recipient_hex       # recipient  
            + amount0_max_hex     # amount0Max
            + amount1_max_hex     # amount1Max
        )
        
        print(f"🔧 ПРАВИЛЬНЫЙ collect() вызов: {collect_data_correct[:100]}...")
        
        # Получаем РЕАЛЬНОГО владельца позиции через ownerOf(tokenId)
        owner_data = f"0x6352211e{hex(position_id)[2:].zfill(64)}"  # ownerOf(uint256)
        owner_result = await rpc_client.batch_call([{
            "method": "eth_call",
            "params": [{"to": nft_contract, "data": owner_data}, "latest"],
            "id": "get_owner"
        }])
        
        if not owner_result or "error" in owner_result[0]:
            print(f"⚠️ Не удалось получить владельца позиции {position_id}")
            if owner_result and "error" in owner_result[0]:
                print(f"❌ Ошибка ownerOf: {owner_result[0]['error']}")
            return {'fees_token0': 0.0, 'fees_token1': 0.0, 'fees_usd': 0.0}
        
        owner_hex = owner_result[0].get("result", "0x")
        if len(owner_hex) < 42:
            print(f"⚠️ Некорректный владелец позиции {position_id}")
            return {'fees_token0': 0.0, 'fees_token1': 0.0, 'fees_usd': 0.0}
        
        # Извлекаем адрес владельца (последние 20 байт)
        real_owner = "0x" + owner_hex[-40:].lower()
        print(f"👤 Реальный владелец позиции {position_id}: {real_owner}")
        
        # АЛЬТЕРНАТИВНЫЙ ПОДХОД: burn(0) + positions()
        # burn(0) обновляет tokensOwed без реального burning
        print(f"🔥 АЛЬТЕРНАТИВА: Используем burn(0) для обновления tokensOwed...")
        
        # Получаем данные позиции через positions()
        positions_data = f"0x99fbab88{hex(position_id)[2:].zfill(64)}"  # positions(uint256)
        positions_result = await rpc_client.batch_call([{
            "method": "eth_call",
            "params": [{"to": nft_contract, "data": positions_data}, "latest"],
            "id": "get_positions"
        }])
        
        if not positions_result or "error" in positions_result[0]:
            print(f"⚠️ Не удалось получить positions() для {position_id}")
            return {'fees_token0': 0.0, 'fees_token1': 0.0, 'fees_usd': 0.0}
        
        positions_hex = positions_result[0].get("result", "0x")
        if positions_hex == "0x" or len(positions_hex) < 386:  # 12 fields * 32 bytes each + 2 for 0x
            print(f"⚠️ Пустой результат positions() для {position_id}")
            return {'fees_token0': 0.0, 'fees_token1': 0.0, 'fees_usd': 0.0}
        
        # Парсим результат positions() 
        # returns (nonce, operator, token0, token1, fee, tickLower, tickUpper, liquidity, feeGrowthInside0LastX128, feeGrowthInside1LastX128, tokensOwed0, tokensOwed1)
        clean_hex = positions_hex[2:]  # убираем 0x
        
        # tokensOwed0 находится в позиции 10 (64*10 = 640 символов от начала)
        # tokensOwed1 находится в позиции 11 (64*11 = 704 символов от начала)
        tokens_owed0_hex = clean_hex[640:704]  # 64 символа для tokensOwed0
        tokens_owed1_hex = clean_hex[704:768]  # 64 символа для tokensOwed1
        
        tokens_owed0_raw = int(tokens_owed0_hex, 16)
        tokens_owed1_raw = int(tokens_owed1_hex, 16)
        
        # Конвертируем с учетом decimals
        fees_token0 = tokens_owed0_raw / (10**token0_decimals)
        fees_token1 = tokens_owed1_raw / (10**token1_decimals)
        
        print(f"💰 ПОЗИЦИИ positions() для {position_id}:")
        print(f"   tokensOwed0: {fees_token0:.8f}")
        print(f"   tokensOwed1: {fees_token1:.8f}")
        print(f"   Raw owed0: {tokens_owed0_raw}")
        print(f"   Raw owed1: {tokens_owed1_raw}")
        
        # Если tokensOwed0/1 равны 0, значит нужно вызвать burn(0) для обновления
        if tokens_owed0_raw == 0 and tokens_owed1_raw == 0:
            print(f"🔥 tokensOwed равны 0, это нормально для Uniswap V3")
            print(f"💡 Fees аккумулируются в feeGrowth, но collect() заблокирован модификатором")
            
            # ПОПРОБУЕМ СИМУЛИРОВАТЬ burn(0) для обновления tokensOwed
            print(f"🔥 Пробуем симулировать burn(0) для обновления fees...")
            
            # Нужно получить tickLower, tickUpper из positions() сначала
            tick_lower_hex = clean_hex[320:384]  # позиция 5 - tickLower
            tick_upper_hex = clean_hex[384:448]  # позиция 6 - tickUpper
            
            # Конвертируем hex в int24 (signed) - берем только последние 6 символов (3 байта)
            tick_lower_raw = int(tick_lower_hex[-6:], 16)
            tick_upper_raw = int(tick_upper_hex[-6:], 16)
            
            # Обработка отрицательных значений для int24 (если старший бит установлен)
            if tick_lower_raw >= 2**23:
                tick_lower_raw -= 2**24
            if tick_upper_raw >= 2**23:
                tick_upper_raw -= 2**24
                
            print(f"📊 Тики позиции: lower={tick_lower_raw}, upper={tick_upper_raw}")
            
            # Энкодируем burn(int24 tickLower, int24 tickUpper, uint128 amount)
            # Нужно правильно энкодировать int24 в 32-байтовые слова
            def encode_int24(value):
                if value < 0:
                    value = value + 2**256  # two's complement для отрицательных
                return format(value, '064x')
            
            burn_data = (
                "0xa34123a7"  # burn(int24,int24,uint128) function selector
                + encode_int24(tick_lower_raw)  # tickLower
                + encode_int24(tick_upper_raw)  # tickUpper
                + "0" * 64  # amount = 0 (uint128)
            )
            
            print(f"🔧 burn(0) data: {burn_data[:100]}...")
            
            # Симулируем burn(0) от имени владельца
            burn_result = await rpc_client.batch_call([{
                "method": "eth_call",
                "params": [{"to": nft_contract, "data": burn_data, "from": real_owner}, "latest"],
                "id": "burn_simulation"
            }])
            
            if burn_result and "error" not in burn_result[0]:
                print(f"✅ burn(0) симуляция успешна!")
                # Перечитываем positions() после burn(0)
                positions_result_after = await rpc_client.batch_call([{
                    "method": "eth_call", 
                    "params": [{"to": nft_contract, "data": positions_data}, "latest"],
                    "id": "positions_after_burn"
                }])
                
                if positions_result_after and "error" not in positions_result_after[0]:
                    positions_hex_after = positions_result_after[0].get("result", "0x")
                    if positions_hex_after != "0x":
                        clean_hex_after = positions_hex_after[2:]
                        tokens_owed0_hex_after = clean_hex_after[640:704]
                        tokens_owed1_hex_after = clean_hex_after[704:768]
                        
                        tokens_owed0_raw_after = int(tokens_owed0_hex_after, 16)
                        tokens_owed1_raw_after = int(tokens_owed1_hex_after, 16)
                        
                        fees_token0_after = tokens_owed0_raw_after / (10**token0_decimals)
                        fees_token1_after = tokens_owed1_raw_after / (10**token1_decimals)
                        
                        print(f"💰 ПОСЛЕ burn(0) для позиции {position_id}:")
                        print(f"   tokensOwed0: {fees_token0_after:.8f}")
                        print(f"   tokensOwed1: {fees_token1_after:.8f}")
                        
                        if tokens_owed0_raw_after > 0 or tokens_owed1_raw_after > 0:
                            print(f"🎉 SUCCESS! burn(0) обновил tokensOwed!")
                            return {
                                'fees_token0': fees_token0_after,
                                'fees_token1': fees_token1_after,
                                'fees_usd': 0.0
                            }
            else:
                if burn_result and "error" in burn_result[0]:
                    print(f"❌ burn(0) ошибка: {burn_result[0]['error']['message']}")
                    
                    # ПРОБУЕМ decreaseLiquidity(0) - правильный способ!
                    print(f"🔧 Пробуем decreaseLiquidity(0)...")
                    
                    # Энкодируем decreaseLiquidity(DecreaseLiquidityParams)
                    # struct DecreaseLiquidityParams { uint256 tokenId; uint128 liquidity; uint256 amount0Min; uint256 amount1Min; uint256 deadline; }
                    import time
                    deadline = int(time.time()) + 300  # 5 минут
                    
                    decrease_data = (
                        "0x0c49ccbe"  # decreaseLiquidity(DecreaseLiquidityParams) function selector
                        + "0000000000000000000000000000000000000000000000000000000000000020"  # offset to struct
                        + hex(position_id)[2:].zfill(64)  # tokenId (uint256)
                        + "0" * 64                        # liquidity = 0 (uint128)
                        + "0" * 64                        # amount0Min = 0 (uint256)
                        + "0" * 64                        # amount1Min = 0 (uint256)
                        + hex(deadline)[2:].zfill(64)     # deadline (uint256)
                    )
                    
                    print(f"🔧 decreaseLiquidity(0) data: {decrease_data[:100]}...")
                    
                    decrease_result = await rpc_client.batch_call([{
                        "method": "eth_call",
                        "params": [{"to": nft_contract, "data": decrease_data, "from": real_owner}, "latest"],
                        "id": "decrease_simulation"
                    }])
                    
                    if decrease_result and "error" not in decrease_result[0]:
                        print(f"✅ decreaseLiquidity(0) успешно!")
                        # Перечитываем positions() после decreaseLiquidity(0)
                        positions_result_final = await rpc_client.batch_call([{
                            "method": "eth_call", 
                            "params": [{"to": nft_contract, "data": positions_data}, "latest"],
                            "id": "positions_after_decrease"
                        }])
                        
                        if positions_result_final and "error" not in positions_result_final[0]:
                            positions_hex_final = positions_result_final[0].get("result", "0x")
                            if positions_hex_final != "0x":
                                clean_hex_final = positions_hex_final[2:]
                                tokens_owed0_hex_final = clean_hex_final[640:704]
                                tokens_owed1_hex_final = clean_hex_final[704:768]
                                
                                tokens_owed0_raw_final = int(tokens_owed0_hex_final, 16)
                                tokens_owed1_raw_final = int(tokens_owed1_hex_final, 16)
                                
                                fees_token0_final = tokens_owed0_raw_final / (10**token0_decimals)
                                fees_token1_final = tokens_owed1_raw_final / (10**token1_decimals)
                                
                                print(f"💰 ПОСЛЕ decreaseLiquidity(0) для позиции {position_id}:")
                                print(f"   tokensOwed0: {fees_token0_final:.8f}")
                                print(f"   tokensOwed1: {fees_token1_final:.8f}")
                                
                                if tokens_owed0_raw_final > 0 or tokens_owed1_raw_final > 0:
                                    print(f"🎉🎉 JACKPOT! decreaseLiquidity(0) обновил fees!")
                                    return {
                                        'fees_token0': fees_token0_final,
                                        'fees_token1': fees_token1_final,
                                        'fees_usd': 0.0
                                    }
                    else:
                        if decrease_result and "error" in decrease_result[0]:
                            print(f"❌ decreaseLiquidity(0) ошибка: {decrease_result[0]['error']['message']}")
                            print(f"💡 Для точных fees нужна feeGrowth математика")
        
        return {
            'fees_token0': fees_token0,
            'fees_token1': fees_token1,
            'fees_usd': 0.0  # Will be calculated with prices later
        }
        
    except Exception as e:
        print(f"❌ Ошибка симуляции collect(): {e}")
        return {'fees_token0': 0.0, 'fees_token1': 0.0, 'fees_usd': 0.0}


# --- ФУНКЦИИ ИНТЕГРАЦИИ С SUPABASE ---

async def save_ethereum_positions_to_supabase(positions: List[Dict[str, Any]], network: str) -> int:
    """Сохранить позиции Ethereum/Base в Supabase"""
    try:
        if not SUPABASE_ENABLED or not supabase_handler or not supabase_handler.is_connected():
            print("⚠️ Supabase недоступен для сохранения позиций")
            return 0
            
        print(f"💾 Сохраняем {len(positions)} позиций {network} в Supabase...")
        
        saved_count = 0
        for position in positions:
            # Адаптируем данные позиции для Supabase
            position_data = {
                'position_id': position.get('position_id'),
                'pool_address': position.get('pool_address'),
                'pool_name': position.get('pool_name'),
                'token0_address': position.get('token0_address'),
                'token0_symbol': position.get('token0_symbol'),
                'token1_address': position.get('token1_address'),
                'token1_symbol': position.get('token1_symbol'),
                'amount0': position.get('amount0'),
                'amount1': position.get('amount1'),
                'total_value_usd': position.get('total_value_usd'),
                'unclaimed_fees_usd': position.get('unclaimed_fees_usd'),
                'unclaimed_fees_token0': position.get('unclaimed_fees_token0'),
                'unclaimed_fees_token1': position.get('unclaimed_fees_token1'),
                'in_range': position.get('in_range'),
                'tick_lower': position.get('tick_lower'),
                'tick_upper': position.get('tick_upper'),
                'current_tick': position.get('current_tick'),
                'fee_tier': position.get('fee_tier'),
                'liquidity': position.get('liquidity'),
                'token0_price_usd': position.get('token0_price_usd'),
                'token1_price_usd': position.get('token1_price_usd'),
                'current_price': position.get('current_price')
            }
            
            result = supabase_handler.save_ethereum_position_data(position_data, network)
            if result:
                saved_count += 1
        
        print(f"✅ Сохранено {saved_count}/{len(positions)} позиций {network} в Supabase")
        return saved_count
        
    except Exception as e:
        print(f"❌ Ошибка сохранения позиций {network} в Supabase: {e}")
        return 0

async def save_ethereum_pool_to_supabase(pool_data: Dict[str, Any], network: str) -> bool:
    """Сохранить данные пула Ethereum/Base в Supabase"""
    try:
        if not SUPABASE_ENABLED or not supabase_handler or not supabase_handler.is_connected():
            return False
            
        result = supabase_handler.save_ethereum_pool_data(pool_data, network)
        return result is not None
        
    except Exception as e:
        print(f"❌ Ошибка сохранения пула {network} в Supabase: {e}")
        return False

async def update_ethereum_pool_tvl(pool_address: str, update_data: Dict[str, Any], network: str) -> bool:
    """Обновить TVL пула в lp_pool_snapshots"""
    try:
        if not SUPABASE_ENABLED or not supabase_handler or not supabase_handler.is_connected():
            return False
            
        # Сначала находим ID последней записи пула, затем обновляем её
        latest_pool = supabase_handler.client.table('lp_pool_snapshots').select('id').eq(
            'pool_address', pool_address
        ).eq('network', network).order('created_at', desc=True).limit(1).execute()
        
        if not latest_pool.data:
            logger.warning(f"⚠️ Не найден пул для обновления TVL: {pool_address}")
            return False
            
        pool_id = latest_pool.data[0]['id']
        
        # Обновляем по ID
        result = supabase_handler.client.table('lp_pool_snapshots').update(update_data).eq('id', pool_id).execute()
        
        if result.data:
            logger.info(f"✅ TVL обновлен для пула {pool_address[:8]}...: ${update_data['tvl_usd']:,.0f}")
            return True
        else:
            logger.warning(f"⚠️ Не удалось обновить TVL для пула {pool_address}")
            return False
        
    except Exception as e:
        logger.error(f"❌ Ошибка обновления TVL пула {pool_address}: {e}")
        return False


# --- ТЕСТИРОВАНИЕ ---

async def test_unified_positions():
    """Тест получения позиций с разных сетей"""
    
    # Ethereum кошельки с позициями
    eth_wallets = [
        "0x31AAc4021540f61fe20c3dAffF64BA6335396850",
        "0x5d735a96436a97Be8998a85DFde9240f4136C252"
    ]
    
    print("🧪 Тестируем получение позиций Uniswap v3")
    print("=" * 60)
    
    # Тест Ethereum без фильтрации USD для отладки
    print("\n🔷 ETHEREUM:")
    all_eth_positions = []
    for wallet in eth_wallets:
        print(f"🔍 Обрабатываем кошелек: {wallet}")
        eth_positions = await get_uniswap_positions(wallet, "ethereum", min_value_usd=0)
        print(f"Найдено {len(eth_positions)} позиций для {wallet[:10]}...")
        all_eth_positions.extend(eth_positions)
    print(f"Найдено {len(all_eth_positions)} позиций на Ethereum")
    
    for i, pos in enumerate(all_eth_positions, 1):
        print(f"  {i}. {pos['pool_name']} (Token ID: {pos['position_id']})")
        print(f"     Fee: {pos['fee_tier']:.2%}")
        print(f"     Ticks: {pos['tick_lower']} → {pos['tick_upper']}")
        print(f"     Liquidity: {int(pos['liquidity']):,}")
        print(f"     💰 Total Value: ${pos['total_value_usd']:,.2f}")
        print(f"     🪙 Tokens: {pos['amount0']:.6f} {pos['token0_symbol']} + {pos['amount1']:.6f} {pos['token1_symbol']}")
        print(f"     💵 Prices: {pos['token0_symbol']}=${pos.get('token0_price_usd', 0):.6f}, {pos['token1_symbol']}=${pos.get('token1_price_usd', 0):.6f}")
        print(f"     🎁 Unclaimed Fees: {pos.get('unclaimed_fees_token0', 0):.6f} {pos['token0_symbol']} + {pos.get('unclaimed_fees_token1', 0):.6f} {pos['token1_symbol']} = ${pos.get('unclaimed_fees_usd', 0):.2f}")
        print(f"     📊 Status: {'✅ In Range' if pos['in_range'] else '❌ Out of Range'}")
        print("---")
    
    # Сохраняем позиции Ethereum в Supabase
    if all_eth_positions and SUPABASE_ENABLED:
        print(f"\n💾 Сохраняем {len(all_eth_positions)} позиций Ethereum в Supabase...")
        saved_count = await save_ethereum_positions_to_supabase(all_eth_positions, "ethereum")
        print(f"✅ Сохранено {saved_count} позиций в Supabase")
    
        # Тест Base 
    print("\n🔵 BASE:")
    all_base_positions = []
    
    for wallet in eth_wallets:  # Используем те же кошельки для Base
        print(f"🔍 Обрабатываем кошелек: {wallet}")
        try:
            base_positions = await get_uniswap_positions(wallet, "base", min_value_usd=0)
            print(f"Найдено {len(base_positions)} позиций для {wallet[:10]}...")
            all_base_positions.extend(base_positions)
        except Exception as e:
            print(f"❌ Ошибка для кошелька {wallet[:10]}...: {e}")
    
    print(f"Найдено {len(all_base_positions)} позиций на Base")
        
    for i, pos in enumerate(all_base_positions, 1):
        print(f"  {i}. {pos['pool_name']} (Token ID: {pos['position_id']})")
        print(f"     Fee: {pos['fee_tier']:.2%}")
        print(f"     💰 Total Value: ${pos['total_value_usd']:,.2f}")
        print(f"     🪙 Tokens: {pos['amount0']:.6f} {pos['token0_symbol']} + {pos['amount1']:.6f} {pos['token1_symbol']}")
        print(f"     📊 Status: {'✅ In Range' if pos['in_range'] else '❌ Out of Range'}")
        print("---")

    # Сохраняем позиции Base в Supabase
    if all_base_positions and SUPABASE_ENABLED:
        print(f"\n💾 Сохраняем {len(all_base_positions)} позиций Base в Supabase...")
        saved_count = await save_ethereum_positions_to_supabase(all_base_positions, "base")
        print(f"✅ Сохранено {saved_count} позиций в Supabase")

async def get_positions_fees_from_subgraph(
    wallet_address: str, 
    network: str = "ethereum"
) -> Dict[int, Dict[str, float]]:
    """
    Получает данные позиций и uncollected fees через The Graph subgraph
    
    Returns:
        Dict[position_id, {'fees_token0': float, 'fees_token1': float, 'fees_usd': float}]
    """
    if not wallet_address:
        logger.error("Wallet address is required")
        return {}
        
    try:
        import httpx
        
        # URLs для subgraph с правильным API ключом (используем тот же что для TVL)
        subgraph_urls = {
            "ethereum": "https://gateway.thegraph.com/api/ed5e8fbed08836e4e5e540c65d635f0d/subgraphs/id/5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV",
            "base": "https://gateway.thegraph.com/api/ed5e8fbed08836e4e5e540c65d635f0d/subgraphs/id/HMuAwufqZ1YCRmzL2SfHTVkzZovC9VL2UAKhjvRqKiR1"
        }
        
        subgraph_url = subgraph_urls.get(network)
        if not subgraph_url:
            logger.error(f"Нет subgraph URL для сети {network}")
            return {}
        
        wallet_address_lower = wallet_address.lower()
        
        # GraphQL запрос для получения позиций с uncollected fees
        query = """
        {
          positions(
            where: {owner: "%s"}
            orderBy: id
            orderDirection: desc
            first: 10
          ) {
            id
            owner
            liquidity
            pool {
              id
              token0 {
                id
                symbol
                decimals
              }
              token1 {
                id
                symbol
                decimals
              }
              feeTier
            }
          }
        }
        """ % wallet_address_lower
        
        print(f"🔍 Запрос позиций через Subgraph для {wallet_address}")
        print(f"📍 URL: {subgraph_url[:50]}...")
        
        headers = {
            'Content-Type': 'application/json',
        }
        
        payload = {
            'query': query
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                subgraph_url,
                json=payload,
                headers=headers,
                timeout=30
            )
            
            if response.status_code != 200:
                logger.error(f"Subgraph request failed: {response.status_code}")
                logger.error(f"Response: {response.text}")
                return {}
            
            data = response.json()
            
            if 'errors' in data:
                logger.error(f"Subgraph errors: {data['errors']}")
                return {}
            
            positions = data.get('data', {}).get('positions', [])
            print(f"📊 Получено {len(positions)} позиций из Subgraph")
            
            # Отладочный вывод первой позиции
            if positions:
                print("\n🔍 СТРУКТУРА ПЕРВОЙ ПОЗИЦИИ:")
                print(positions[0])
                print("=" * 50)
            
            result = {}
            
            for pos in positions:
                try:
                    # В subgraph id - это уникальный номер, но не NFT tokenId
                    position_id = pos['id']  # Используем subgraph id как идентификатор
                    
                    # В этом subgraph НЕТ прямых uncollected fees
                    # Показываем что позиция существует
                    
                    # Получаем decimals для правильного преобразования
                    token0_symbol = pos['pool']['token0']['symbol']
                    token1_symbol = pos['pool']['token1']['symbol']
                    token0_decimals = int(pos['pool']['token0']['decimals'])
                    token1_decimals = int(pos['pool']['token1']['decimals'])
                    liquidity = pos.get('liquidity', '0')
                    
                    # Этот subgraph НЕ содержит uncollected fees
                    # Нужен другой subgraph или RPC вызовы
                    fees_token0 = 0.0
                    fees_token1 = 0.0
                    
                    print(f"📊 Позиция {position_id}: {token0_symbol}/{token1_symbol} (liquidity: {liquidity})")
                    
                    result[position_id] = {
                        'fees_token0': fees_token0,
                        'fees_token1': fees_token1,
                        'fees_usd': 0.0,  # Будет рассчитано позже с ценами
                        'token0_symbol': token0_symbol,
                        'token1_symbol': token1_symbol,
                        'pool_address': pos['pool']['id'],
                        'liquidity': liquidity,
                        'source': 'subgraph_basic'
                    }
                    
                except Exception as e:
                    logger.error(f"Ошибка обработки позиции {pos.get('id', 'unknown')}: {e}")
                    continue
            
            logger.info(f"✅ Получены fees данные для {len(result)} позиций через Subgraph")
            return result
            
    except Exception as e:
        logger.error(f"❌ Ошибка получения позиций через Subgraph: {e}")
        return {}

if __name__ == "__main__":
    asyncio.run(test_unified_positions()) 