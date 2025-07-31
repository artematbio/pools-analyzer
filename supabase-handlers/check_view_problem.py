#!/usr/bin/env python3
from database_handler import SupabaseHandler

def check_view_problem():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 Проверяем view bio_dao_lp_support...')
    
    # Проверяем что показывает view
    result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
    
    print(f'Найдено {len(result.data)} записей в view')
    
    # Группируем по токенам для проверки FDV
    tokens = {}
    for record in result.data:
        token = record['token_symbol']
        network = record['network_display'] 
        fdv = record['token_fdv_usd']
        timestamp = record['snapshot_timestamp'][:16]
        
        if token not in tokens:
            tokens[token] = {}
        
        tokens[token][network] = {'fdv': fdv, 'timestamp': timestamp}
    
    print('\n🔍 FDV в view bio_dao_lp_support:')
    problem_found = False
    
    for token, networks in sorted(tokens.items()):
        if len(networks) > 1:  # Токены на нескольких сетях
            print(f'{token}:')
            fdv_values = []
            for network, data in networks.items():
                fdv_val = data['fdv']
                fdv_values.append(fdv_val)
                print(f'  {network}: FDV ${fdv_val:,.0f} ({data["timestamp"]})')
            
            # Проверяем одинаковые ли FDV
            if len(set(fdv_values)) > 1:
                print(f'  ❌ ПРОБЛЕМА: Разные FDV для {token}!')
                problem_found = True
            else:
                print(f'  ✅ OK: Единый FDV для {token}')
            print()
    
    # Проверяем позиции
    print('\n💰 ПОЗИЦИИ В VIEW:')
    positions_found = []
    for record in result.data:
        our_pos = record['our_position_value_usd']
        if our_pos > 0:
            positions_found.append({
                'pool': record['pool_name'],
                'network': record['network_display'],
                'value': our_pos,
                'timestamp': record['snapshot_timestamp'][:16],
                'fdv': record['token_fdv_usd']
            })
    
    if positions_found:
        positions_found.sort(key=lambda x: x['value'], reverse=True)
        
        for pos in positions_found:
            print(f'  💰 {pos["pool"]} ({pos["network"]}): ${pos["value"]:,.2f} - FDV: ${pos["fdv"]:,.0f} - {pos["timestamp"]}')
    else:
        print('  ❌ Нет позиций с value > 0!')
    
    print(f'\n📊 ИТОГО: {len(positions_found)} позиций в view')
    
    if problem_found:
        print('\n❌ НАЙДЕНЫ ПРОБЛЕМЫ С FDV!')
    else:
        print('\n✅ FDV данные выглядят корректно')

if __name__ == '__main__':
    check_view_problem() 