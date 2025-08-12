#!/usr/bin/env python3
import sys
import os
sys.path.append('..')
from database_handler import SupabaseHandler
import json

def check_missing_tokens():
    """Проверяет какие токены отсутствуют в view bio_dao_lp_support"""
    
    supabase_handler = SupabaseHandler()
    
    if not supabase_handler.is_connected():
        print("❌ Не удается подключиться к Supabase")
        return
    
    print('✅ Подключение к Supabase успешно')
    print('=' * 80)
    print('🔍 АНАЛИЗ ОТСУТСТВУЮЩИХ ТОКЕНОВ В VIEW bio_dao_lp_support')
    print('=' * 80)
    
    # Загружаем конфиг токенов
    with open('tokens_pools_config.json', 'r') as f:
        config = json.load(f)
    
    # Получаем текущие записи view
    view_result = supabase_handler.client.table('bio_dao_lp_support').select('*').execute()
    current_tokens = {}
    
    for record in view_result.data:
        token = record['token_symbol']
        network = record['network_display'].lower()
        if network == 'ethereum':
            network = 'ethereum'
        elif network == 'base':
            network = 'base'
        elif network == 'solana':
            network = 'solana'
        
        if token not in current_tokens:
            current_tokens[token] = []
        current_tokens[token].append(network)
    
    print(f"📊 ТЕКУЩИЕ ТОКЕНЫ В VIEW: {len(current_tokens)} уникальных токенов")
    for token, networks in current_tokens.items():
        print(f"   {token}: {', '.join(networks)}")
    
    print(f"\n📋 ВСЕ DAO ТОКЕНЫ ИЗ КОНФИГА:")
    
    # Собираем все уникальные токены из конфига (кроме BIO, SOL, WETH, ETH)
    all_dao_tokens = set()
    
    for network in ['ethereum', 'base', 'solana']:
        for token in config['tokens'][network]:
            symbol = token['symbol']
            if symbol not in ['BIO', 'SOL', 'WETH', 'ETH']:
                all_dao_tokens.add(symbol)
    
    print(f"   Найдено {len(all_dao_tokens)} DAO токенов: {sorted(all_dao_tokens)}")
    
    # Проверяем какие токены отсутствуют
    print(f"\n❌ ОТСУТСТВУЮЩИЕ ТОКЕНЫ:")
    missing_tokens = []
    
    for token in sorted(all_dao_tokens):
        if token not in current_tokens:
            missing_tokens.append(token)
            print(f"   🚫 {token} - ПОЛНОСТЬЮ ОТСУТСТВУЕТ во view")
        else:
            # Проверяем на каких чейнах есть токен в конфиге vs view
            config_networks = []
            for network in ['ethereum', 'base', 'solana']:
                for config_token in config['tokens'][network]:
                    if config_token['symbol'] == token:
                        config_networks.append(network)
            
            view_networks = current_tokens[token]
            missing_networks = [n for n in config_networks if n not in view_networks]
            
            if missing_networks:
                print(f"   ⚠️  {token} - отсутствует на чейнах: {', '.join(missing_networks)}")
                print(f"        (есть в конфиге: {', '.join(config_networks)})")
                print(f"        (есть во view: {', '.join(view_networks)})")
    
    # Анализируем пулы с BIO
    print(f"\n🔍 АНАЛИЗ ПУЛОВ С BIO:")
    
    # Получаем все пулы из dao_pool_snapshots
    pools_result = supabase_handler.client.table('dao_pool_snapshots').select(
        'token_symbol, network, pool_name, is_bio_pair, token_fdv_usd, created_at'
    ).gte('created_at', '2025-07-30T00:00:00Z').execute()
    
    # Группируем по токенам и сетям
    pools_by_token = {}
    for pool in pools_result.data:
        token = pool['token_symbol']
        network = pool['network']
        if token not in pools_by_token:
            pools_by_token[token] = {}
        if network not in pools_by_token[token]:
            pools_by_token[token][network] = []
        pools_by_token[token][network].append({
            'pool_name': pool['pool_name'],
            'is_bio_pair': pool['is_bio_pair'],
            'fdv': pool['token_fdv_usd']
        })
    
    print(f"📊 ПУЛЫ В DAO_POOL_SNAPSHOTS:")
    for token in sorted(all_dao_tokens):
        if token in pools_by_token:
            print(f"\n   💰 {token}:")
            for network in ['ethereum', 'base', 'solana']:
                if network in pools_by_token[token]:
                    pools = pools_by_token[token][network]
                    bio_pools = [p for p in pools if p['is_bio_pair']]
                    non_bio_pools = [p for p in pools if not p['is_bio_pair']]
                    
                    if bio_pools:
                        print(f"      ✅ {network}: {len(bio_pools)} BIO пулов")
                        for pool in bio_pools[:2]:  # Показываем первые 2
                            print(f"         - {pool['pool_name']} (FDV: ${pool['fdv']:,.0f})")
                    else:
                        print(f"      ❌ {network}: БЕЗ BIO пулов")
                        if non_bio_pools:
                            print(f"         (есть {len(non_bio_pools)} не-BIO пулов)")
                else:
                    print(f"      ❌ {network}: НЕТ ДАННЫХ")
        else:
            print(f"\n   🚫 {token}: НЕТ ДАННЫХ ВООБЩЕ")
    
    # Рекомендации
    print(f"\n🎯 РЕКОМЕНДАЦИИ ДЛЯ ИСПРАВЛЕНИЯ:")
    print(f"1. Нужно добавить отсутствующие токены как 'Need to Create'")
    print(f"2. Для каждого DAO токена должна быть BIO пара на всех 3 чейнах")
    print(f"3. Если реальной BIO пары нет - показывать как 'Need to Create'")
    
    if missing_tokens:
        print(f"\n🔧 ПОЛНОСТЬЮ ОТСУТСТВУЮЩИЕ ТОКЕНЫ: {len(missing_tokens)}")
        for token in missing_tokens:
            print(f"   - {token}")

if __name__ == '__main__':
    check_missing_tokens()
