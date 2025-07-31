#!/usr/bin/env python3
from database_handler import SupabaseHandler

def check_view_latest():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 ДЕТАЛЬНАЯ ПРОВЕРКА VIEW ПОСЛЕ SQL ИЗМЕНЕНИЙ\n')
    
    # 1. Проверяем сколько записей в view
    view_result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
    print(f'📊 View bio_dao_lp_support: {len(view_result.data)} записей\n')
    
    # 2. Сравним с количеством в dao_pool_snapshots
    dao_result = supabase_handler.client.table('dao_pool_snapshots').select(
        'pool_name, network, is_bio_pair, token_fdv_usd, our_position_value_usd, created_at'
    ).gte('created_at', '2025-07-30T00:00:00Z').execute()
    
    bio_pairs = [r for r in dao_result.data if r.get('is_bio_pair', False) and r.get('token_fdv_usd', 0) > 0]
    print(f'📊 DAO pool snapshots (BIO пары с FDV > 0): {len(bio_pairs)} записей')
    print(f'📊 Всего dao_pool_snapshots за сегодня: {len(dao_result.data)} записей\n')
    
    # 3. Проверяем FDV проблемы
    print('🔍 ПРОВЕРКА FDV В VIEW:')
    token_fdv_map = {}
    for record in view_result.data:
        token = record['token_symbol']
        network = record['network_display']
        fdv = record['token_fdv_usd']
        
        if token not in token_fdv_map:
            token_fdv_map[token] = {}
        token_fdv_map[token][network] = fdv
    
    fdv_problems = []
    for token, networks in token_fdv_map.items():
        if len(networks) > 1:
            fdv_values = list(networks.values())
            if len(set(fdv_values)) > 1:
                fdv_problems.append(token)
                print(f'❌ {token}: {networks}')
            else:
                print(f'✅ {token}: единый FDV ${fdv_values[0]:,.0f}')
    
    if not fdv_problems:
        print('✅ Все FDV корректны!')
    print()
    
    # 4. Проверяем позиции
    print('💰 ПОЗИЦИИ В VIEW:')
    view_positions = []
    for record in view_result.data:
        if record['our_position_value_usd'] > 0:
            view_positions.append({
                'pool': record['pool_name'],
                'network': record['network_display'],
                'value': record['our_position_value_usd'],
                'timestamp': record['snapshot_timestamp'][:16]
            })
    
    view_positions.sort(key=lambda x: x['value'], reverse=True)
    for pos in view_positions:
        print(f'  💰 {pos["pool"]} ({pos["network"]}): ${pos["value"]:,.2f} - {pos["timestamp"]}')
    
    print(f'\n📊 Позиций в view: {len(view_positions)}')
    
    # 5. Проверяем позиции в dao_pool_snapshots
    print('\n💰 ПОЗИЦИИ В DAO_POOL_SNAPSHOTS:')
    dao_positions = []
    for record in dao_result.data:
        if record['our_position_value_usd'] > 0:
            dao_positions.append({
                'pool': record['pool_name'],
                'network': record['network'],
                'value': record['our_position_value_usd'],
                'is_bio': record.get('is_bio_pair', False),
                'timestamp': record['created_at'][:16]
            })
    
    dao_positions.sort(key=lambda x: x['value'], reverse=True)
    for pos in dao_positions:
        bio_marker = "🔥" if pos['is_bio'] else "  "
        print(f'{bio_marker} {pos["pool"]} ({pos["network"]}): ${pos["value"]:,.2f} - BIO pair: {pos["is_bio"]} - {pos["timestamp"]}')
    
    print(f'\n📊 Позиций в dao_pool_snapshots: {len(dao_positions)}')
    print(f'📊 BIO пар с позициями: {len([p for p in dao_positions if p["is_bio"]])}')
    
    # 6. Анализ расхождений
    print('\n🔍 АНАЛИЗ РАСХОЖДЕНИЙ:')
    if len(view_positions) < len(dao_positions):
        missing = len(dao_positions) - len(view_positions)
        print(f'❌ В view отсутствует {missing} позиций!')
        
        view_pools = {f"{p['pool']}_{p['network']}" for p in view_positions}
        dao_pools = {f"{p['pool']}_{p['network']}" for p in dao_positions}
        
        missing_pools = dao_pools - view_pools
        print('❌ Отсутствующие пулы в view:')
        for pool_key in missing_pools:
            print(f'  - {pool_key}')
    else:
        print('✅ Количество позиций совпадает')

if __name__ == '__main__':
    check_view_latest() 