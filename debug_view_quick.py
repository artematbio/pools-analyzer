#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database_handler import SupabaseHandler
from datetime import datetime, timedelta

def debug_view_values():
    """Быстрая диагностика значений в bio_dao_lp_support view"""
    
    print("🔍 ДИАГНОСТИКА VIEW bio_dao_lp_support")
    print("=====================================")
    
    supabase_handler = SupabaseHandler()
    
    # 1. Проверяем view напрямую
    print("\n1️⃣ ТЕКУЩИЕ ЗНАЧЕНИЯ В VIEW (проблемные > $100K):")
    view_result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
    
    if view_result.data:
        problematic_found = False
        for row in view_result.data:
            pool_name = row.get('pool_name', 'N/A')
            our_pos = float(row.get('our_position_value_usd', 0))
            target = float(row.get('target_lp_value_usd', 0))
            gap = float(row.get('lp_gap_usd', 0))
            
            if our_pos > 100000:  # Показываем проблемные > $100K
                problematic_found = True
                print(f"   🚨 ПРОБЛЕМА: {pool_name}")
                print(f"      Our Position: ${our_pos:,.2f}")
                print(f"      Target: ${target:,.2f}")
                print(f"      Gap: ${gap:,.2f}")
                print()
        
        if not problematic_found:
            print("   ✅ Проблемных значений не найдено!")
            # Показываем несколько обычных для контроля
            for i, row in enumerate(view_result.data[:3]):
                pool_name = row.get('pool_name', 'N/A')
                our_pos = float(row.get('our_position_value_usd', 0))
                print(f"   📊 {pool_name}: ${our_pos:,.2f}")
    else:
        print("   ❌ View пустой!")
    
    # 2. Проверяем dao_pool_snapshots для поиска источника проблемы
    print("\n2️⃣ ПРОВЕРКА dao_pool_snapshots (последние записи):")
    
    two_days_ago = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    dao_result = supabase_handler.client.table('dao_pool_snapshots').select(
        'pool_name, network, our_position_value_usd, created_at'
    ).gte('created_at', two_days_ago).order('created_at', desc=True).execute()
    
    print(f"   📊 Найдено {len(dao_result.data)} записей за последние 2 дня")
    
    problematic_dao = False
    for row in dao_result.data:
        pool_name = row.get('pool_name', 'N/A')
        our_pos = float(row.get('our_position_value_usd', 0))
        network = row.get('network', 'N/A')
        created = row.get('created_at', 'N/A')
        
        if our_pos > 100000:  # Проблемные > $100K
            problematic_dao = True
            print(f"   🚨 ИСТОЧНИК ПРОБЛЕМЫ: {pool_name} ({network})")
            print(f"      Our Position: ${our_pos:,.2f}")
            print(f"      Создано: {created}")
            print()
    
    if not problematic_dao:
        print("   ✅ В dao_pool_snapshots проблемных значений не найдено!")
    
    # 3. Проверяем lp_position_snapshots для реальных значений
    print("\n3️⃣ РЕАЛЬНЫЕ ЗНАЧЕНИЯ В lp_position_snapshots:")
    
    positions_result = supabase_handler.client.table('lp_position_snapshots').select(
        'pool_name, network, position_value_usd, created_at'
    ).gte('created_at', two_days_ago).order('created_at', desc=True).execute()
    
    print(f"   📊 Найдено {len(positions_result.data)} позиций за последние 2 дня")
    
    # Группируем по пулам для суммирования
    pool_totals = {}
    for pos in positions_result.data:
        pool_name = pos.get('pool_name', 'N/A')
        network = pos.get('network', 'N/A')
        value = float(pos.get('position_value_usd', 0))
        
        key = f"{pool_name}_{network}"
        if key not in pool_totals:
            pool_totals[key] = {'total': 0, 'count': 0, 'pool_name': pool_name, 'network': network}
        
        pool_totals[key]['total'] += value
        pool_totals[key]['count'] += 1
    
    print("\n   📋 РЕАЛЬНЫЕ СУММЫ ПО ПУЛАМ:")
    for key, data in sorted(pool_totals.items(), key=lambda x: x[1]['total'], reverse=True):
        if data['total'] > 1000:  # Показываем только значимые позиции
            print(f"      💰 {data['pool_name']} ({data['network']}): ${data['total']:,.2f} ({data['count']} поз.)")
    
    # 4. Общая статистика
    total_portfolio = sum(data['total'] for data in pool_totals.values())
    print(f"\n   📊 ОБЩАЯ СТОИМОСТЬ ПОРТФЕЛЯ: ${total_portfolio:,.2f}")

if __name__ == "__main__":
    debug_view_values()
