#!/usr/bin/env python3
"""
Скрипт для очистки дублей в Supabase
"""

from database_handler import supabase_handler

def cleanup_duplicates():
    print('🗑️ Выполняю очистку дублей в Supabase...')
    
    try:
        # 1. Сначала смотрим что есть
        positions = supabase_handler.client.table('lp_position_snapshots').select('id, position_mint, network, created_at').eq('network', 'base').execute()
        print(f'📊 Найдено {len(positions.data)} позиций Base до очистки')
        
        pools = supabase_handler.client.table('lp_pool_snapshots').select('id, pool_address, network, tvl_usd, created_at').eq('network', 'base').execute()
        print(f'📊 Найдено {len(pools.data)} пулов Base до очистки')
        
        # 2. Удаляем старые записи пулов с TVL=0
        zero_tvl_pools = supabase_handler.client.table('lp_pool_snapshots').delete().eq('network', 'base').eq('tvl_usd', 0).execute()
        print(f'✅ Удалено пулов с TVL=0: {len(zero_tvl_pools.data) if zero_tvl_pools.data else "неизвестно"}')
        
        # 3. Удаляем старые дубли позиций (оставляем только последние по времени)
        # Группируем позиции по position_mint
        position_groups = {}
        for pos in positions.data:
            mint = pos['position_mint']
            if mint not in position_groups:
                position_groups[mint] = []
            position_groups[mint].append(pos)
        
        deleted_positions = 0
        for mint, pos_list in position_groups.items():
            if len(pos_list) > 1:
                # Сортируем по времени создания, оставляем последний
                pos_list.sort(key=lambda x: x['created_at'], reverse=True)
                latest = pos_list[0]
                
                # Удаляем все кроме последнего
                for pos in pos_list[1:]:
                    supabase_handler.client.table('lp_position_snapshots').delete().eq('id', pos['id']).execute()
                    deleted_positions += 1
                    print(f'   Удален дубль позиции {mint}: id={pos["id"]}')
        
        print(f'✅ Удалено дублей позиций: {deleted_positions}')
        
        # 4. Проверяем результат
        pools_after = supabase_handler.client.table('lp_pool_snapshots').select('id, pool_address, network, tvl_usd').eq('network', 'base').execute()
        print(f'📊 Осталось {len(pools_after.data)} пулов Base после очистки')
        
        positions_after = supabase_handler.client.table('lp_position_snapshots').select('id, position_mint, network').eq('network', 'base').execute()
        print(f'📊 Осталось {len(positions_after.data)} позиций Base после очистки')
        
        print('\n🏊 АКТУАЛЬНЫЕ ПУЛЫ BASE:')
        for pool in pools_after.data:
            print(f'   Pool {pool.get("pool_address", "unknown")[:10]}...: TVL=${pool.get("tvl_usd", 0):,.0f}')
        
        print('\n📍 АКТУАЛЬНЫЕ ПОЗИЦИИ BASE:')
        for pos in positions_after.data:
            print(f'   Position {pos.get("position_mint", "unknown")}')
        
        print('\n✅ Очистка дублей завершена!')
        
    except Exception as e:
        print(f'❌ Ошибка: {e}')
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    cleanup_duplicates()
