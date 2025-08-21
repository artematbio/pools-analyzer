#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database_handler import SupabaseHandler
from datetime import datetime, timedelta
from collections import defaultdict

def analyze_duplicates():
    """Анализ и исправление дублирующихся позиций"""
    
    print("🔍 АНАЛИЗ ДУБЛИКАТОВ В lp_position_snapshots")
    print("===========================================")
    
    supabase_handler = SupabaseHandler()
    
    # Получаем все позиции за последние 3 дня
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
    
    print(f"\n📅 Получаем данные с {three_days_ago}...")
    
    result = supabase_handler.client.table('lp_position_snapshots').select(
        'id, position_mint, network, pool_id, pool_name, position_value_usd, created_at'
    ).gte('created_at', three_days_ago).order('created_at', desc=True).execute()
    
    print(f"📊 Найдено {len(result.data)} записей")
    
    # Группируем по уникальным позициям
    unique_positions = defaultdict(list)
    
    for record in result.data:
        position_mint = record.get('position_mint', '')
        network = record.get('network', '')
        value = float(record.get('position_value_usd', 0))
        created_at = record.get('created_at', '')
        
        # Ключ уникальной позиции
        unique_key = f"{position_mint}_{network}"
        
        unique_positions[unique_key].append({
            'id': record['id'],
            'pool_name': record.get('pool_name', 'N/A'),
            'value': value,
            'created_at': created_at
        })
    
    print(f"\n🎯 Уникальных позиций: {len(unique_positions)}")
    
    # Анализируем дубликаты
    duplicates_found = 0
    total_excess_value = 0
    positions_to_delete = []
    
    print("\n🔍 АНАЛИЗ ДУБЛИКАТОВ:")
    
    for unique_key, records in unique_positions.items():
        if len(records) > 1:
            duplicates_found += 1
            
            # Сортируем по дате создания (новые сначала)
            records.sort(key=lambda x: x['created_at'], reverse=True)
            
            newest = records[0]
            duplicates = records[1:]
            
            print(f"\n   🚨 {newest['pool_name']} ({unique_key})")
            print(f"      Всего записей: {len(records)}")
            print(f"      ✅ Оставляем: ${newest['value']:,.2f} ({newest['created_at']})")
            
            duplicate_value = 0
            for dup in duplicates:
                duplicate_value += dup['value']
                positions_to_delete.append(dup['id'])
                print(f"      ❌ Удаляем: ${dup['value']:,.2f} ({dup['created_at']})")
            
            total_excess_value += duplicate_value
    
    print(f"\n📊 СТАТИСТИКА ДУБЛИКАТОВ:")
    print(f"   • Позиций с дубликатами: {duplicates_found}")
    print(f"   • Записей для удаления: {len(positions_to_delete)}")
    print(f"   • Избыточная стоимость: ${total_excess_value:,.2f}")
    print(f"   • Ожидаемая стоимость после очистки: ${117870735.71 - total_excess_value:,.2f}")
    
    if len(positions_to_delete) > 0:
        print(f"\n❓ ВЫПОЛНИТЬ ОЧИСТКУ ДУБЛИКАТОВ?")
        print(f"   Это удалит {len(positions_to_delete)} дублирующихся записей")
        print(f"   и уменьшит портфель на ${total_excess_value:,.2f}")
        
        # Для безопасности - сначала показываем план, не удаляем автоматически
        print(f"\n⚠️ ДЛЯ БЕЗОПАСНОСТИ: ПЛАН ГОТОВ, НО НЕ ВЫПОЛНЕН")
        print(f"   Если хотите выполнить - раскомментируйте код удаления")
        
        # ЗАКОММЕНТИРОВАННЫЙ код удаления для безопасности
        """
        try:
            print("\\n🗑️ Удаляем дубликаты...")
            for record_id in positions_to_delete:
                supabase_handler.client.table('lp_position_snapshots').delete().eq('id', record_id).execute()
            
            print(f"✅ Удалено {len(positions_to_delete)} дублирующихся записей")
        except Exception as e:
            print(f"❌ Ошибка удаления: {e}")
        """
    
    # Проверяем актуальное состояние после анализа
    print(f"\n🔧 РЕКОМЕНДАЦИИ:")
    if duplicates_found > 0:
        print(f"   1. Дубликаты найдены - нужна очистка")
        print(f"   2. Проверить логику записи позиций")
        print(f"   3. Добавить уникальные ограничения")
    else:
        print(f"   ✅ Дубликатов не найдено")
    
    return positions_to_delete, total_excess_value

def create_cleanup_script(positions_to_delete):
    """Создает SQL скрипт для ручной очистки"""
    
    if not positions_to_delete:
        return
    
    script_content = "-- СКРИПТ ОЧИСТКИ ДУБЛИКАТОВ lp_position_snapshots\n"
    script_content += f"-- Удаляет {len(positions_to_delete)} дублирующихся записей\n"
    script_content += f"-- Создан: {datetime.now().isoformat()}\n\n"
    
    # Группируем ID по батчам для удобства
    batch_size = 50
    for i in range(0, len(positions_to_delete), batch_size):
        batch = positions_to_delete[i:i+batch_size]
        ids_str = "', '".join(batch)
        script_content += f"-- Batch {i//batch_size + 1}\n"
        script_content += f"DELETE FROM lp_position_snapshots WHERE id IN ('{ids_str}');\n\n"
    
    with open('cleanup_duplicates.sql', 'w') as f:
        f.write(script_content)
    
    print(f"💾 SQL скрипт сохранен: cleanup_duplicates.sql")

if __name__ == "__main__":
    positions_to_delete, total_excess = analyze_duplicates()
    if positions_to_delete:
        create_cleanup_script(positions_to_delete)
