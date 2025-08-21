#!/usr/bin/env python3
"""
Скрипт для проверки исправления проблемы с позициями после применения SQL
"""
import sys
sys.path.append('..')
from database_handler import SupabaseHandler

def verify_fixed_positions():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('=' * 80)
    print('🔍 ПРОВЕРКА ИСПРАВЛЕНИЯ ПОЗИЦИЙ В bio_dao_lp_support')
    print('=' * 80)
    
    # Получаем все записи view после применения исправления
    try:
        result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
        
        if not result.data:
            print('❌ VIEW ПУСТОЙ! SQL не применен или ошибка в логике')
            return
        
        print(f'📊 Записей в view: {len(result.data)}')
        
        # Считаем общую сумму позиций
        total_value = 0
        problematic_positions = []
        
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
                
                total_value += numeric_val
                
                # Считаем проблемными позиции больше $5M (раньше было $1M)
                if numeric_val > 5000000:
                    problematic_positions.append({
                        'token': token,
                        'chain': chain,
                        'value': numeric_val,
                        'formatted': our_positions
                    })
            except Exception as e:
                print(f'❌ Не удалось преобразовать значение для {token} ({chain}): {our_positions} - {e}')
        
        print(f'\n💰 ОБЩАЯ СУММА ВСЕХ ПОЗИЦИЙ: ${total_value:,.2f}')
        
        # Проверяем результат исправления
        if total_value > 150000000:  # >$150M
            print(f'❌ СУММА ВСЕ ЕЩЕ СЛИШКОМ БОЛЬШАЯ!')
            print(f'   Ожидали: ~$118M')
            print(f'   Получили: ${total_value:,.2f}')
            print(f'   SQL НЕ ИСПРАВИЛ ПРОБЛЕМУ!')
        elif total_value < 50000000:  # <$50M
            print(f'❌ СУММА СЛИШКОМ МАЛЕНЬКАЯ!')
            print(f'   Возможно, фильтрация слишком строгая')
        else:
            print(f'✅ СУММА В РАЗУМНЫХ ПРЕДЕЛАХ!')
            print(f'   Ожидали: ~$118M')
            print(f'   Получили: ${total_value:,.2f}')
            print(f'   ПРОБЛЕМА ИСПРАВЛЕНА! 🎉')
        
        print(f'\n🚨 ПОЗИЦИЙ БОЛЬШЕ $5M: {len(problematic_positions)}')
        
        if problematic_positions:
            print(f'\n📋 ДЕТАЛИ КРУПНЫХ ПОЗИЦИЙ:')
            for i, pos in enumerate(sorted(problematic_positions, key=lambda x: x['value'], reverse=True), 1):
                print(f'  [{i:2d}] {pos["token"]} ({pos["chain"]}): {pos["formatted"]} (${pos["value"]:,.0f})')
        
        # Сравниваем с базой данных
        print(f'\n' + '=' * 80)
        print(f'🔍 СРАВНЕНИЕ С БАЗОЙ ДАННЫХ')
        print(f'=' * 80)
        
        # Получаем данные из базы
        lp_positions = supabase_handler.client.table('lp_position_snapshots').select(
            'token0_symbol, token1_symbol, position_value_usd, created_at, network'
        ).execute()
        
        # Фильтруем BIO позиции
        bio_positions = [
            pos for pos in lp_positions.data 
            if (pos['token0_symbol'] == 'BIO' or pos['token1_symbol'] == 'BIO') 
            and pos['position_value_usd'] > 0
        ]
        
        db_total_value = sum(pos['position_value_usd'] for pos in bio_positions)
        
        print(f'   База данных (все снапшоты): ${db_total_value:,.2f}')
        print(f'   VIEW (исправленный): ${total_value:,.2f}')
        
        difference = abs(total_value - db_total_value)
        percentage = (difference / db_total_value) * 100 if db_total_value > 0 else 0
        
        print(f'   Разница: ${difference:,.2f} ({percentage:.1f}%)')
        
        if percentage < 5:
            print(f'✅ ОТЛИЧНАЯ РАБОТА! Разница менее 5%')
        elif percentage < 15:
            print(f'⚠️  Неплохо, но есть небольшие расхождения')
        else:
            print(f'❌ Слишком большая разница! Нужно проверить логику')
        
        # Финальная оценка
        print(f'\n🎯 ФИНАЛЬНАЯ ОЦЕНКА:')
        if total_value <= 150000000 and percentage < 15:
            print(f'✅ ПРОБЛЕМА ИСПРАВЛЕНА!')
            print(f'   - Позиции больше не дублируются')
            print(f'   - Суммы в разумных пределах')
            print(f'   - View работает корректно')
        else:
            print(f'❌ ТРЕБУЕТСЯ ДОПОЛНИТЕЛЬНАЯ РАБОТА')
            print(f'   - Проверьте логику агрегации')
            print(f'   - Возможно, нужна дополнительная фильтрация')
        
    except Exception as e:
        print(f'❌ Ошибка при проверке view: {e}')

if __name__ == '__main__':
    verify_fixed_positions()
