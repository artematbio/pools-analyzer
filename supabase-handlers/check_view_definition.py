#!/usr/bin/env python3
import sys
sys.path.append('..')
from database_handler import SupabaseHandler

def check_view_definition():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 Проверка определения view bio_dao_lp_support...\n')
    
    # Попробуем разные способы получить определение view
    try:
        # Способ 1: через information_schema
        result = supabase_handler.client.rpc('sql', {
            'query': '''
            SELECT view_definition 
            FROM information_schema.views 
            WHERE table_name = 'bio_dao_lp_support'
            '''
        }).execute()
        
        if result.data:
            print('📋 ОПРЕДЕЛЕНИЕ VIEW:')
            print(result.data[0]['view_definition'])
        else:
            print('❌ View определение не найдено через information_schema')
            
    except Exception as e:
        print(f'❌ Ошибка получения определения view: {e}')
    
    # Альтернативный способ - проверим логику через анализ данных
    print('\n🔍 АНАЛИЗ ЛОГИКИ VIEW ЧЕРЕЗ ДАННЫЕ:')
    
    # Получим все записи view с timestamp
    view_result = supabase_handler.client.table('bio_dao_lp_support').select(
        'token_symbol, network_display, pool_name, snapshot_timestamp, token_fdv_usd'
    ).execute()
    
    print(f'📊 View содержит {len(view_result.data)} записей')
    
    # Группируем по токенам и анализируем timestamp
    token_timestamps = {}
    for record in view_result.data:
        token = record['token_symbol']
        network = record['network_display']
        timestamp = record['snapshot_timestamp']
        fdv = record['token_fdv_usd']
        
        if token not in token_timestamps:
            token_timestamps[token] = {}
        
        token_timestamps[token][network] = {
            'timestamp': timestamp[:16],
            'fdv': fdv,
            'pool': record['pool_name']
        }
    
    print('\n📅 TIMESTAMP АНАЛИЗ В VIEW:')
    problem_tokens = []
    
    for token, networks in sorted(token_timestamps.items()):
        if len(networks) > 1:
            timestamps = [data['timestamp'] for data in networks.values()]
            unique_timestamps = set(timestamps)
            
            if len(unique_timestamps) > 1:
                problem_tokens.append(token)
                print(f'❌ {token}: разные timestamp!')
                for network, data in networks.items():
                    print(f'   {network}: {data["timestamp"]} - FDV ${data["fdv"]:,.0f} - {data["pool"]}')
            else:
                print(f'✅ {token}: единый timestamp {list(unique_timestamps)[0]}')
            print()
    
    # Проверим что должно быть в dao_pool_snapshots для сравнения
    print('\n📅 СРАВНЕНИЕ С DAO_POOL_SNAPSHOTS:')
    
    dao_result = supabase_handler.client.table('dao_pool_snapshots').select(
        'token_symbol, network, pool_name, created_at, token_fdv_usd, is_bio_pair'
    ).gte('created_at', '2025-07-30T15:20:00Z').eq('is_bio_pair', True).gt('token_fdv_usd', 0).execute()
    
    print(f'📊 DAO snapshots (BIO пары, FDV > 0, после 15:20): {len(dao_result.data)} записей')
    
    for record in dao_result.data:
        token = record['token_symbol']
        network = record['network']
        timestamp = record['created_at'][:16]
        fdv = record['token_fdv_usd']
        
        # Найдем соответствующую запись в view
        view_match = None
        for view_rec in view_result.data:
            if (view_rec['token_symbol'] == token and 
                view_rec['network_display'].lower() == network.title()):
                view_match = view_rec
                break
        
        if view_match:
            view_ts = view_match['snapshot_timestamp'][:16]
            view_fdv = view_match['token_fdv_usd']
            
            if view_ts != timestamp or view_fdv != fdv:
                print(f'❌ {token} ({network}):')
                print(f'   DAO: {timestamp} - FDV ${fdv:,.0f}')
                print(f'   View: {view_ts} - FDV ${view_fdv:,.0f}')
            else:
                print(f'✅ {token} ({network}): синхронизировано')
        else:
            print(f'❌ {token} ({network}): отсутствует в view!')

if __name__ == '__main__':
    check_view_definition() 