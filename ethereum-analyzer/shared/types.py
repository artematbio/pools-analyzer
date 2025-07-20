"""
Универсальные типы данных для анализа пулов ликвидности
Поддерживает как Raydium/Solana так и Uniswap/Ethereum
"""

from dataclasses import dataclass
from typing import Optional, Dict, List, Any, Union
from decimal import Decimal
from datetime import datetime
from enum import Enum

class DataSource(Enum):
    """Источники данных"""
    RPC_DIRECT = "rpc_direct"
    API_THIRD_PARTY = "api_third_party"
    SUBGRAPH = "subgraph"
    BLOCKCHAIN = "blockchain"
    CACHE = "cache"

class ProtocolType(Enum):
    """Типы протоколов"""
    RAYDIUM_CLMM = "raydium_clmm"
    UNISWAP_V3 = "uniswap_v3"
    ORCA_WHIRLPOOL = "orca_whirlpool"

class PositionStatus(Enum):
    """Статус позиции"""
    IN_RANGE = "in_range"
    OUT_OF_RANGE = "out_of_range"
    CLOSED = "closed"
    PENDING = "pending"

@dataclass
class DataQuality:
    """Оценка качества данных"""
    source: DataSource
    freshness_seconds: int  # Как давно обновлялись данные
    confidence: float  # 0.0 - 1.0
    completeness: float  # 0.0 - 1.0, насколько полные данные
    
    def is_reliable(self) -> bool:
        """Проверяет надежность данных"""
        return (
            self.confidence >= 0.8 and 
            self.completeness >= 0.9 and 
            self.freshness_seconds <= 300  # 5 минут
        )

@dataclass
class Token:
    """Универсальная структура токена"""
    address: str
    symbol: str
    name: str
    decimals: int
    price_usd: Optional[Decimal] = None
    logo_uri: Optional[str] = None
    
    # Blockchain-specific поля
    mint_authority: Optional[str] = None  # Solana
    freeze_authority: Optional[str] = None  # Solana
    
    def __str__(self) -> str:
        return f"{self.symbol} ({self.address[:8]}...)"

@dataclass
class PoolInfo:
    """Информация о пуле ликвидности"""
    pool_id: str
    protocol: ProtocolType
    token0: Token
    token1: Token
    fee_tier: int  # В basis points (3000 = 0.3%)
    tick_spacing: int
    
    # Текущее состояние
    current_tick: Optional[int] = None
    sqrt_price: Optional[int] = None  # X64 или X96 в зависимости от протокола
    liquidity: Optional[int] = None
    
    # Метрики
    tvl_usd: Optional[Decimal] = None
    volume_24h_usd: Optional[Decimal] = None
    apr: Optional[Decimal] = None
    
    # Качество данных
    data_quality: Optional[DataQuality] = None
    
    def get_pair_name(self) -> str:
        """Возвращает название пары"""
        return f"{self.token0.symbol}/{self.token1.symbol}"

@dataclass
class PositionData:
    """Универсальная структура позиции ликвидности"""
    position_id: str  # Token ID для NFT или PDA для Solana
    owner: str
    pool: PoolInfo
    protocol: ProtocolType
    
    # Диапазон позиции
    tick_lower: int
    tick_upper: int
    liquidity: int
    
    # Накопленные комиссии
    uncollected_fees_token0: Decimal
    uncollected_fees_token1: Decimal
    
    # Рассчитанные значения
    token0_amount: Optional[Decimal] = None
    token1_amount: Optional[Decimal] = None
    total_value_usd: Optional[Decimal] = None
    
    # Статус
    status: PositionStatus = PositionStatus.PENDING
    
    # Метаданные
    created_at: Optional[datetime] = None
    last_updated: Optional[datetime] = None
    data_quality: Optional[DataQuality] = None
    
    def is_in_range(self) -> bool:
        """Проверяет находится ли позиция в диапазоне"""
        if not self.pool.current_tick:
            return False
        return self.tick_lower <= self.pool.current_tick <= self.tick_upper
    
    def get_range_width_percent(self) -> Optional[float]:
        """Возвращает ширину диапазона в процентах"""
        if not self.pool.current_tick:
            return None
        
        total_range = self.tick_upper - self.tick_lower
        if total_range <= 0:
            return 0.0
        
        # Приблизительный расчет через tick spacing
        return (total_range / self.pool.tick_spacing) * 0.01  # Примерная оценка

