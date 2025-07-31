#!/usr/bin/env python3
from database_handler import SupabaseHandler

def check_view_current_state():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('=' * 60)
    print('📊 ТЕКУЩЕЕ СОСТОЯНИЕ VIEW bio_dao_lp_support')
    print('=' * 60)
    
    # Проверяем что сейчас в view
    result = supabase_handler.client.table('bio_dao_lp_support').select('*').order('our_position_value_usd', desc=True).execute()
    
    print(f'Записей в view: {len(result.data)}')
    
    if len(result.data) == 0:
        print('❌ VIEW ПУСТОЙ! Либо SQL не выполнен, либо логика неправильная')
        return
    
    print(f'\n💰 ВСЕ ЗАПИСИ В VIEW:')
    for i, record in enumerate(result.data, 1):
        pos_value = record['our_position_value_usd']
        fdv = record['token_fdv_usd']
        symbol = record['token_symbol']
        pool_name = record['pool_name']
        network = record['network_display']
        
        marker = '💰' if pos_value > 0 else '  '
        print(f'{marker} [{i:2d}] {pool_name} ({network}): ${pos_value:,.2f}')
        print(f'        {symbol} FDV: ${fdv:,.0f}')
    
    print(f'\n🔍 ПРОВЕРКА ПРОБЛЕМ:')
    
    # QBIO/SOL
    qbio_sol_view = [r for r in result.data if 'QBIO/SOL' in r['pool_name']]
    if qbio_sol_view:
        print(f'❌ QBIO/SOL ВСЕ ЕЩЕ во view: {len(qbio_sol_view)} записей')
    else:
        print('✅ QBIO/SOL исключен')
    
    # BIO/SPINE дублирование
    spine_view = [r for r in result.data if 'BIO/SPINE' in r['pool_name']]
    if len(spine_view) > 1:
        print(f'❌ BIO/SPINE ВСЕ ЕЩЕ дублируется: {len(spine_view)} записей')
    else:
        print(f'✅ BIO/SPINE без дублирования: {len(spine_view)} запись')
    
    # ATH FDV
    ath_view = [r for r in result.data if r['token_symbol'] == 'ATH']
    if ath_view:
        for record in ath_view:
            fdv = record['token_fdv_usd']
            if fdv > 10000000:
                print(f'✅ ATH FDV исправлен: ${fdv:,.0f}')
            else:
                print(f'❌ ATH FDV ВСЕ ЕЩЕ неправильный: ${fdv:,.0f}')
    else:
        print('❌ ATH не найден во view')
    
    # Крупные позиции
    large_positions = [r for r in result.data if r['our_position_value_usd'] > 100000]
    print(f'\n💰 КРУПНЫЕ ПОЗИЦИИ (>$100k): {len(large_positions)}')
    for record in large_positions:
        value = record['our_position_value_usd']
        pool_name = record['pool_name']
        network = record['network_display']
        print(f'    {pool_name} ({network}): ${value:,.2f}')
    
    # Позиции с $0
    zero_positions = [r for r in result.data if r['our_position_value_usd'] == 0]
    print(f'\n💸 ПОЗИЦИИ С $0: {len(zero_positions)}')
    
    print(f'\n📊 ИТОГО ПРОБЛЕМ:')
    problems = 0
    if qbio_sol_view:
        problems += 1
        print('❌ QBIO/SOL не исключен')
    if len(spine_view) > 1:
        problems += 1
        print('❌ BIO/SPINE дублируется')
    if ath_view and ath_view[0]['token_fdv_usd'] < 10000000:
        problems += 1
        print('❌ ATH FDV неправильный')
    if len(large_positions) < 3:
        problems += 1
        print('❌ Мало крупных позиций')
    
    if problems == 0:
        print('✅ ВСЕ ПРОБЛЕМЫ РЕШЕНЫ!')
    else:
        print(f'❌ ОСТАЛОСЬ ПРОБЛЕМ: {problems}')
        print('\n🤔 ВЫВОД: Я действительно дебил, если SQL не исправил проблемы')

if __name__ == '__main__':
    check_view_current_state() 