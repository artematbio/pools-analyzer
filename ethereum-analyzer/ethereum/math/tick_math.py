"""
Точная математика для Uniswap v3 с поддержкой X96 формата
Исправляет критические ошибки из изученных материалов byterover
"""

import math
from decimal import Decimal, getcontext
from typing import Dict, Union

# Устанавливаем высокую точность для Decimal операций
getcontext().prec = 78

# Константы для Uniswap v3 (X96 формат)
Q96 = Decimal(2**96)
Q128 = Decimal(2**128)

# Константы для расчетов
MIN_TICK = -887272
MAX_TICK = 887272
MIN_SQRT_RATIO = Decimal(4295128739)
MAX_SQRT_RATIO = Decimal(1461446703485210103287273052203988822378723970342)

# Предвычисленные константы для точности
SQRT_1_0001 = Decimal('1.0001').sqrt()


def tick_to_sqrt_price_x96(tick: int) -> int:
    """
    Конвертирует tick в sqrtPriceX96
    
    ИСПРАВЛЕНИЕ: использует X96 (не X64) для Uniswap v3
    Формула: sqrt(1.0001^tick) * 2^96
    
    Args:
        tick: Tick value
        
    Returns:
        sqrtPriceX96 как uint160
    """
    if not (MIN_TICK <= tick <= MAX_TICK):
        raise ValueError(f"Tick {tick} out of bounds [{MIN_TICK}, {MAX_TICK}]")
    
    try:
        # Используем Decimal для высокой точности
        sqrt_price = SQRT_1_0001 ** Decimal(tick)
        sqrt_price_x96 = sqrt_price * Q96
        
        # Конвертируем в int, проверяя границы uint160
        result = int(sqrt_price_x96.to_integral_value(rounding='ROUND_HALF_UP'))
        
        if not (MIN_SQRT_RATIO <= result <= MAX_SQRT_RATIO):
            raise ValueError(f"Calculated sqrtPriceX96 {result} out of bounds")
            
        return result
        
    except Exception as e:
        raise ValueError(f"Error calculating sqrtPriceX96 for tick {tick}: {e}")


def sqrt_price_x96_to_price(
    sqrt_price_x96: int, 
    decimals0: int, 
    decimals1: int
) -> Decimal:
    """
    Конвертирует sqrtPriceX96 в читаемую цену токена1 в единицах токена0
    
    ИСПРАВЛЕНИЕ: правильная обработка decimal places для токенов
    
    Args:
        sqrt_price_x96: sqrtPriceX96 value
        decimals0: Decimal places токена0
        decimals1: Decimal places токена1
        
    Returns:
        Цена токена1 в единицах токена0
    """
    try:
        sqrt_price_x96_decimal = Decimal(sqrt_price_x96)
        
        # price = (sqrtPriceX96 / 2^96)^2
        price_ratio = (sqrt_price_x96_decimal / Q96) ** 2
        
        # Корректируем для decimal places
        # Цена = (amount1 / 10^decimals1) / (amount0 / 10^decimals0)
        decimal_adjustment = Decimal(10) ** (decimals0 - decimals1)
        adjusted_price = price_ratio * decimal_adjustment
        
        return adjusted_price
        
    except Exception as e:
        raise ValueError(f"Error converting sqrtPriceX96 {sqrt_price_x96}: {e}")