@dataclass 
class APIConfig:
    """Конфигурация API"""
    name: str
    base_url: str
    api_key: Optional[str] = None
    rate_limit: Optional[int] = None
    timeout: int = 30

@dataclass
class BlockchainConfig:
    """Конфигурация блокчейна"""
    name: str
    rpc_urls: List[str]
    api_configs: Dict[str, APIConfig]
    default_timeout: int = 30
    
    def get_primary_rpc(self) -> str:
        """Возвращает основной RPC URL"""
        return self.rpc_urls[0] if self.rpc_urls else ""

@dataclass
class AnalysisResult:
    """Результат анализа позиций"""
    timestamp: datetime
    total_positions: int
    total_value_usd: Decimal
    in_range_positions: int
    out_of_range_positions: int
    
    # Детальная информация
    positions: List[PositionData]
    pools: List[PoolInfo]
    
    # Рекомендации
    recommendations: List[str]
    alerts: List[str]
    
    # Качество анализа
    data_quality_score: float  # 0.0 - 1.0
    
    def get_summary(self) -> Dict[str, Any]:
        """Возвращает краткую сводку"""
        return {
            "total_positions": self.total_positions,
            "total_value_usd": float(self.total_value_usd),
            "in_range_percent": (self.in_range_positions / max(1, self.total_positions)) * 100,
            "unique_pools": len(self.pools),
            "data_quality": self.data_quality_score,
            "alerts_count": len(self.alerts)
        }

# Утилитарные функции
def create_ethereum_token(address: str, symbol: str, decimals: int = 18) -> Token:
    """Создает токен Ethereum с дефолтными параметрами"""
    return Token(
        address=address.lower(),
        symbol=symbol,
        name=symbol,  # Упрощенная версия
        decimals=decimals
    )

def create_solana_token(mint: str, symbol: str, decimals: int = 9) -> Token:
    """Создает токен Solana с дефолтными параметрами"""
    return Token(
        address=mint,
        symbol=symbol,
        name=symbol,  # Упрощенная версия
        decimals=decimals
    )

def validate_position_data(position: PositionData) -> List[str]:
    """Валидирует данные позиции и возвращает список ошибок"""
    errors = []
    
    if not position.position_id:
        errors.append("Missing position_id")
    
    if not position.owner:
        errors.append("Missing owner")
    
    if position.tick_lower >= position.tick_upper:
        errors.append("Invalid tick range: tick_lower >= tick_upper")
    
    if position.liquidity < 0:
        errors.append("Negative liquidity")
    
    if position.uncollected_fees_token0 < 0:
        errors.append("Negative uncollected_fees_token0")
    
    if position.uncollected_fees_token1 < 0:
        errors.append("Negative uncollected_fees_token1")
    
    return errors

# Константы для протоколов
RAYDIUM_TICK_SPACING = {
    1: 1,     # 0.01%
    60: 60,   # 0.6%
    600: 600, # 6%
}

UNISWAP_TICK_SPACING = {
    100: 1,     # 0.01%
    500: 10,    # 0.05%
    3000: 60,   # 0.3%
    10000: 200, # 1%
}

def get_tick_spacing(protocol: ProtocolType, fee_tier: int) -> int:
    """Возвращает tick spacing для протокола и fee tier"""
    if protocol == ProtocolType.RAYDIUM_CLMM:
        return RAYDIUM_TICK_SPACING.get(fee_tier, 60)  # Default 60
    elif protocol == ProtocolType.UNISWAP_V3:
        return UNISWAP_TICK_SPACING.get(fee_tier, 60)  # Default 60
    else:
        return 60  # Default fallback 