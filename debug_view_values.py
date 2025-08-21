#!/usr/bin/env python3

import os
from supabase import create_client, Client
from datetime import datetime, timedelta

# Подключение к Supabase
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase: Client = create_client(url, key)

def debug_view_values():
    """Диагностика значений в bio_dao_lp_support view"""
    
    print("🔍 ДИАГНОСТИКА VIEW bio_dao_lp_support")
    print("=====================================")
    
    # 1. Проверяем view напрямую
    print("\n1️⃣ ТЕКУЩИЕ ЗНАЧЕНИЯ В VIEW:")
    view_result = supabase.table('bio_dao_lp_support').select('*').execute()
    
    if view_result.data:
        for row in view_result.data:
            pool_name = row.get('pool_name', 'N/A')
            our_pos = row.get('our_position_value_usd', 0)
            target = row.get('target_lp_value_usd', 0)
            gap = row.get('lp_gap_usd', 0)
            
            print(f"   🏊 {pool_name}")
            print(f"      Our Position: ${our_pos:,.2f}")
            print(f"      Target: ${target:,.2f}")
            print(f"      Gap: ${gap:,.2f}")
            print()
    else:
        print("   ❌ View пустой!")
    
    # 2. Проверяем исходные данные в lp_position_snapshots
    print("\n2️⃣ ИСХОДНЫЕ ДАННЫЕ В lp_position_snapshots:")
    
    # Получаем свежие позиции (последние 2 дня)
    two_days_ago = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')
    
    positions_result = supabase.table('lp_position_snapshots').select(
        'pool_id, pool_name, network, position_value_usd, created_at'
    ).gte('created_at', two_days_ago).order('created_at', desc=True).execute()
    
    print(f"   📊 Найдено {len(positions_result.data)} позиций за последние 2 дня")
    
    # Группируем по пулам
    pool_positions = {}
    for pos in positions_result.data:
        pool_key = f"{pos['pool_id']}_{pos['network']}"
        pool_name = pos.get('pool_name', 'N/A')
        value = float(pos.get('position_value_usd', 0))
        
        if pool_key not in pool_positions:
            pool_positions[pool_key] = {
                'pool_name': pool_name,
                'network': pos['network'],
                'positions': [],
                'total_value': 0
            }
        
        pool_positions[pool_key]['positions'].append({
            'value': value,
            'created_at': pos['created_at']
        })
        pool_positions[pool_key]['total_value'] += value
    
    print("\n   📋 ГРУППИРОВКА ПО ПУЛАМ:")
    for pool_key, data in pool_positions.items():
        if data['total_value'] > 0:  # Только пулы с позициями
            print(f"      🎯 {data['pool_name']} ({data['network']})")
            print(f"         Pool Key: {pool_key}")
            print(f"         Позиций: {len(data['positions'])}")
            print(f"         Общая стоимость: ${data['total_value']:,.2f}")
            
            # Показываем последние позиции
            for i, pos in enumerate(data['positions'][:3]):  # Первые 3
                print(f"           {i+1}. ${pos['value']:,.2f} ({pos['created_at']})")
            
            if len(data['positions']) > 3:
                print(f"           ... и еще {len(data['positions']) - 3} позиций")
            print()
    
    # 3. Проверяем dao_pool_snapshots
    print("\n3️⃣ ДАННЫЕ В dao_pool_snapshots:")
    
    dao_result = supabase.table('dao_pool_snapshots').select(
        'pool_address, pool_name, network, our_position_value_usd, target_lp_value_usd, lp_gap_usd, created_at'
    ).gte('created_at', two_days_ago).order('created_at', desc=True).execute()
    
    print(f"   📊 Найдено {len(dao_result.data)} записей в dao_pool_snapshots")
    
    for row in dao_result.data:
        pool_name = row.get('pool_name', 'N/A')
        our_pos = float(row.get('our_position_value_usd', 0))
        target = float(row.get('target_lp_value_usd', 0))
        gap = float(row.get('lp_gap_usd', 0))
        network = row.get('network', 'N/A')
        
        if our_pos > 1000000:  # Показываем только проблемные (> $1M)
            print(f"   🚨 ПРОБЛЕМА: {pool_name} ({network})")
            print(f"      Our Position: ${our_pos:,.2f}")
            print(f"      Target: ${target:,.2f}")
            print(f"      Gap: ${gap:,.2f}")
            print(f"      Created: {row.get('created_at', 'N/A')}")
            print()
    
    # 4. Диагностика конкретных проблемных пулов
    print("\n4️⃣ ДИАГНОСТИКА КОНКРЕТНЫХ ПУЛОВ:")
    
    # Ищем пулы с большими значениями в dao_pool_snapshots
    problematic_pools = [row for row in dao_result.data if float(row.get('our_position_value_usd', 0)) > 1000000]
    
    for prob_pool in problematic_pools[:5]:  # Топ-5 проблемных
        pool_name = prob_pool.get('pool_name', 'N/A')
        pool_addr = prob_pool.get('pool_address', 'N/A')
        network = prob_pool.get('network', 'N/A')
        
        print(f"   🔍 АНАЛИЗ: {pool_name}")
        print(f"      Pool Address: {pool_addr}")
        print(f"      Network: {network}")
        
        # Ищем соответствующие позиции
        pool_key_variants = [
            f"{pool_addr.lower()}_{network}",
            f"{pool_addr}_{network}",
            pool_addr.lower(),
            pool_addr
        ]
        
        found_positions = []
        for variant in pool_key_variants:
            if variant in pool_positions:
                found_positions = pool_positions[variant]['positions']
                print(f"      ✅ Найдены позиции по ключу: {variant}")
                break
        
        if found_positions:
            print(f"      📊 Позиций найдено: {len(found_positions)}")
            total = sum(pos['value'] for pos in found_positions)
            print(f"      💰 Реальная сумма: ${total:,.2f}")
        else:
            print(f"      ❌ Позиции НЕ НАЙДЕНЫ!")
            print(f"      🔍 Проверенные ключи:")
            for variant in pool_key_variants:
                print(f"         - {variant}")
        
        print()

if __name__ == "__main__":
    debug_view_values()