def calculate_amounts_from_liquidity(
    liquidity: int,
    sqrt_price_x96_current: int,
    tick_lower: int,
    tick_upper: int
) -> Dict[str, Decimal]:
    """
    Рассчитывает количества token0 и token1 из ликвидности позиции
    
    ИСПРАВЛЕНИЕ: корректная математика для Uniswap v3 X96
    
    Args:
        liquidity: Количество ликвидности (uint128)
        sqrt_price_x96_current: Текущая цена пула
        tick_lower: Нижняя граница позиции
        tick_upper: Верхняя граница позиции
        
    Returns:
        Dict с amount0 и amount1
    """
    if tick_lower >= tick_upper:
        return {"amount0": Decimal(0), "amount1": Decimal(0)}
    
    if liquidity == 0:
        return {"amount0": Decimal(0), "amount1": Decimal(0)}
    
    try:
        L = Decimal(liquidity)
        
        # Получаем sqrtPrice для границ
        sqrt_price_a = Decimal(tick_to_sqrt_price_x96(tick_lower))  # sqrtPrice нижней границы
        sqrt_price_b = Decimal(tick_to_sqrt_price_x96(tick_upper))  # sqrtPrice верхней границы
        sqrt_price_current = Decimal(sqrt_price_x96_current)
        
        amount0 = Decimal(0)
        amount1 = Decimal(0)
        
        if sqrt_price_current <= sqrt_price_a:
            # Цена ниже диапазона -> только token0
            if sqrt_price_a > 0 and sqrt_price_b > 0:
                amount0 = L * (sqrt_price_b - sqrt_price_a) / (sqrt_price_a * sqrt_price_b) * Q96
        elif sqrt_price_current >= sqrt_price_b:
            # Цена выше диапазона -> только token1  
            amount1 = L * (sqrt_price_b - sqrt_price_a) / Q96
        else:
            # Цена в диапазоне -> оба токена
            if sqrt_price_current > 0 and sqrt_price_b > 0:
                amount0 = L * (sqrt_price_b - sqrt_price_current) / (sqrt_price_current * sqrt_price_b) * Q96
            amount1 = L * (sqrt_price_current - sqrt_price_a) / Q96
        
        # Ensure non-negative
        amount0 = max(Decimal(0), amount0)
        amount1 = max(Decimal(0), amount1)
        
        return {
            "amount0": amount0,
            "amount1": amount1
        }
        
    except Exception as e:
        print(f"Error calculating amounts from liquidity: {e}")
        return {"amount0": Decimal(0), "amount1": Decimal(0)}


def get_price_from_tick(tick: int, decimals0: int = 18, decimals1: int = 18) -> Decimal:
    """
    Прямое получение цены из tick с учетом decimals
    
    Args:
        tick: Tick value
        decimals0: Decimal places token0
        decimals1: Decimal places token1
        
    Returns:
        Цена токена1 в единицах токена0
    """
    try:
        sqrt_price_x96 = tick_to_sqrt_price_x96(tick)
        return sqrt_price_x96_to_price(sqrt_price_x96, decimals0, decimals1)
    except Exception as e:
        raise ValueError(f"Error getting price from tick {tick}: {e}")


def calculate_price_range(tick_lower: int, tick_upper: int, decimals0: int = 18, decimals1: int = 18) -> Dict[str, Decimal]:
    """
    Рассчитывает диапазон цен для позиции
    
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
        raise ValueError(f"Error calculating price range: {e}")


def is_position_in_range(current_tick: int, tick_lower: int, tick_upper: int) -> bool:
    """
    Проверяет, находится ли позиция в диапазоне (in-range)
    
    Args:
        current_tick: Текущий tick пула
        tick_lower: Нижний tick позиции
        tick_upper: Верхний tick позиции
        
    Returns:
        True если позиция in-range
    """
    return tick_lower <= current_tick <= tick_upper


# Хелперы для debug и валидации
def validate_tick(tick: int) -> bool:
    """Проверяет валидность tick"""
    return MIN_TICK <= tick <= MAX_TICK


def validate_sqrt_price_x96(sqrt_price_x96: int) -> bool:
    """Проверяет валидность sqrtPriceX96"""
    return MIN_SQRT_RATIO <= sqrt_price_x96 <= MAX_SQRT_RATIO


# Константы для тестирования
USDC_DECIMALS = 6
WETH_DECIMALS = 18
DAI_DECIMALS = 18

def test_calculations():
    """Тест основных функций математики"""
    print("🧪 Тестирование математики Uniswap v3...")
    
    # Тест 1: Конвертация tick в sqrtPriceX96
    test_tick = 0  # tick = 0 соответствует цене 1:1
    sqrt_price = tick_to_sqrt_price_x96(test_tick)
    print(f"Tick 0 -> sqrtPriceX96: {sqrt_price}")
    
    # Тест 2: Конвертация в цену
    price = sqrt_price_x96_to_price(sqrt_price, 18, 18)
    print(f"sqrtPriceX96 -> price: {price}")
    
    # Тест 3: Расчет amounts
    liquidity = 1000000000000000000  # 1e18
    amounts = calculate_amounts_from_liquidity(liquidity, sqrt_price, -1000, 1000)
    print(f"Amounts from liquidity: {amounts}")
    
    print("✅ Тесты завершены")


if __name__ == "__main__":
    test_calculations() 