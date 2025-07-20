"""
Продвинутый Rate Limiter для управления API лимитами
Поддерживает sliding window и exponential backoff
"""

import time
import asyncio
import logging
from typing import Dict, List, Any, Callable
from dataclasses import dataclass
from collections import deque, defaultdict
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)

@dataclass
class RateLimitConfig:
    """Конфигурация rate limiting"""
    max_requests: int
    time_window: int  # в секундах
    burst_allowance: int = 0  # дополнительные запросы для burst
    backoff_multiplier: float = 1.5
    max_backoff: int = 300  # максимальное время ожидания в секундах

class TokenBucket:
    """Token bucket для rate limiting"""
    
    def __init__(self, max_tokens: int, refill_rate: float):
        self.max_tokens = max_tokens
        self.tokens = max_tokens
        self.refill_rate = refill_rate
        self.last_refill = time.time()
    
    async def consume(self, tokens: int = 1) -> bool:
        """Попытка потребить токены"""
        now = time.time()
        
        # Пополняем токены
        time_passed = now - self.last_refill
        new_tokens = time_passed * self.refill_rate
        self.tokens = min(self.max_tokens, self.tokens + new_tokens)
        self.last_refill = now
        
        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False
    
    async def wait_for_tokens(self, tokens: int = 1) -> float:
        """Ожидание доступности токенов"""
        if await self.consume(tokens):
            return 0.0
        
        # Вычисляем время ожидания
        needed_tokens = tokens - self.tokens
        wait_time = needed_tokens / self.refill_rate
        return wait_time

class SlidingWindowRateLimiter:
    """Sliding window rate limiter"""
    
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self.requests = deque()
    
    async def is_allowed(self) -> bool:
        """Проверяет разрешен ли запрос"""
        now = time.time()
        
        # Удаляем старые запросы
        while self.requests and self.requests[0] <= now - self.config.time_window:
            self.requests.popleft()
        
        # Проверяем лимит (включая burst)
        max_allowed = self.config.max_requests + self.config.burst_allowance
        return len(self.requests) < max_allowed
    
    async def record_request(self):
        """Записывает новый запрос"""
        self.requests.append(time.time())
    
    async def time_until_allowed(self) -> float:
        """Возвращает время до следующего разрешенного запроса"""
        if await self.is_allowed():
            return 0.0
        
        # Время до истечения самого старого запроса
        if self.requests:
            oldest_request = self.requests[0]
            return max(0, oldest_request + self.config.time_window - time.time())
        return 0.0

class APIRateLimiter:
    """Главный класс для управления rate limiting разных API"""
    
    def __init__(self):
        self.configs: Dict[str, RateLimitConfig] = {}
        self.limiters: Dict[str, SlidingWindowRateLimiter] = {}
        self.error_counts: Dict[str, int] = defaultdict(int)
        self.last_error_time: Dict[str, float] = {}
        
        # Предустановленные конфигурации для популярных API
        self._setup_default_configs()
    
    def _setup_default_configs(self):
        """Настройка дефолтных конфигураций для известных API"""
        self.add_api_config("alchemy_free", RateLimitConfig(
            max_requests=330, time_window=60, burst_allowance=50
        ))
        self.add_api_config("alchemy_growth", RateLimitConfig(
            max_requests=660, time_window=60, burst_allowance=100
        ))
        self.add_api_config("coingecko_free", RateLimitConfig(
            max_requests=50, time_window=60, burst_allowance=10
        ))
        self.add_api_config("coingecko_pro", RateLimitConfig(
            max_requests=500, time_window=60, burst_allowance=50
        ))
        self.add_api_config("the_graph", RateLimitConfig(
            max_requests=1000, time_window=60, burst_allowance=100
        ))
        self.add_api_config("geckoterminal", RateLimitConfig(
            max_requests=60, time_window=60, burst_allowance=15
        ))
        
        # Конфигурации для Ethereum RPC
        self.add_api_config("ethereum_free", RateLimitConfig(
            max_requests=300, time_window=60, burst_allowance=50
        ))
        self.add_api_config("ethereum_growth", RateLimitConfig(
            max_requests=600, time_window=60, burst_allowance=100
        ))
        self.add_api_config("ethereum_pro", RateLimitConfig(
            max_requests=1200, time_window=60, burst_allowance=200
        ))
    
    def add_api_config(self, api_name: str, config: RateLimitConfig):
        """Добавляет конфигурацию для API"""
        self.configs[api_name] = config
        self.limiters[api_name] = SlidingWindowRateLimiter(config)
    
    @asynccontextmanager
    async def rate_limited_request(self, api_name: str, operation_name: str = "request"):
        """Context manager для rate limited запросов"""
        if api_name not in self.limiters:
            raise ValueError(f"Unknown API: {api_name}")
        
        limiter = self.limiters[api_name]
        config = self.configs[api_name]
        
        # Проверка backoff
        if await self._should_backoff(api_name):
            backoff_time = self._calculate_backoff(api_name)
            logger.warning(f"Backing off {api_name} for {backoff_time:.1f}s after errors")
            await asyncio.sleep(backoff_time)
        
        # Ожидание rate limit
        wait_time = await limiter.time_until_allowed()
        if wait_time > 0:
            logger.debug(f"Rate limiting {api_name}: waiting {wait_time:.1f}s")
            await asyncio.sleep(wait_time)
        
        start_time = time.time()
        
        try:
            # Записываем запрос
            await limiter.record_request()
            
            yield
            
            # Успешный запрос - сбрасываем error count
            self.error_counts[api_name] = 0
            
        except Exception as e:
            # Ошибка - увеличиваем counter
            self.error_counts[api_name] += 1
            self.last_error_time[api_name] = time.time()
            
            # Логируем rate limit errors отдельно
            if "rate limit" in str(e).lower():
                logger.warning(f"Rate limit hit for {api_name}: {e}")
            else:
                logger.error(f"API error for {api_name}: {e}")
            raise
        finally:
            duration = time.time() - start_time
            logger.debug(f"{api_name} {operation_name} took {duration:.2f}s")
    
    async def _should_backoff(self, api_name: str) -> bool:
        """Определяет нужен ли backoff"""
        error_count = self.error_counts[api_name]
        
        if error_count < 3:
            return False
        
        last_error = self.last_error_time.get(api_name, 0)
        backoff_time = self._calculate_backoff(api_name)
        
        return time.time() - last_error < backoff_time
    
    def _calculate_backoff(self, api_name: str) -> float:
        """Рассчитывает время backoff"""
        error_count = self.error_counts[api_name]
        config = self.configs[api_name]
        
        if error_count <= 2:
            return 0.0
        
        # Exponential backoff: base^(errors-2) seconds
        backoff = config.backoff_multiplier ** (error_count - 2)
        return min(backoff, config.max_backoff)
    
    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """Возвращает статистику по всем API"""
        stats = {}
        for api_name, limiter in self.limiters.items():
            stats[api_name] = {
                "error_count": self.error_counts[api_name],
                "active_requests": len(limiter.requests),
                "max_requests": self.configs[api_name].max_requests,
                "last_error": self.last_error_time.get(api_name),
                "next_backoff": self._calculate_backoff(api_name)
            }
        return stats

# Глобальный instance
global_rate_limiter = APIRateLimiter()

# Утилитарная функция для простого использования
async def rate_limited_call(api_name: str, func: Callable, *args, **kwargs):
    """Выполняет функцию с rate limiting"""
    async with global_rate_limiter.rate_limited_request(api_name):
        return await func(*args, **kwargs) 