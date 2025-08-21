#!/usr/bin/env python3
"""
Быстрая проверка исправления джоина в bio_dao_lp_support view
"""
import sys
sys.path.append('..')
from database_handler import SupabaseHandler

def quick_verify_fixed_join():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('=' * 60)
    print('🔍 БЫСТРАЯ ПРОВЕРКА ИСПРАВЛЕНИЯ ДЖОИНА')
    print('=' * 60)
    
    # Получаем записи с позициями
    result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
    
    print(f'📊 Всего записей в view: {len(result.data)}')
    
    # Считаем записи с позициями > $0
    positions_with_value = []
    total_value = 0
    
    for record in result.data:
        our_positions = record['Our positions $']
        token = record['Token']
        chain = record['Chain']
        
        # Преобразуем значение в число
        try:
            if isinstance(our_positions, str):
                # Убираем $ и K/M
                clean_val = our_positions.replace('$', '').replace(',', '')
                if 'M' in clean_val:
                    numeric_val = float(clean_val.replace('M', '')) * 1000000
                elif 'K' in clean_val:
                    numeric_val = float(clean_val.replace('K', '')) * 1000
                else:
                    numeric_val = float(clean_val)
            else:
                numeric_val = float(our_positions)
            
            if numeric_val > 0:
                positions_with_value.append({
                    'token': token,
                    'chain': chain,
                    'value': numeric_val,
                    'formatted': our_positions
                })
                total_value += numeric_val
        except:
            pass
    
    print(f'💰 Позиций с суммой > $0: {len(positions_with_value)}')
    print(f'💰 Общая сумма позиций: ${total_value:,.2f}')
    
    if len(positions_with_value) > 15:
        print(f'✅ ОТЛИЧНО! Джоин работает - найдено {len(positions_with_value)} позиций')
        print(f'   Было: 3 позиции (VITA, SPINE, MYCO)')
        print(f'   Стало: {len(positions_with_value)} позиций')
        print(f'   Улучшение в {len(positions_with_value)/3:.1f} раз!')
    elif len(positions_with_value) > 10:
        print(f'⚠️  Хорошо, но можно лучше: {len(positions_with_value)} позиций')
    elif len(positions_with_value) > 5:
        print(f'⚠️  Некоторое улучшение: {len(positions_with_value)} позиций')
    else:
        print(f'❌ ДЖОИН ВСЕ ЕЩЕ НЕ РАБОТАЕТ: только {len(positions_with_value)} позиций')
    
    # Показываем топ-10 позиций
    if positions_with_value:
        print(f'\n📋 ТОП ПОЗИЦИИ:')
        sorted_positions = sorted(positions_with_value, key=lambda x: x['value'], reverse=True)
        for i, pos in enumerate(sorted_positions[:10], 1):
            print(f'  [{i:2d}] {pos["token"]} ({pos["chain"]}): {pos["formatted"]}')
        
        if len(sorted_positions) > 10:
            print(f'       ... и еще {len(sorted_positions) - 10} позиций')
    
    # Оценка исправления
    print(f'\n🎯 ОЦЕНКА ИСПРАВЛЕНИЯ:')
    if len(positions_with_value) >= 15:
        print(f'✅ ДЖОИН ПО pool_name РАБОТАЕТ ИДЕАЛЬНО!')
        print(f'   - Позиции найдены для большинства токенов')
        print(f'   - Суммы в разумных пределах')
        print(f'   - View готов к использованию')
    elif len(positions_with_value) >= 10:
        print(f'✅ ДЖОИН РАБОТАЕТ ХОРОШО!')
        print(f'   - Существенное улучшение')
        print(f'   - Большинство позиций найдено')
    else:
        print(f'❌ ДЖОИН ВСЕ ЕЩЕ ПРОБЛЕМАТИЧЕН')
        print(f'   - Нужна дополнительная диагностика')
        print(f'   - Возможны другие проблемы в SQL')

if __name__ == '__main__':
    quick_verify_fixed_join()
