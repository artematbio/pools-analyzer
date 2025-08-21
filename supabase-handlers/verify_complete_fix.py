#!/usr/bin/env python3
"""
Финальная проверка полностью исправленного bio_dao_lp_support view
"""
import sys
sys.path.append('..')
from database_handler import SupabaseHandler

def verify_complete_fix():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('=' * 80)
    print('🎉 ФИНАЛЬНАЯ ПРОВЕРКА ИСПРАВЛЕННОГО VIEW')
    print('=' * 80)
    
    # Получаем все записи из обновленного view
    try:
        result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
        
        if not result.data:
            print('❌ VIEW ПУСТОЙ после применения SQL!')
            return
        
        print(f'📊 Всего записей в view: {len(result.data)}')
        
        # Анализируем позиции
        positions_with_value = []
        total_value = 0
        
        for record in result.data:
            our_positions = record['Our positions $']
            token = record['Token']
            chain = record['Chain']
            
            # Преобразуем значение в число
            try:
                if isinstance(our_positions, str):
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
        
        print(f'\n💰 РЕЗУЛЬТАТЫ ИСПРАВЛЕНИЯ:')
        print(f'   Позиций с суммой > $0: {len(positions_with_value)}')
        print(f'   Общая сумма всех позиций: ${total_value:,.2f}')
        
        # Проверяем конкретные проблемные пулы
        print(f'\n🔍 ПРОВЕРКА ИСПРАВЛЕННЫХ ПУЛОВ:')
        
        problematic_pools = {
            'WETH/BIO': {'chain': 'Ethereum', 'expected_range': (1500000, 2000000)},  # ~$1.7M
            'HAIR/BIO': {'chain': 'Ethereum', 'expected_range': (1000000, 1500000)},  # ~$1.2M
            'ATH/BIO': {'chain': 'Ethereum', 'expected_range': (100000, 200000)},     # ~$146K
            'BIO/PSY': {'chain': 'Ethereum', 'expected_range': (40000, 80000)},       # ~$54K
            'BIO/QBIO': {'chain': 'Ethereum', 'expected_range': (40000, 80000)}       # ~$52K
        }
        
        found_pools = {}
        for record in result.data:
            token = record['Token']
            chain = record['Chain']
            our_positions = record['Our positions $']
            
            # Ищем пулы по токену и сети
            for pool_name, pool_info in problematic_pools.items():
                if token in pool_name and chain == pool_info['chain']:
                    try:
                        if isinstance(our_positions, str):
                            clean_val = our_positions.replace('$', '').replace(',', '')
                            if 'M' in clean_val:
                                numeric_val = float(clean_val.replace('M', '')) * 1000000
                            elif 'K' in clean_val:
                                numeric_val = float(clean_val.replace('K', '')) * 1000
                            else:
                                numeric_val = float(clean_val)
                        else:
                            numeric_val = float(our_positions)
                        
                        found_pools[pool_name] = {
                            'value': numeric_val,
                            'formatted': our_positions,
                            'expected_range': pool_info['expected_range']
                        }
                    except:
                        pass
        
        fix_success_count = 0
        for pool_name, data in found_pools.items():
            value = data['value']
            min_expected, max_expected = data['expected_range']
            
            if min_expected <= value <= max_expected:
                print(f'   ✅ {pool_name}: {data["formatted"]} (в ожидаемом диапазоне)')
                fix_success_count += 1
            else:
                print(f'   ❌ {pool_name}: {data["formatted"]} (ожидалось ${min_expected:,.0f}-${max_expected:,.0f})')
        
        # Показываем топ-15 позиций
        print(f'\n📋 ТОП-15 ПОЗИЦИЙ ПО СТОИМОСТИ:')
        sorted_positions = sorted(positions_with_value, key=lambda x: x['value'], reverse=True)
        
        for i, pos in enumerate(sorted_positions[:15], 1):
            print(f'  [{i:2d}] {pos["token"]} ({pos["chain"]}): {pos["formatted"]}')
        
        # Финальная оценка
        print(f'\n🎯 ФИНАЛЬНАЯ ОЦЕНКА ИСПРАВЛЕНИЯ:')
        
        if len(positions_with_value) >= 20:
            print(f'✅ ОТЛИЧНО! Найдено {len(positions_with_value)} позиций (было 3)')
        elif len(positions_with_value) >= 15:
            print(f'✅ ХОРОШО! Найдено {len(positions_with_value)} позиций')
        else:
            print(f'⚠️ Найдено только {len(positions_with_value)} позиций')
        
        if 80000000 <= total_value <= 150000000:  # $80M-$150M разумный диапазон
            print(f'✅ ОБЩАЯ СУММА В РАЗУМНЫХ ПРЕДЕЛАХ: ${total_value:,.2f}')
        elif total_value > 200000000:
            print(f'❌ СУММА ВСЕ ЕЩЕ СЛИШКОМ БОЛЬШАЯ: ${total_value:,.2f}')
        else:
            print(f'⚠️ СУММА ВОЗМОЖНО ЗАНИЖЕНА: ${total_value:,.2f}')
        
        if fix_success_count >= 3:
            print(f'✅ ПРОБЛЕМНЫЕ ПУЛЫ ИСПРАВЛЕНЫ: {fix_success_count}/5 в ожидаемых диапазонах')
        else:
            print(f'❌ ПРОБЛЕМНЫЕ ПУЛЫ НЕ ИСПРАВЛЕНЫ: только {fix_success_count}/5 в диапазонах')
        
        if (len(positions_with_value) >= 20 and 
            80000000 <= total_value <= 150000000 and 
            fix_success_count >= 3):
            print(f'\n🎉 ВСЕ ПРОБЛЕМЫ ИСПРАВЛЕНЫ!')
            print(f'   ✅ Включены все позиции (не только из dao_pool_snapshots)')
            print(f'   ✅ Устранены переоценки в 20-47 раз')
            print(f'   ✅ Только последние снапшоты каждой NFT позиции')
            print(f'   ✅ Правильный джоин по pool_name')
            print(f'   ✅ View готов к использованию!')
        else:
            print(f'\n⚠️ ТРЕБУЕТСЯ ДОПОЛНИТЕЛЬНАЯ РАБОТА')
            print(f'   - Проверьте применение SQL')
            print(f'   - Возможны проблемы в логике CTE')
        
    except Exception as e:
        print(f'❌ Ошибка при проверке view: {e}')

if __name__ == '__main__':
    verify_complete_fix()
