"""
Ethereum RPC Client с поддержкой multiple endpoints и batching
Интеграция с Alchemy и Infura для повышенной надежности
"""

import asyncio
import logging
import time
from typing import List, Dict, Any, Optional, Union
from dataclasses import dataclass
from web3 import Web3
from web3.providers import HTTPProvider
import httpx

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))

from shared.rate_limiter import global_rate_limiter
from shared.types import DataQuality, DataSource

logger = logging.getLogger(__name__)

@dataclass
class RPCEndpoint:
    """Конфигурация RPC endpoint"""
    name: str
    url: str
    api_key: Optional[str] = None
    priority: int = 1  # 1 = highest priority
    rate_limit_tier: str = "free"  # free, growth, pro

class EthereumRPCClient:
    """
    Клиент для работы с Ethereum RPC с поддержкой:
    - Multiple endpoints (Alchemy, Infura, публичные)
    - Automatic failover
    - Rate limiting
    - Batch calls
    """

    def __init__(self, endpoints: List[RPCEndpoint]):
        self.endpoints = sorted(endpoints, key=lambda x: x.priority)
        self.web3_instances: Dict[str, Web3] = {}
        self.client: Optional[httpx.AsyncClient] = None
        
        # Инициализируем Web3 для каждого endpoint
        for endpoint in self.endpoints:
            try:
                # Формируем URL с API ключом если нужен
                url = self._build_url(endpoint)
                self.web3_instances[endpoint.name] = Web3(Web3.HTTPProvider(url))
                logger.info(f"Initialized Web3 for {endpoint.name}")
            except Exception as e:
                logger.error(f"Failed to initialize {endpoint.name}: {e}")

    def _build_url(self, endpoint: RPCEndpoint) -> str:
        """Строит URL с API ключом"""
        if endpoint.api_key:
            if "alchemy" in endpoint.url.lower():
                return f"{endpoint.url}/{endpoint.api_key}"
            elif "infura" in endpoint.url.lower():
                return f"{endpoint.url}/{endpoint.api_key}"
        return endpoint.url

    async def __aenter__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.client:
            await self.client.aclose()

    async def batch_call(self, calls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Выполняет batch RPC calls с автоматическим failover
        
        Args:
            calls: Список RPC вызовов в формате:
                   [{"method": "eth_call", "params": [...], "id": 1}, ...]
        
        Returns:
            Список результатов в том же порядке
        """
        if not calls:
            return []

        batch = [
            {
                "jsonrpc": "2.0",
                "id": call.get("id", i),
                "method": call["method"],
                "params": call.get("params", [])
            }
            for i, call in enumerate(calls)
        ]

        # Пробуем каждый endpoint по порядку приоритета
        for endpoint in self.endpoints:
            try:
                async with global_rate_limiter.rate_limited_request(
                    f"ethereum_{endpoint.rate_limit_tier}",
                    f"batch_call_{len(batch)}"
                ):
                    results = await self._try_batch_on_endpoint(batch, endpoint)
                    return results
            except Exception as e:
                logger.warning(f"Batch failed on {endpoint.name}: {e}")
                continue

        # Если все endpoint'ы не сработали
        logger.error(f"All endpoints failed for batch of {len(batch)} calls")
        return [{"error": "All endpoints failed"} for _ in batch]

    async def _try_batch_on_endpoint(
        self, batch: List[Dict[str, Any]], endpoint: RPCEndpoint
    ) -> List[Dict[str, Any]]:
        """Пытается выполнить батч на конкретном endpoint"""
        web3 = self.web3_instances.get(endpoint.name)
        if not web3:
            raise ValueError(f"Web3 instance not found for {endpoint.name}")

        url = self._build_url(endpoint)
        
        if not self.client:
            raise ValueError("HTTP client not initialized")

        response = await self.client.post(
            url,
            json=batch,
            headers={"Content-Type": "application/json"}
        )
        response.raise_for_status()
        
        results = response.json()
        
        # Если batch call, результат - массив
        if isinstance(results, list):
            return results
        else:
            # Single call
            return [results]

    async def get_block_number(self) -> int:
        """Получает текущий номер блока"""
        results = await self.batch_call([{"method": "eth_blockNumber", "params": []}])
        if results and "result" in results[0]:
            return int(results[0]["result"], 16)
        else:
            raise ValueError("Failed to get block number")

    def get_web3_instance(self, endpoint_name: Optional[str] = None) -> Web3:
        """Возвращает Web3 instance для синхронных операций"""
        if endpoint_name and endpoint_name in self.web3_instances:
            return self.web3_instances[endpoint_name]
        else:
            # Возвращаем первый доступный
            return list(self.web3_instances.values())[0]

    def is_connected(self) -> bool:
        """Проверяет подключение к любому из endpoints"""
        for web3 in self.web3_instances.values():
            try:
                web3.eth.block_number
                return True
            except Exception:
                continue
        return False

    def get_data_quality(self, endpoint_name: str) -> DataQuality:
        """Возвращает оценку качества данных для endpoint"""
        endpoint = next((e for e in self.endpoints if e.name == endpoint_name), None)
        if not endpoint:
            return DataQuality(
                source=DataSource.BLOCKCHAIN,
                freshness_seconds=0,
                confidence=0.0,
                completeness=0.0
            )
        
        confidence_map = {
            "pro": 0.95,
            "growth": 0.90,
            "free": 0.85
        }
        
        return DataQuality(
            source=DataSource.BLOCKCHAIN,
            freshness_seconds=12,  # Ethereum block time
            completeness=1.0,
            confidence=confidence_map.get(endpoint.rate_limit_tier, 0.7),
        )


# Фабрика для создания клиента с реальными endpoint'ами
def create_ethereum_rpc_client(
    alchemy_api_key: Optional[str] = None,
    infura_api_key: Optional[str] = None
) -> EthereumRPCClient:
    """
    Создает RPC клиент с реальными API ключами
    """
    # Получаем API ключи из переменных окружения, если не переданы
    if alchemy_api_key is None:
        alchemy_api_key = os.getenv("ALCHEMY_API_KEY", "0l42UZmHRHWXBYMJ2QFcdEE-Glj20xqn")
    if infura_api_key is None:
        infura_api_key = os.getenv("INFURA_API_KEY", "347bf443bc8f4d468768e41ee26aff27")
    
    endpoints = []

    if alchemy_api_key:
        endpoints.append(RPCEndpoint(
            name="alchemy_mainnet",
            url="https://eth-mainnet.g.alchemy.com/v2",
            api_key=alchemy_api_key,
            priority=1,
            rate_limit_tier="free"
        ))

    if infura_api_key:
        endpoints.append(RPCEndpoint(
            name="infura_mainnet", 
            url="https://mainnet.infura.io/v3",
            api_key=infura_api_key,
            priority=2,
            rate_limit_tier="free"
        ))

    # Публичные endpoint'ы как fallback
    endpoints.extend([
        RPCEndpoint(
            name="cloudflare",
            url="https://cloudflare-eth.com",
            priority=3
        ),
        RPCEndpoint(
            name="ankr",
            url="https://rpc.ankr.com/eth",
            priority=4
        )
    ])

    return EthereumRPCClient(endpoints) 