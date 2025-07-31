#!/usr/bin/env python3
from database_handler import SupabaseHandler
from datetime import datetime, timedelta

def check_position_data_freshness():
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('🔍 ПРОВЕРКА АКТУАЛЬНОСТИ ДАННЫХ В lp_position_snapshots...\n')
    
    # Проверяем последние данные позиций
    positions_result = supabase_handler.client.table('lp_position_snapshots').select(
        'token0_symbol, token1_symbol, pool_name, network, position_value_usd, created_at'
    ).order('created_at', desc=True).limit(50).execute()
    
    print(f'📊 ПОСЛЕДНИЕ ЗАПИСИ В lp_position_snapshots: {len(positions_result.data)}')
    
    # Группируем по дате создания
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    
    today_positions = []
    yesterday_positions = []
    older_positions = []
    
    for record in positions_result.data:
        created_date = datetime.fromisoformat(record['created_at'].replace('Z', '+00:00')).date()
        
        if created_date == today:
            today_positions.append(record)
        elif created_date == yesterday:
            yesterday_positions.append(record)
        else:
            older_positions.append(record)
    
    print(f'📅 Сегодня ({today}): {len(today_positions)} записей')
    print(f'📅 Вчера ({yesterday}): {len(yesterday_positions)} записей') 
    print(f'📅 Раньше: {len(older_positions)} записей\n')
    
    # Проверяем конкретные проблемные пары
    target_pairs = ['VITA/BIO', 'BIO/MYCO', 'BIO/SPINE']
    
    print('🔍 ПРОВЕРКА ПРОБЛЕМНЫХ ПУЛОВ В lp_position_snapshots:')
    
    for pair_name in target_pairs:
        print(f'\n💰 {pair_name}:')
        
        found_positions = []
        for record in positions_result.data:
            pool_name_record = record.get('pool_name', '')
            token0 = record.get('token0_symbol', '')
            token1 = record.get('token1_symbol', '')
            
            # Проверяем различные варианты пар
            if (pair_name in pool_name_record or 
                (pair_name == 'VITA/BIO' and (('VITA' in token0 and 'BIO' in token1) or ('BIO' in token0 and 'VITA' in token1))) or
                (pair_name == 'BIO/MYCO' and (('BIO' in token0 and 'MYCO' in token1) or ('MYCO' in token0 and 'BIO' in token1))) or
                (pair_name == 'BIO/SPINE' and (('BIO' in token0 and 'SPINE' in token1) or ('SPINE' in token0 and 'BIO' in token1)))):
                found_positions.append(record)
        
        if found_positions:
            # Сортируем по дате создания
            found_positions.sort(key=lambda x: x['created_at'], reverse=True)
            
            print(f'  Найдено {len(found_positions)} записей:')
            for i, record in enumerate(found_positions[:3]):  # Показываем только последние 3
                created_time = record['created_at'][:16]
                timestamp_time = record.get('timestamp', 'N/A')[:16] if record.get('timestamp') else 'N/A'
                
                print(f'  [{i+1}] {record["pool_name"]} ({record["network"]})')
                print(f'      💰 Позиция: ${record["position_value_usd"]:,.2f}')
                print(f'      📅 Создано: {created_time}')
                print(f'      🕐 Timestamp: {timestamp_time}')
                print(f'      🏷️ Токены: {record.get("token0_symbol", "UNK")}/{record.get("token1_symbol", "UNK")}')
        else:
            print(f'  ❌ Не найдено в lp_position_snapshots')
    
    # Проверяем все позиции с value > 0
    print(f'\n💰 ВСЕ АКТИВНЫЕ ПОЗИЦИИ (value > 0):')
    
    active_positions = [r for r in positions_result.data if r['position_value_usd'] > 0]
    active_positions.sort(key=lambda x: x['position_value_usd'], reverse=True)
    
    print(f'Найдено {len(active_positions)} активных позиций:')
    
    for record in active_positions[:10]:  # Показываем топ 10
        created_time = record['created_at'][:16]
        print(f'  💰 {record["pool_name"]} ({record["network"]}): ${record["position_value_usd"]:,.2f} - {created_time}')
    
    # Проверяем когда последний раз обновлялись позиции по сетям
    print(f'\n📅 ПОСЛЕДНИЕ ОБНОВЛЕНИЯ ПО СЕТЯМ:')
    
    networks = ['ethereum', 'base', 'solana']
    for network in networks:
        network_positions = [r for r in positions_result.data if r['network'] == network]
        
        if network_positions:
            latest = max(network_positions, key=lambda x: x['created_at'])
            latest_time = latest['created_at'][:16]
            count_today = len([r for r in network_positions if datetime.fromisoformat(r['created_at'].replace('Z', '+00:00')).date() == today])
            
            print(f'  📡 {network.upper()}: последнее обновление {latest_time} (сегодня: {count_today} записей)')
        else:
            print(f'  📡 {network.upper()}: ❌ Нет данных')

if __name__ == '__main__':
    check_position_data_freshness() 