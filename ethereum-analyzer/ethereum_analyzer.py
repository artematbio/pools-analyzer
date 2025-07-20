"""
Ethereum Uniswap v3 Analyzer - генерация отчетов по позициям
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any
import sys
import os

# Добавляем пути для импортов
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))

from ethereum.uniswap_positions import get_user_positions_filtered
from ethereum.contracts.uniswap_abis import get_token_symbol
from ethereum.uniswap_market_data import fetch_uniswap_subgraph_data

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def format_ethereum_report(analysis_data: Dict[str, Any]) -> str:
    """
    Форматирует отчет по Ethereum позициям в стиле Raydium
    
    Args:
        analysis_data: Данные анализа позиций
        
    Returns:
        Отформатированный текстовый отчет
    """
    
    if "error" in analysis_data:
        return f"❌ Ошибка анализа: {analysis_data['error']}"
    
    positions = analysis_data.get("positions", [])
    total_value = analysis_data.get("total_value_usd", 0)
    wallet = analysis_data.get("wallet_address", "Unknown")
    total_positions = analysis_data.get("total_positions", 0)
    filtered_positions = analysis_data.get("filtered_positions", 0)
    filtered_out = analysis_data.get("filtered_out", 0)
    min_value_filter = analysis_data.get("min_value_filter", 1000)
    pools_market_data = analysis_data.get("pools_market_data", {})
    
    # Группируем позиции по пулам
    pools_data = {}
    for position in positions:
        pool_address = position.get("pool_address", "Unknown")
        
        if pool_address not in pools_data:
            # Получаем информацию о токенах из первой позиции пула
            value_analysis = position.get("value_analysis", {})
            token0_symbol = value_analysis.get("token0_symbol", "UNKNOWN")
            token1_symbol = value_analysis.get("token1_symbol", "UNKNOWN")
            
            pools_data[pool_address] = {
                "pool_address": pool_address,
                "token0_symbol": token0_symbol,
                "token1_symbol": token1_symbol,
                "positions": [],
                "total_pool_value": 0,
                "total_fees": 0,
                "in_range_count": 0,
                "out_of_range_count": 0
            }
        
        # Добавляем позицию к пулу
        pools_data[pool_address]["positions"].append(position)
        pools_data[pool_address]["total_pool_value"] += position.get("value_analysis", {}).get("value_usd", 0)
        pools_data[pool_address]["total_fees"] += position.get("fees_analysis", {}).get("total_fees_usd", 0)
        
        # Подсчитываем статус позиций
        if position.get("range_analysis", {}).get("in_range", False):
            pools_data[pool_address]["in_range_count"] += 1
        else:
            pools_data[pool_address]["out_of_range_count"] += 1
    
    # Сортируем пулы по общей стоимости
    sorted_pools = sorted(pools_data.values(), key=lambda x: x["total_pool_value"], reverse=True)
    
    # Генерируем отчет
    current_time = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    
    report = []
    report.append("=" * 60)
    report.append("ETHEREUM UNISWAP V3 POSITIONS ANALYSIS REPORT")
    report.append("=" * 60)
    report.append("")
    report.append(f"Generated: {current_time} UTC")
    report.append(f"Wallet: {wallet}")
    report.append(f"Total Positions Found: {total_positions}")
    report.append(f"Positions in Report: {filtered_positions} (min value ${min_value_filter})")
    if filtered_out > 0:
        report.append(f"Positions Filtered Out: {filtered_out}")
    report.append(f"Total Portfolio Value: ${total_value:,.2f}")
    report.append("")
    
    # Добавляем информацию по каждому пулу
    for pool_idx, pool_data in enumerate(sorted_pools, 1):
        token_pair = f"{pool_data['token0_symbol']}/{pool_data['token1_symbol']}"
        
        report.append(f"POOL {pool_idx}: {token_pair}")
        report.append("-" * 40)
        report.append("")
        
        # Информация о пуле
        report.append(f"Pool Address: {pool_data['pool_address']}")
        report.append("")
        
        # Добавляем market data из Subgraph (Phase 5) в стиле Raydium
        pool_addr = pool_data['pool_address']
        if pool_addr in pools_market_data:
            market_data = pools_market_data[pool_addr]
            
            # TOKEN PRICES секция
            report.append("TOKEN PRICES:")
            token0_symbol = market_data.get('token0', {}).get('symbol', pool_data['token0_symbol'])
            token1_symbol = market_data.get('token1', {}).get('symbol', pool_data['token1_symbol'])
            token0_price = market_data.get('token0_price', 0)
            token1_price = market_data.get('token1_price', 0)
            
            report.append(f"  {token0_symbol}: ${token0_price:.6f}")
            report.append(f"  {token1_symbol}: ${token1_price:.6f}")
            report.append("")
            
            # TVL & VOLUMES секция
            report.append("TVL & VOLUMES:")
            tvl_usd = market_data.get('tvl_usd', 0)
            volume_usd = market_data.get('volume_usd', 0)
            fee_tier = market_data.get('fee_tier', 0) / 10000
            
            report.append(f"  Pool TVL: ${tvl_usd:,.2f}")
            report.append(f"  24h TVL change %: N/A")  # TODO: можно добавить расчет из исторических данных
            report.append(f"  24h Volume: ${volume_usd:,.2f}")
            
            # Daily volumes за последние 7 дней
            historical_data = market_data.get('historical_data', [])
            if historical_data:
                report.append("")
                report.append("Daily volumes (7d):")
                for day_data in historical_data[-7:]:
                    date_timestamp = day_data.get('date', 0)
                    date_str = datetime.fromtimestamp(date_timestamp).strftime('%Y-%m-%d')
                    day_volume = day_data.get('volume_usd', 0)
                    report.append(f"  {date_str}: ${day_volume:,.2f}")
        
        report.append("")
        
        # Позиции
        report.append("POSITIONS:")
        report.append(f"  Active positions: {len(pool_data['positions'])}")
        report.append(f"  Total position value: ${pool_data['total_pool_value']:,.2f}")
        report.append(f"  Pending yield (fees): ${pool_data['total_fees']:,.2f}")
        report.append(f"  In range: {pool_data['in_range_count']}, Out of range: {pool_data['out_of_range_count']}")
        report.append("")
        
        # Детали позиций
        report.append("Position details:")
        for pos_idx, position in enumerate(pool_data['positions'], 1):
            token_id = position.get("token_id", "Unknown")
            value_usd = position.get("value_analysis", {}).get("value_usd", 0)
            fees_usd = position.get("fees_analysis", {}).get("total_fees_usd", 0)
            in_range = position.get("range_analysis", {}).get("in_range", False)
            status_emoji = "✅" if in_range else "❌"
            status_text = "In range" if in_range else "Out of range"
            
            # Получаем информацию о составе позиции
            value_analysis = position.get("value_analysis", {})
            token0_amount = value_analysis.get("token0_amount_formatted", value_analysis.get("token0_amount", 0))
            token1_amount = value_analysis.get("token1_amount_formatted", value_analysis.get("token1_amount", 0))
            token0_symbol = value_analysis.get("token0_symbol", "TOKEN0")
            token1_symbol = value_analysis.get("token1_symbol", "TOKEN1")
            
            report.append(f"  {pos_idx}. Token ID: {token_id}")
            report.append(f"     Value: ${value_usd:,.2f}")
            report.append(f"     Composition: {token0_amount:,.2f} {token0_symbol} + {token1_amount:,.2f} {token1_symbol}")
            report.append(f"     Fees: ${fees_usd:,.2f}")
            report.append(f"     Status: {status_emoji} {status_text}")
            
            # Добавляем информацию о диапазоне
            range_analysis = position.get("range_analysis", {})
            if "current_tick" in range_analysis and "tick_lower" in range_analysis and "tick_upper" in range_analysis:
                current_tick = range_analysis["current_tick"]
                tick_lower = range_analysis["tick_lower"]
                tick_upper = range_analysis["tick_upper"]
                report.append(f"     Range: {tick_lower} to {tick_upper} (current: {current_tick})")
            
        report.append("")
        report.append("-" * 40)
        report.append("")
    
    # Итоговая статистика
    report.append("SUMMARY:")
    report.append(f"Total portfolio value: ${total_value:,.2f}")
    report.append(f"Total positions in report: {filtered_positions}")
    total_fees = sum(pos.get("fees_analysis", {}).get("total_fees_usd", 0) for pos in positions)
    report.append(f"Total pending yield: ${total_fees:,.2f}")
    report.append("")
    report.append("=" * 60)
    report.append("Report generated by Ethereum Uniswap v3 Analyzer")
    report.append("Next analysis: Manual execution")
    report.append("=" * 60)
    
    return "\n".join(report)


async def analyze_ethereum_wallet(wallet_address: str, min_value_usd: float = 1000.0) -> str:
    """
    Анализирует Ethereum кошелек и возвращает отформатированный отчет
    
    Args:
        wallet_address: Адрес кошелька для анализа
        min_value_usd: Минимальная стоимость позиции для включения в отчет
        
    Returns:
        Отформатированный текстовый отчет
    """
    print(f"🚀 Начинаем анализ Ethereum кошелька: {wallet_address}")
    print(f"💰 Минимальная стоимость позиции: ${min_value_usd}")
    
    try:
        # Получаем данные позиций с фильтрацией
        analysis_data = await get_user_positions_filtered(wallet_address, min_value_usd)
        
        # Получаем адреса пулов из позиций для market data
        pool_addresses = []
        if "positions" in analysis_data and analysis_data["positions"]:
            for position in analysis_data["positions"]:
                pool_addr = position.get("pool_address")
                if pool_addr and pool_addr not in pool_addresses:
                    pool_addresses.append(pool_addr)
        
        # Получаем рыночные данные пулов через Subgraph (Phase 5)
        pools_market_data = {}
        if pool_addresses:
            print(f"📊 Получение market data для {len(pool_addresses)} пулов через Uniswap Subgraph...")
            try:
                pools_market_data = await fetch_uniswap_subgraph_data(pool_addresses)
                print(f"✅ Получены market data для {len(pools_market_data)} пулов")
            except Exception as e:
                print(f"⚠️ Subgraph недоступен, пропускаем market data: {e}")
        
        # Добавляем market data в анализ
        analysis_data["pools_market_data"] = pools_market_data
        
        # Форматируем отчет  
        report = format_ethereum_report(analysis_data)
        
        # Сохраняем отчет в файл
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')
        filename = f"ethereum_positions_report_{timestamp}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(report)
        
        print(f"✅ Отчет сохранен: {filename}")
        
        return report
        
    except Exception as e:
        logger.error(f"❌ Ошибка анализа: {e}")
        import traceback
        traceback.print_exc()
        return f"❌ Ошибка анализа кошелька: {str(e)}"


async def main():
    """Основная функция для тестирования анализатора"""
    
    # Тестовый кошелек
    test_wallet = "0x31AAc4021540f61fe20c3dAffF64BA6335396850"
    
    print("🔍 Ethereum Uniswap v3 Analyzer")
    print("=" * 50)
    
    # Анализируем кошелек
    report = await analyze_ethereum_wallet(test_wallet, min_value_usd=1000.0)
    
    # Сохраняем отчет в файл
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"ethereum_positions_report_{timestamp}.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report)
    
    print(f"\n📄 Отчет сохранен в файл: {filename}")
    print("\n" + "=" * 50)
    print("📊 ОТЧЕТ:")
    print("=" * 50)
    print(report)


if __name__ == "__main__":
    asyncio.run(main()) 