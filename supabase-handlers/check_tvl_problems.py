#!/usr/bin/env python3
"""
Проверка проблем с TVL для Ethereum/Base в telegram отчетах
"""

import asyncio
import sys
import os
sys.path.append('..')
from database_handler import supabase_handler

async def check_tvl_problems():
    """Проверяем TVL данные в Supabase для Ethereum/Base"""
    
    print("🔍 ПРОВЕРКА TVL ПРОБЛЕМ В ETHEREUM/BASE ОТЧЕТАХ")
    print("=" * 60)
    
    if not supabase_handler or not supabase_handler.is_connected():
        print("❌ Supabase не подключен!")
        return
    
    # 1. Проверяем позиции Ethereum
    print("\n📊 ETHEREUM ПОЗИЦИИ:")
    eth_positions = supabase_handler.client.table('lp_position_snapshots').select(
        'position_mint, pool_id, pool_name, position_value_usd, created_at'
    ).eq('network', 'ethereum').order('created_at', desc=True).limit(10).execute()
    
    if eth_positions.data:
        print(f"   Найдено {len(eth_positions.data)} позиций")
        for pos in eth_positions.data:
            print(f"   • {pos['pool_name']}: ${pos['position_value_usd']:.2f} (pool_id: {pos['pool_id'][:8]}...)")
    else:
        print("   ❌ Позиции Ethereum не найдены!")
    
    # 2. Проверяем пулы Ethereum и их TVL
    print("\n🏊 ETHEREUM POOLS TVL:")
    eth_pools = supabase_handler.client.table('lp_pool_snapshots').select(
        'pool_address, pool_name, tvl_usd, created_at'
    ).eq('network', 'ethereum').order('created_at', desc=True).limit(10).execute()
    
    if eth_pools.data:
        print(f"   Найдено {len(eth_pools.data)} пулов")
        for pool in eth_pools.data:
            tvl = pool['tvl_usd'] if pool['tvl_usd'] else 0
            print(f"   • {pool['pool_name']}: TVL = ${tvl:,.0f}")
    else:
        print("   ❌ Пулы Ethereum не найдены!")
    
    # 3. Проверяем JOIN между positions и pools для Ethereum
    print("\n🔗 ETHEREUM JOIN ПРОВЕРКА:")
    if eth_positions.data and eth_pools.data:
        for pos in eth_positions.data[:3]:  # Проверяем первые 3 позиции
            pool_id = pos['pool_id']
            matching_pool = supabase_handler.client.table('lp_pool_snapshots').select(
                'tvl_usd, pool_name'
            ).eq('pool_address', pool_id).eq('network', 'ethereum').order('created_at', desc=True).limit(1).execute()
            
            if matching_pool.data:
                tvl = matching_pool.data[0]['tvl_usd'] if matching_pool.data[0]['tvl_usd'] else 0
                print(f"   ✅ {pos['pool_name']}: pool_id найден, TVL = ${tvl:,.0f}")
            else:
                print(f"   ❌ {pos['pool_name']}: pool_id {pool_id[:8]}... НЕ НАЙДЕН в lp_pool_snapshots!")
    
    print("\n" + "=" * 60)
    
    # 4. Проверяем позиции Base
    print("\n📊 BASE ПОЗИЦИИ:")
    base_positions = supabase_handler.client.table('lp_position_snapshots').select(
        'position_mint, pool_id, pool_name, position_value_usd, created_at'
    ).eq('network', 'base').order('created_at', desc=True).limit(10).execute()
    
    if base_positions.data:
        print(f"   Найдено {len(base_positions.data)} позиций")
        for pos in base_positions.data:
            print(f"   • {pos['pool_name']}: ${pos['position_value_usd']:.2f} (pool_id: {pos['pool_id'][:8]}...)")
    else:
        print("   ❌ Позиции Base не найдены!")
    
    # 5. Проверяем пулы Base и их TVL
    print("\n🏊 BASE POOLS TVL:")
    base_pools = supabase_handler.client.table('lp_pool_snapshots').select(
        'pool_address, pool_name, tvl_usd, created_at'
    ).eq('network', 'base').order('created_at', desc=True).limit(10).execute()
    
    if base_pools.data:
        print(f"   Найдено {len(base_pools.data)} пулов")
        for pool in base_pools.data:
            tvl = pool['tvl_usd'] if pool['tvl_usd'] else 0
            print(f"   • {pool['pool_name']}: TVL = ${tvl:,.0f}")
    else:
        print("   ❌ Пулы Base не найдены!")
    
    # 6. Проверяем JOIN между positions и pools для Base
    print("\n🔗 BASE JOIN ПРОВЕРКА:")
    if base_positions.data and base_pools.data:
        for pos in base_positions.data[:3]:  # Проверяем первые 3 позиции
            pool_id = pos['pool_id']
            matching_pool = supabase_handler.client.table('lp_pool_snapshots').select(
                'tvl_usd, pool_name'
            ).eq('pool_address', pool_id).eq('network', 'base').order('created_at', desc=True).limit(1).execute()
            
            if matching_pool.data:
                tvl = matching_pool.data[0]['tvl_usd'] if matching_pool.data[0]['tvl_usd'] else 0
                print(f"   ✅ {pos['pool_name']}: pool_id найден, TVL = ${tvl:,.0f}")
            else:
                print(f"   ❌ {pos['pool_name']}: pool_id {pool_id[:8]}... НЕ НАЙДЕН в lp_pool_snapshots!")
    
    print("\n🎯 ВЫВОДЫ:")
    print("1. Если TVL = 0 или N/A - проблема в unified_positions_analyzer.py")
    print("2. Если pool_id не найден - проблема в сохранении пулов")
    print("3. Если JOIN не работает - проблема в multichain_report_generator.py")

if __name__ == "__main__":
    asyncio.run(check_tvl_problems()) 