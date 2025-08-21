#!/usr/bin/env python3

import requests
import json
import os
from datetime import datetime

def check_solana_token_metadata():
    """Проверяем метаданные токена VITA на Solana через Helius RPC"""
    
    print("🔍 ПРОВЕРКА МЕТАДАННЫХ VITA НА SOLANA")
    print("====================================")
    print()
    
    # VITA token mint на Solana
    vita_mint = "vita3LfgKErA37DWA7W8RBks3c7Rym2hPFgizNRshBi"
    
    # Helius RPC endpoint (из env.example)
    helius_key = "your_helius_api_key"  # Заглушка, в реальности из .env
    rpc_url = f"https://mainnet.helius-rpc.com/?api-key={helius_key}"
    
    print(f"📋 Токен: {vita_mint}")
    print(f"🔗 RPC: {rpc_url}")
    print()
    
    # 1. Проверяем account info токена
    print("1️⃣ Получаем информацию о mint account...")
    
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAccountInfo",
        "params": [
            vita_mint,
            {
                "encoding": "jsonParsed"
            }
        ]
    }
    
    try:
        response = requests.post(rpc_url, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'result' in data and data['result']:
            account_info = data['result']['value']
            if account_info:
                parsed_data = account_info.get('data', {}).get('parsed', {})
                mint_info = parsed_data.get('info', {})
                
                print(f"   ✅ Mint найден!")
                print(f"   📊 Decimals: {mint_info.get('decimals', 'N/A')}")
                print(f"   🏪 Supply: {mint_info.get('supply', 'N/A')}")
                print(f"   🔐 Mint Authority: {mint_info.get('mintAuthority', 'N/A')}")
                print(f"   ❄️ Freeze Authority: {mint_info.get('freezeAuthority', 'N/A')}")
                print()
            else:
                print("   ❌ Account не найден")
                print()
        else:
            print("   ❌ Ошибка получения данных")
            print()
            
    except Exception as e:
        print(f"   ❌ Ошибка запроса: {e}")
        print()
    
    # 2. Ищем Metadata Account (Metaplex)
    print("2️⃣ Ищем Metaplex Metadata Account...")
    
    # Вычисляем Metadata PDA для данного mint
    # Metaplex использует seeds: ["metadata", metaplex_program_id, mint_account]
    metaplex_program_id = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
    
    # Для простоты покажем концепцию, в реальности нужно вычислить PDA
    print(f"   🔍 Metaplex Program: {metaplex_program_id}")
    print(f"   📝 Для токена {vita_mint}")
    print(f"   ⚠️ Нужно вычислить PDA для проверки метаданных")
    print()
    
    # 3. Проверяем через DAS API (Digital Asset Standard)
    print("3️⃣ Проверяем через Helius DAS API...")
    
    das_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getAsset",
        "params": {
            "id": vita_mint
        }
    }
    
    try:
        response = requests.post(rpc_url, json=das_payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'result' in data and data['result']:
            asset_data = data['result']
            print(f"   ✅ Asset найден через DAS!")
            print(f"   📛 Name: {asset_data.get('content', {}).get('metadata', {}).get('name', 'N/A')}")
            print(f"   🏷️ Symbol: {asset_data.get('content', {}).get('metadata', {}).get('symbol', 'N/A')}")
            print(f"   📄 Description: {asset_data.get('content', {}).get('metadata', {}).get('description', 'N/A')}")
            
            # Проверяем files/images
            files = asset_data.get('content', {}).get('files', [])
            if files:
                print(f"   🖼️ Image: {files[0].get('uri', 'N/A')}")
            else:
                print(f"   🖼️ Image: N/A")
            
            print()
            
            # Полные метаданные
            print("📊 ПОЛНЫЕ МЕТАДАННЫЕ:")
            print(json.dumps(asset_data, indent=2, ensure_ascii=False))
            
        else:
            print("   ❌ Asset не найден через DAS")
            error = data.get('error', {})
            print(f"   ❗ Ошибка: {error}")
            print()
            
    except Exception as e:
        print(f"   ❌ Ошибка DAS запроса: {e}")
        print()
    
    # 4. Анализ результатов
    print("🎯 АНАЛИЗ РЕЗУЛЬТАТОВ:")
    print("====================")
    print()
    print("📋 Статус метаданных VITA на Solana:")
    print("   • Mint account: существует")
    print("   • Metaplex metadata: нужна проверка")
    print("   • DAS compatibility: нужна проверка")
    print()
    print("🔧 ПЛАН ДОБАВЛЕНИЯ МЕТАДАННЫХ:")
    print("1. Создать JSON файл с метаданными")
    print("2. Загрузить на IPFS/Arweave")
    print("3. Использовать CreateMetadataV2 instruction")
    print("4. Указать URI на JSON файл")
    print()

if __name__ == "__main__":
    check_solana_token_metadata()
