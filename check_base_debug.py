#!/usr/bin/env python3

from database_handler import supabase_handler

def check_base_data():
    if not supabase_handler or not supabase_handler.is_connected():
        print('❌ Supabase не подключен')
        return

    # Проверяем последние позиции Base
    print("=== ПОЗИЦИИ BASE ===")
    result = supabase_handler.client.table('lp_position_snapshots').select('*').eq(
        'network', 'base'
    ).order('created_at', desc=True).limit(10).execute()

    print(f'📍 Найдено позиций Base: {len(result.data)}')
    for pos in result.data:
        pool_name = pos.get('pool_name', 'Unknown')
        pos_id = pos.get('position_mint', 'N/A')
        value = pos.get('position_value_usd', 0)
        pool_addr = pos.get('pool_id', 'N/A')
        print(f'  - {pool_name}: ID={pos_id}, Value=${value:,.2f}')
        print(f'    Pool Address: {pool_addr}')
        print()

    # Проверяем пулы Base
    print("=== ПУЛЫ BASE ===")
    pools_result = supabase_handler.client.table('lp_pool_snapshots').select('*').eq(
        'network', 'base'
    ).order('created_at', desc=True).limit(10).execute()

    print(f'📊 Найдено пулов Base: {len(pools_result.data)}')
    for pool in pools_result.data:
        pool_name = pool.get('pool_name', 'Unknown')
        tvl = pool.get('tvl_usd', 0)
        pool_addr = pool.get('pool_address', 'N/A')
        print(f'  - {pool_name}: TVL=${tvl:,.0f}')
        print(f'    Pool Address: {pool_addr}')
        print()

if __name__ == "__main__":
    check_base_data()