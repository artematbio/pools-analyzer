#!/usr/bin/env python3
"""
Калькулятор приближения к границам позиций
"""

from decimal import Decimal
from typing import Dict, Any, Optional, List
import logging

def calculate_range_proximity(position: Dict[str, Any]) -> Dict[str, Any]:
    """
    Рассчитывает приближение позиции к границам диапазона
    
    Args:
        position: Данные позиции с tick_lower, tick_upper, current_tick/current_price
        
    Returns:
        Dict с информацией о приближении к границам
    """
    try:
        tick_lower = position.get('tick_lower')
        tick_upper = position.get('tick_upper')
        
        # Получаем текущий тик из разных возможных источников
        current_tick = position.get('current_tick')
        if current_tick is None:
            # Пытаемся вычислить из current_price если есть
            current_price = position.get('current_price')
            if current_price and 'decimals0' in position and 'decimals1' in position:
                # Для точного расчета нужна функция конвертации цены в тик
                # Пока используем приблизительную логику
                current_tick = estimate_tick_from_price(
                    float(current_price), 
                    position.get('decimals0', 18),
                    position.get('decimals1', 18)
                )
        
        if None in [tick_lower, tick_upper, current_tick]:
            return {
                'proximity_status': 'insufficient_data',
                'distance_to_lower_percent': None,
                'distance_to_upper_percent': None,
                'warning_threshold_reached': False
            }
        
        # Проверяем что позиция в диапазоне
        in_range = tick_lower <= current_tick <= tick_upper
        if not in_range:
            return {
                'proximity_status': 'out_of_range',
                'distance_to_lower_percent': None,
                'distance_to_upper_percent': None,
                'warning_threshold_reached': False,
                'current_status': 'below_range' if current_tick < tick_lower else 'above_range'
            }
        
        # Рассчитываем расстояния
        total_range = tick_upper - tick_lower
        distance_from_lower = current_tick - tick_lower
        distance_from_upper = tick_upper - current_tick
        
        # Процентные расстояния от границ
        distance_to_lower_percent = (distance_from_lower / total_range) * 100
        distance_to_upper_percent = (distance_from_upper / total_range) * 100
        
        # Проверяем приближение к границам (5% порог)
        warning_threshold = 5.0
        approaching_lower = distance_to_lower_percent <= warning_threshold
        approaching_upper = distance_to_upper_percent <= warning_threshold
        
        warning_threshold_reached = approaching_lower or approaching_upper
        
        proximity_status = 'safe'
        if warning_threshold_reached:
            if approaching_lower and approaching_upper:
                proximity_status = 'narrow_range_warning'
            elif approaching_lower:
                proximity_status = 'approaching_lower_bound'
            else:
                proximity_status = 'approaching_upper_bound'
        
        return {
            'proximity_status': proximity_status,
            'distance_to_lower_percent': round(distance_to_lower_percent, 2),
            'distance_to_upper_percent': round(distance_to_upper_percent, 2),
            'warning_threshold_reached': warning_threshold_reached,
            'approaching_lower': approaching_lower,
            'approaching_upper': approaching_upper,
            'total_range_ticks': total_range,
            'current_tick': current_tick,
            'tick_lower': tick_lower,
            'tick_upper': tick_upper
        }
        
    except Exception as e:
        logging.error(f"Error calculating range proximity: {e}")
        return {
            'proximity_status': 'error',
            'distance_to_lower_percent': None,
            'distance_to_upper_percent': None,
            'warning_threshold_reached': False,
            'error': str(e)
        }

def estimate_tick_from_price(price: float, decimals0: int, decimals1: int) -> Optional[int]:
    """
    Приблизительно оценивает тик из цены
    Это упрощенная версия - для точных расчетов нужна обратная функция к get_price_from_tick
    """
    try:
        # Логарифмическая связь между тиком и ценой
        # tick ≈ log(price) / log(1.0001) с поправкой на decimals
        import math
        
        # Корректируем цену с учетом decimals
        adjusted_price = price / (10 ** (decimals0 - decimals1))
        
        if adjusted_price <= 0:
            return None
            
        # Приблизительная формула (может потребоваться уточнение)
        tick = math.log(adjusted_price) / math.log(1.0001)
        return int(round(tick))
        
    except Exception as e:
        logging.warning(f"Error estimating tick from price {price}: {e}")
        return None

def filter_positions_approaching_bounds(positions: List[Dict[str, Any]], threshold_percent: float = 5.0) -> List[Dict[str, Any]]:
    """
    Фильтрует позиции, приближающиеся к границам диапазона
    
    Args:
        positions: Список позиций
        threshold_percent: Пороговый процент приближения (по умолчанию 5%)
        
    Returns:
        Список позиций, приближающихся к границам
    """
    approaching_positions = []
    
    for position in positions:
        proximity_info = calculate_range_proximity(position)
        
        if proximity_info.get('warning_threshold_reached', False):
            # Добавляем информацию о приближении к позиции
            position_with_proximity = position.copy()
            position_with_proximity['proximity_info'] = proximity_info
            approaching_positions.append(position_with_proximity)
    
    return approaching_positions

def format_proximity_warning(proximity_info: Dict[str, Any]) -> str:
    """
    Форматирует предупреждение о приближении к границам
    """
    status = proximity_info.get('proximity_status', 'unknown')
    
    if status == 'approaching_lower_bound':
        return f"⚠️ Approaching lower bound ({proximity_info['distance_to_lower_percent']:.1f}% from edge)"
    elif status == 'approaching_upper_bound':
        return f"⚠️ Approaching upper bound ({proximity_info['distance_to_upper_percent']:.1f}% from edge)"
    elif status == 'narrow_range_warning':
        return f"⚠️ Very narrow position (Lower: {proximity_info['distance_to_lower_percent']:.1f}%, Upper: {proximity_info['distance_to_upper_percent']:.1f}%)"
    else:
        return "⚠️ Range proximity warning" 