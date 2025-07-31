#!/usr/bin/env python3
from database_handler import SupabaseHandler

def check_fresh_data():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 ПРОВЕРКА СВЕЖИХ ДАННЫХ ПОСЛЕ ОБНОВЛЕНИЯ...\n')
    
    # Проверяем самые свежие данные
    dao_result = supabase_handler.client.table('dao_pool_snapshots').select(
        'pool_name, network, our_position_value_usd, token_symbol, is_bio_pair, snapshot_timestamp, created_at'
    ).gte('created_at', '2025-07-30T15:40:00Z').order('created_at', desc=True).execute()
    
    print(f'📊 СВЕЖИЕ ДАННЫЕ (после 15:40): {len(dao_result.data)} записей\n')
    
    # Ищем позиции
    positions = []
    for record in dao_result.data:
        if (record['our_position_value_usd'] > 0 and 
            record.get('is_bio_pair', False) and 
            'BIO' in record['pool_name']):
            positions.append(record)
    
    print(f'💰 СВЕЖИЕ BIO ПОЗИЦИИ (> 0): {len(positions)}')
    positions.sort(key=lambda x: x['our_position_value_usd'], reverse=True)
    
    for record in positions:
        timestamp = record['snapshot_timestamp'][:16]
        print(f'  💰 {record["pool_name"]} ({record["network"]}): ${record["our_position_value_usd"]:,.2f} - {timestamp}')
    
    # Проверяем конкретно BIO/MYCO и BIO/SPINE
    print(f'\n🔍 ПРОВЕРКА BIO/MYCO И BIO/SPINE В СВЕЖИХ ДАННЫХ:')
    
    target_pools = ['BIO/MYCO', 'BIO/SPINE']
    
    for pool_name in target_pools:
        print(f'\n{pool_name}:')
        
        found = []
        for record in dao_result.data:
            if pool_name in record['pool_name']:
                found.append(record)
        
        if found:
            for record in found:
                pos_marker = "💰" if record['our_position_value_usd'] > 0 else "  "
                print(f'  {pos_marker} {record["pool_name"]} ({record["network"]}): ${record["our_position_value_usd"]:,.2f}')
                print(f'     BIO pair: {record.get("is_bio_pair", False)}, timestamp: {record["snapshot_timestamp"][:16]}')
        else:
            print(f'  ❌ Не найдено в свежих данных')
    
    # Проверяем дублирование BIO/SPINE
    spine_records = [r for r in dao_result.data if 'BIO/SPINE' in r['pool_name']]
    if len(spine_records) > 1:
        print(f'\n⚠️ ДУБЛИРОВАНИЕ BIO/SPINE: найдено {len(spine_records)} записей')
        for record in spine_records:
            print(f'  {record["pool_name"]} ({record["network"]}) - {record["snapshot_timestamp"][:16]}')
    
    # Проверяем все BIO пары
    print(f'\n📊 ВСЕ BIO ПАРЫ В СВЕЖИХ ДАННЫХ:')
    
    bio_pairs = []
    for record in dao_result.data:
        if record.get('is_bio_pair', False) and 'BIO' in record['pool_name']:
            bio_pairs.append(record)
    
    print(f'Найдено {len(bio_pairs)} BIO пар')
    
    # Группируем по названию пула
    pool_groups = {}
    for record in bio_pairs:
        pool_name = record['pool_name']
        if pool_name not in pool_groups:
            pool_groups[pool_name] = []
        pool_groups[pool_name].append(record)
    
    for pool_name, records in sorted(pool_groups.items()):
        has_position = any(r['our_position_value_usd'] > 0 for r in records)
        position_marker = "💰" if has_position else "  "
        
        max_position = max(r['our_position_value_usd'] for r in records)
        
        print(f'{position_marker} {pool_name}: ${max_position:,.2f}')
        if len(records) > 1:
            print(f'    ⚠️ {len(records)} записей (дублирование)')

if __name__ == '__main__':
    check_fresh_data() 