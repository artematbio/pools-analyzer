"""
Uniswap v3 Contract ABIs
Содержит упрощенные ABI для основных функций контрактов Uniswap v3
"""

# Contract Addresses (Ethereum Mainnet)
NONFUNGIBLE_POSITION_MANAGER = "0xC36442b4a4522E871399CD717aBDD847Ab11FE88"
UNISWAP_V3_FACTORY = "0x1F98431c8aD98523631AE4a59f267346ea31F984"

# NonfungiblePositionManager ABI (только нужные функции)
POSITION_MANAGER_ABI = [
    {
        "inputs": [{"internalType": "address", "name": "owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [
            {"internalType": "address", "name": "owner", "type": "address"},
            {"internalType": "uint256", "name": "index", "type": "uint256"}
        ],
        "name": "tokenOfOwnerByIndex",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "positions",
        "outputs": [
            {"internalType": "uint96", "name": "nonce", "type": "uint96"},
            {"internalType": "address", "name": "operator", "type": "address"},
            {"internalType": "address", "name": "token0", "type": "address"},
            {"internalType": "address", "name": "token1", "type": "address"},
            {"internalType": "uint24", "name": "fee", "type": "uint24"},
            {"internalType": "int24", "name": "tickLower", "type": "int24"},
            {"internalType": "int24", "name": "tickUpper", "type": "int24"},
            {"internalType": "uint128", "name": "liquidity", "type": "uint128"},
            {"internalType": "uint256", "name": "feeGrowthInside0LastX128", "type": "uint256"},
            {"internalType": "uint256", "name": "feeGrowthInside1LastX128", "type": "uint256"},
            {"internalType": "uint128", "name": "tokensOwed0", "type": "uint128"},
            {"internalType": "uint128", "name": "tokensOwed1", "type": "uint128"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# UniswapV3Pool ABI (только нужные функции)
UNISWAP_V3_POOL_ABI = [
    {
        "inputs": [],
        "name": "slot0",
        "outputs": [
            {"internalType": "uint160", "name": "sqrtPriceX96", "type": "uint160"},
            {"internalType": "int24", "name": "tick", "type": "int24"},
            {"internalType": "uint16", "name": "observationIndex", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinality", "type": "uint16"},
            {"internalType": "uint16", "name": "observationCardinalityNext", "type": "uint16"},
            {"internalType": "uint8", "name": "feeProtocol", "type": "uint8"},
            {"internalType": "bool", "name": "unlocked", "type": "bool"}
        ],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "liquidity",
        "outputs": [{"internalType": "uint128", "name": "", "type": "uint128"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "fee",
        "outputs": [{"internalType": "uint24", "name": "", "type": "uint24"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token0",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "token1",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function"
    },
    {
        "inputs": [],
        "name": "tickSpacing",
        "outputs": [{"internalType": "int24", "name": "", "type": "int24"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Токены для анализа (WETH + DeSci токены) - все в lowercase для совместимости
ETHEREUM_TOKENS = {
    "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2": "WETH",
    "0xcb1592591996765ec0efc1f92599a19767ee5ffa": "BIO",
    "0x81f8f0bb1cb2a06649e51913a151f0e7ef6fa321": "VITA",
    "0x9ce115f0341ae5dabc8b477b74e83db2018a6f42": "HAIR",
    "0xa4ffdf3208f46898ce063e25c1c43056fa754739": "ATH",
    "0x761a3557184cbc07b7493da0661c41177b2f97fa": "GROW",
    "0xab814ce69e15f6b9660a3b184c0b0c97b9394a6b": "NEURON",
    "0xf4308b0263723b121210565938e40879dd0": "CRYO",
    "0x2196b84eace74867b73fb003aff93c11fce1d47a": "PSY",
    "0x3e6a1b21bd267677fa49be6425aebe2fc089bde": "QBIO"
}

def get_token_symbol(token_address):
    """Получает символ токена из известных адресов"""
    return ETHEREUM_TOKENS.get(token_address.lower(), token_address[:8] + "...")

# Константы комиссий Uniswap v3
UNISWAP_V3_FEES = {
    100: "0.01%",    # 0.01% fee tier
    500: "0.05%",    # 0.05% fee tier  
    3000: "0.3%",    # 0.3% fee tier
    10000: "1%"      # 1% fee tier
}

def format_fee_tier(fee_raw):
    """Форматирует fee tier для отображения"""
    return UNISWAP_V3_FEES.get(fee_raw, f"{fee_raw/10000:.2%}")

def get_position_manager_abi():
    """Возвращает ABI для NonfungiblePositionManager"""
    return POSITION_MANAGER_ABI

def get_pool_abi():
    """Возвращает ABI для UniswapV3Pool"""
    return UNISWAP_V3_POOL_ABI

def parse_position_data(raw_position_data):
    """
    Парсит данные позиции из positions() вызова
    """
    if not raw_position_data or len(raw_position_data) < 12:
        return None
        
    return {
        'nonce': raw_position_data[0],
        'operator': raw_position_data[1], 
        'token0': raw_position_data[2],
        'token1': raw_position_data[3],
        'fee': raw_position_data[4],
        'tick_lower': raw_position_data[5],
        'tick_upper': raw_position_data[6],
        'liquidity': raw_position_data[7],
        'fee_growth_inside0_last_x128': raw_position_data[8],
        'fee_growth_inside1_last_x128': raw_position_data[9],
        'tokens_owed0': raw_position_data[10],
        'tokens_owed1': raw_position_data[11]
    }

def is_valid_position(position_data):
    """Проверяет, является ли позиция валидной (не пустой)"""
    if not position_data:
        return False
    
    return (
        position_data.get('liquidity', 0) > 0 or 
        position_data.get('tokens_owed0', 0) > 0 or 
        position_data.get('tokens_owed1', 0) > 0
    ) 