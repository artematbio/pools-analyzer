#!/usr/bin/env python3
from database_handler import SupabaseHandler
from datetime import datetime

def check_fdv_data():
    # Подключаемся к Supabase через handler
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('📊 Проверяем dao_pool_snapshots за сегодня...')

    # Проверяем последние записи по токенам за сегодня
    result = supabase_handler.client.table('dao_pool_snapshots').select(
        'token_symbol, network, token_fdv_usd, created_at'
    ).gte('created_at', '2025-07-30T00:00:00Z').order(
        'created_at', desc=True
    ).limit(50).execute()

    print(f'Найдено {len(result.data)} записей за сегодня\n')

    # Группируем по токенам и показываем FDV
    tokens = {}
    for record in result.data:
        token = record['token_symbol']
        network = record['network'] 
        fdv = record['token_fdv_usd']
        created = record['created_at'][:16]
        
        if token not in tokens:
            tokens[token] = {}
        
        if network not in tokens[token]:
            tokens[token][network] = {'fdv': fdv, 'time': created}

    # Показываем результаты
    print('🔍 FDV по токенам и сетям (последние записи):')
    for token, networks in sorted(tokens.items()):
        if len(networks) > 1:  # Показываем только токены на нескольких сетях
            print(f'{token}:')
            fdv_values = []
            for network, data in networks.items():
                fdv_val = data['fdv']
                fdv_values.append(fdv_val)
                print(f'  {network}: FDV ${fdv_val:,.0f} ({data["time"]})')
            
            # Проверяем одинаковые ли FDV
            if len(set(fdv_values)) > 1:
                print(f'  ❌ ПРОБЛЕМА: Разные FDV для {token}!')
            else:
                print(f'  ✅ OK: Единый FDV для {token}')
            print()

    # Дополнительно проверим конкретные проблемные токены
    print('\n🔍 Детальная проверка проблемных токенов:')
    problem_tokens = ['ATH', 'CRYO', 'GROW', 'NEURON']
    
    for token in problem_tokens:
        result = supabase_handler.client.table('dao_pool_snapshots').select(
            'token_symbol, network, token_fdv_usd, pool_name, created_at'
        ).eq('token_symbol', token).gte('created_at', '2025-07-30T00:00:00Z').order(
            'created_at', desc=True
        ).limit(10).execute()
        
        if result.data:
            print(f'\n{token} записи:')
            for record in result.data:
                fdv = record["token_fdv_usd"]
                print(f'  {record["network"]}: FDV ${fdv:,.0f} - {record["pool_name"]} ({record["created_at"][:16]})')

if __name__ == '__main__':
    check_fdv_data() 