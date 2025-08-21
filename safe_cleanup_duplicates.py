#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database_handler import SupabaseHandler
from datetime import datetime, timedelta
from collections import defaultdict
import json

def create_safe_cleanup():
    """Создает безопасный план очистки дубликатов"""
    
    print("🔧 СОЗДАНИЕ БЕЗОПАСНОГО ПЛАНА ОЧИСТКИ")
    print("====================================")
    
    supabase_handler = SupabaseHandler()
    
    # Получаем все позиции за последние 7 дней (чтобы поймать все дубликаты)
    week_ago = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    
    print(f"📅 Анализируем записи с {week_ago}...")
    
    result = supabase_handler.client.table('lp_position_snapshots').select(
        'id, position_mint, network, pool_id, pool_name, position_value_usd, created_at'
    ).gte('created_at', week_ago).order('created_at', desc=True).execute()
    
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
    
    # Создаем план очистки
    cleanup_plan = {
        'total_positions': len(unique_positions),
        'duplicates_found': 0,
        'records_to_delete': [],
        'records_to_keep': [],
        'total_excess_value': 0,
        'created_at': datetime.now().isoformat()
    }
    
    print(f"\n🔍 АНАЛИЗ {len(unique_positions)} УНИКАЛЬНЫХ ПОЗИЦИЙ:")
    
    for unique_key, records in unique_positions.items():
        if len(records) > 1:
            cleanup_plan['duplicates_found'] += 1
            
            # Сортируем по дате создания (новые сначала)
            records.sort(key=lambda x: x['created_at'], reverse=True)
            
            # Оставляем самую свежую запись
            newest = records[0]
            duplicates = records[1:]
            
            cleanup_plan['records_to_keep'].append({
                'id': newest['id'],
                'pool_name': newest['pool_name'],
                'value': newest['value'],
                'created_at': newest['created_at'],
                'unique_key': unique_key
            })
            
            # Остальные помечаем на удаление
            for dup in duplicates:
                cleanup_plan['records_to_delete'].append({
                    'id': dup['id'],
                    'pool_name': dup['pool_name'],
                    'value': dup['value'],
                    'created_at': dup['created_at'],
                    'unique_key': unique_key
                })
                cleanup_plan['total_excess_value'] += dup['value']
            
            print(f"   🔍 {newest['pool_name']} ({unique_key})")
            print(f"      ✅ Оставляем: ${newest['value']:,.2f} ({newest['created_at']})")
            print(f"      ❌ Удаляем: {len(duplicates)} записей на ${sum(d['value'] for d in duplicates):,.2f}")
    
    # Сохраняем план в JSON
    with open('cleanup_plan.json', 'w') as f:
        json.dump(cleanup_plan, f, indent=2, ensure_ascii=False)
    
    print(f"\n📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(f"   • Позиций с дубликатами: {cleanup_plan['duplicates_found']}")
    print(f"   • Записей к удалению: {len(cleanup_plan['records_to_delete'])}")
    print(f"   • Записей к сохранению: {len(cleanup_plan['records_to_keep'])}")
    print(f"   • Избыточная стоимость: ${cleanup_plan['total_excess_value']:,.2f}")
    
    # Создаем SQL скрипт для очистки
    create_sql_cleanup_script(cleanup_plan['records_to_delete'])
    
    print(f"\n💾 ФАЙЛЫ СОЗДАНЫ:")
    print(f"   • cleanup_plan.json - полный план очистки")
    print(f"   • cleanup_duplicates_safe.sql - SQL скрипт")
    
    return cleanup_plan

def create_sql_cleanup_script(records_to_delete):
    """Создает SQL скрипт для безопасной очистки"""
    
    if not records_to_delete:
        return
    
    script_content = """-- БЕЗОПАСНАЯ ОЧИСТКА ДУБЛИКАТОВ lp_position_snapshots
-- =====================================================
-- ВАЖНО: Перед выполнением сделайте бэкап таблицы!
-- 
-- CREATE TABLE lp_position_snapshots_backup AS 
-- SELECT * FROM lp_position_snapshots;
-- 
"""
    script_content += f"-- Удаляет {len(records_to_delete)} дублирующихся записей\n"
    script_content += f"-- Создан: {datetime.now().isoformat()}\n\n"
    
    script_content += "BEGIN;\n\n"
    
    # Группируем по пулам для наглядности
    pools = defaultdict(list)
    for record in records_to_delete:
        pool_name = record['pool_name']
        pools[pool_name].append(record)
    
    for pool_name, pool_records in pools.items():
        script_content += f"-- {pool_name} ({len(pool_records)} дубликатов)\n"
        
        # Группируем ID в батчи по 20 для безопасности
        ids = [record['id'] for record in pool_records]
        batch_size = 20
        
        for i in range(0, len(ids), batch_size):
            batch = ids[i:i+batch_size]
            ids_str = "', '".join(str(id) for id in batch)
            script_content += f"DELETE FROM lp_position_snapshots WHERE id IN ('{ids_str}');\n"
        
        script_content += "\n"
    
    script_content += """
-- Проверка результата
SELECT 
    COUNT(*) as total_records,
    COUNT(DISTINCT CONCAT(position_mint, '_', network)) as unique_positions
FROM lp_position_snapshots 
WHERE created_at >= NOW() - INTERVAL '7 days';

COMMIT;

-- ROLLBACK; -- Раскомментируйте эту строку вместо COMMIT для отката
"""
    
    with open('cleanup_duplicates_safe.sql', 'w') as f:
        f.write(script_content)

if __name__ == "__main__":
    plan = create_safe_cleanup()
    
    print(f"\n🎯 СЛЕДУЮЩИЕ ШАГИ:")
    print(f"   1. Проверьте cleanup_plan.json")
    print(f"   2. Сделайте бэкап таблицы в Supabase")
    print(f"   3. Выполните cleanup_duplicates_safe.sql")
    print(f"   4. Проверьте результат")
    print(f"   5. Исправьте логику записи позиций")
