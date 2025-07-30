#!/usr/bin/env python3
from database_handler import SupabaseHandler

def check_view_logic():
    # Подключаемся к Supabase через handler
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    
    # Попробуем найти view bio dao lp support
    print('🔍 Ищем view "bio dao lp support"...')
    
    # Сначала проверим все доступные views
    try:
        result = supabase_handler.client.rpc('get_views').execute()
        print(f"Доступные views: {result.data}")
    except:
        print("Не удалось получить список views")
    
    # Проверим есть ли таблица или view с похожим названием
    tables_to_check = [
        'bio_dao_lp_support',
        'dao_lp_support', 
        'dao_pools_dashboard',
        'bio_pair_support'
    ]
    
    for table_name in tables_to_check:
        try:
            print(f'\n🔍 Проверяем {table_name}...')
            result = supabase_handler.client.table(table_name).select('*').limit(3).execute()
            print(f'✅ Найдена таблица/view {table_name} с {len(result.data)} записями')
            if result.data:
                print(f'Колонки: {list(result.data[0].keys())}')
        except Exception as e:
            print(f'❌ {table_name} не найден: {e}')
    
    # Прямой SQL запрос для имитации view logic
    print('\n🔍 Проверяем логику группировки как в view...')
    
    # Эмулируем проблемную логику view
    query = """
    SELECT 
        token_symbol,
        network,
        token_fdv_usd,
        pool_name,
        created_at,
        ROW_NUMBER() OVER (
            PARTITION BY token_symbol, network, pool_address 
            ORDER BY created_at DESC
        ) as rn
    FROM dao_pool_snapshots 
    WHERE 
        token_fdv_usd > 0 
        AND token_symbol IN ('ATH', 'CRYO', 'GROW', 'NEURON')
        AND created_at >= '2025-07-30T00:00:00Z'
    """
    
    try:
        result = supabase_handler.client.rpc('exec_sql', {'query': query}).execute()
        print(f"SQL результат: {result.data}")
    except Exception as e:
        print(f"Ошибка SQL: {e}")
        
        # Альтернативный подход - ручной запрос
        print('\n🔍 Альтернативная проверка...')
        for token in ['ATH', 'CRYO', 'GROW', 'NEURON']:
            result = supabase_handler.client.table('dao_pool_snapshots').select(
                'token_symbol, network, token_fdv_usd, pool_name, created_at'
            ).eq('token_symbol', token).gt('token_fdv_usd', 0).gte(
                'created_at', '2025-07-30T00:00:00Z'
            ).order('created_at', desc=True).execute()
            
            print(f'\n{token} - все записи за сегодня:')
            for record in result.data[:5]:  # Показываем первые 5
                print(f'  {record["network"]}: FDV ${record["token_fdv_usd"]:,.0f} - {record["created_at"][:16]}')

if __name__ == '__main__':
    check_view_logic() 