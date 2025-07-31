#!/usr/bin/env python3
from database_handler import SupabaseHandler

def debug_view_sql():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ПРОБЛЕМЫ SQL В VIEW...\n')
    
    # 1. Проверяем BIO пары в dao_pool_snapshots детально
    print('📊 ВСЕ BIO ПАРЫ В DAO_POOL_SNAPSHOTS (сегодня):')
    
    dao_result = supabase_handler.client.table('dao_pool_snapshots').select(
        'pool_name, network, token_symbol, token_fdv_usd, our_position_value_usd, snapshot_timestamp, created_at, is_bio_pair'
    ).gte('created_at', '2025-07-30T00:00:00Z').eq('is_bio_pair', True).gt('token_fdv_usd', 0).order('snapshot_timestamp', desc=True).execute()
    
    print(f'Найдено {len(dao_result.data)} BIO пар с FDV > 0\n')
    
    # Группируем по токенам для анализа
    tokens_data = {}
    for record in dao_result.data:
        token = record['token_symbol']
        network = record['network']
        key = f"{token}_{network}"
        
        if key not in tokens_data:
            tokens_data[key] = []
        
        tokens_data[key].append({
            'pool': record['pool_name'],
            'fdv': record['token_fdv_usd'],
            'position': record['our_position_value_usd'],
            'snapshot_ts': record['snapshot_timestamp'][:16],
            'created_at': record['created_at'][:16]
        })
    
    # Показываем данные по проблемным токенам
    problem_tokens = ['NEURON', 'VITA']
    
    for token in problem_tokens:
        print(f'🔍 {token} данные в DAO_POOL_SNAPSHOTS:')
        
        token_records = []
        for key, records in tokens_data.items():
            if key.startswith(f"{token}_"):
                network = key.split('_')[1]
                for record in records:
                    token_records.append({
                        'network': network,
                        **record
                    })
        
        # Сортируем по snapshot_timestamp DESC
        token_records.sort(key=lambda x: x['snapshot_ts'], reverse=True)
        
        for record in token_records:
            print(f"  {record['network']}: {record['pool']} - FDV ${record['fdv']:,.0f} - Pos ${record['position']:,.2f}")
            print(f"    snapshot_ts: {record['snapshot_ts']}, created_at: {record['created_at']}")
        print()
    
    # 2. Проверяем отсутствующие позиции
    print('🔍 ОТСУТСТВУЮЩИЕ ПОЗИЦИИ В VIEW:')
    
    missing_pools = ['BIO/WETH', 'SOL/BIO']
    
    for pool_name in missing_pools:
        print(f'\n{pool_name} в dao_pool_snapshots:')
        
        matching_records = []
        for record in dao_result.data:
            if pool_name in record['pool_name'] and record['our_position_value_usd'] > 0:
                matching_records.append(record)
        
        for record in matching_records:
            print(f"  {record['network']}: {record['pool_name']} - FDV ${record['token_fdv_usd']:,.0f} - Pos ${record['our_position_value_usd']:,.2f}")
            print(f"    snapshot_ts: {record['snapshot_timestamp'][:16]}, created_at: {record['created_at'][:16]}")
            print(f"    is_bio_pair: {record['is_bio_pair']}")
    
    # 3. Проверяем фильтрацию по дате
    print('\n📅 ПРОВЕРКА ФИЛЬТРАЦИИ ПО ДАТЕ:')
    
    # Тестируем фильтр snapshot_timestamp >= CURRENT_DATE
    test_timestamps = [
        '2025-07-30T09:12:00',
        '2025-07-30T15:22:00', 
        '2025-07-30T15:24:00'
    ]
    
    for ts in test_timestamps:
        count = len([r for r in dao_result.data if r['snapshot_timestamp'] >= f'{ts}Z'])
        print(f"  snapshot_timestamp >= {ts}: {count} записей")
    
    # 4. Предлагаем исправленный SQL
    print(f'\n🔧 ПРЕДЛАГАЕМОЕ ИСПРАВЛЕНИЕ SQL:')
    
    # Найдем максимальный snapshot_timestamp
    max_snapshot_ts = max([r['snapshot_timestamp'] for r in dao_result.data])
    print(f"Максимальный snapshot_timestamp: {max_snapshot_ts}")
    
    print('''
ПРОБЛЕМА в SQL:
1. ROW_NUMBER() PARTITION BY token_symbol, network, pool_address - слишком детальная группировка
2. Фильтр snapshot_timestamp >= CURRENT_DATE может исключать записи
3. Нужно группировать по token_symbol, network только

ИСПРАВЛЕННЫЙ SQL:
''')

if __name__ == '__main__':
    debug_view_sql() 