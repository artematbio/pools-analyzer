#!/usr/bin/env python3
"""
Проверка проблемы с Range Proximity Warning для Ethereum/Base
"""

import asyncio
import sys
import os
sys.path.append('..')

async def check_range_proximity_issue():
    """Проверяем почему Range Proximity Warning показывает только Solana"""
    
    print("🔍 ПРОВЕРКА RANGE PROXIMITY WARNING")
    print("=" * 50)
    
    # 1. Проверяем что alerting.py импортирует только Solana данные
    print("\n📋 АНАЛИЗ КОДА ALERTING.PY:")
    
    try:
        from alerting import AlertingSystem
        print("   ✅ AlertingSystem импортирован")
        
        # Проверяем метод check_range_proximity_positions
        import inspect
        source = inspect.getsource(AlertingSystem.check_range_proximity_positions)
        
        if "pool_analyzer" in source:
            print("   ❌ ПРОБЛЕМА: alerting.py импортирует только pool_analyzer (SOLANA)")
            print("      - pool_analyzer.py получает только Solana позиции")
            print("      - НЕТ импорта unified_positions_analyzer для Ethereum/Base")
        
        if "get_positions_from_multiple_wallets" in source:
            print("   📌 Функция get_positions_from_multiple_wallets используется")
            print("      - Эта функция ТОЛЬКО для Solana (из pool_analyzer.py)")
        
        print("\n🎯 РЕШЕНИЕ:")
        print("   Нужно ИЗМЕНИТЬ alerting.py чтобы получать позиции из:")
        print("   1. Solana (pool_analyzer.py)")
        print("   2. Ethereum (unified_positions_analyzer.py)")
        print("   3. Base (unified_positions_analyzer.py)")
        
    except Exception as e:
        print(f"   ❌ Ошибка анализа alerting.py: {e}")
    
    # 2. Проверяем какие данные есть в Supabase для range proximity
    print("\n📊 ДАННЫЕ В SUPABASE ДЛЯ RANGE PROXIMITY:")
    
    try:
        from database_handler import supabase_handler
        
        if not supabase_handler or not supabase_handler.is_connected():
            print("   ❌ Supabase не подключен!")
            return
        
        # Проверяем Ethereum позиции с tick данными
        eth_positions = supabase_handler.client.table('lp_position_snapshots').select(
            'position_mint, pool_name, tick_lower, tick_upper, position_value_usd'
        ).eq('network', 'ethereum').gt('position_value_usd', 100).order(
            'created_at', desc=True
        ).limit(5).execute()
        
        print(f"\n   🔷 ETHEREUM позиции (>${100}+):")
        if eth_positions.data:
            for pos in eth_positions.data:
                tick_lower = pos.get('tick_lower')
                tick_upper = pos.get('tick_upper')
                has_ticks = tick_lower is not None and tick_upper is not None
                print(f"   • {pos['pool_name']}: ${pos['position_value_usd']:.0f}")
                print(f"     Ticks: {tick_lower} → {tick_upper} {'✅' if has_ticks else '❌'}")
        else:
            print("   ❌ Нет Ethereum позиций!")
        
        # Проверяем Base позиции с tick данными
        base_positions = supabase_handler.client.table('lp_position_snapshots').select(
            'position_mint, pool_name, tick_lower, tick_upper, position_value_usd'
        ).eq('network', 'base').gt('position_value_usd', 100).order(
            'created_at', desc=True
        ).limit(5).execute()
        
        print(f"\n   🔶 BASE позиции (>${100}+):")
        if base_positions.data:
            for pos in base_positions.data:
                tick_lower = pos.get('tick_lower')
                tick_upper = pos.get('tick_upper')
                has_ticks = tick_lower is not None and tick_upper is not None
                print(f"   • {pos['pool_name']}: ${pos['position_value_usd']:.0f}")
                print(f"     Ticks: {tick_lower} → {tick_upper} {'✅' if has_ticks else '❌'}")
        else:
            print("   ❌ Нет Base позиций!")
            
    except Exception as e:
        print(f"   ❌ Ошибка проверки данных: {e}")
    
    print("\n" + "=" * 50)
    print("🔧 НЕОБХОДИМЫЕ ИСПРАВЛЕНИЯ:")
    print("1. Изменить alerting.py - добавить Ethereum/Base позиции")
    print("2. Убедиться что tick_lower/tick_upper сохраняются корректно")
    print("3. Протестировать range proximity для всех сетей")

if __name__ == "__main__":
    asyncio.run(check_range_proximity_issue()) 