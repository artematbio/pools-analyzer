#!/usr/bin/env python3

import requests
import json

def check_vita_mint_structure():
    """Реальная проверка структуры VITA mint account на Solana"""
    
    print("🔍 РЕАЛЬНАЯ ПРОВЕРКА СТРУКТУРЫ VITA НА SOLANA")
    print("=============================================")
    print()
    
    vita_mint = "vita3LfgKErA37DWA7W8RBks3c7Rym2hPFgizNRshBi"
    
    # Используем публичный RPC (без ключа для демонстрации)
    public_rpc = "https://api.mainnet-beta.solana.com"
    
    print(f"📋 Проверяем mint: {vita_mint}")
    print(f"🔗 RPC: {public_rpc}")
    print()
    
    # Запрос информации о mint account
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
        response = requests.post(public_rpc, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        if 'result' in data and data['result'] and data['result']['value']:
            account_info = data['result']['value']
            parsed_data = account_info.get('data', {}).get('parsed', {})
            mint_info = parsed_data.get('info', {})
            
            print("✅ MINT ACCOUNT НАЙДЕН!")
            print("=======================")
            print()
            
            # Основная информация о mint
            decimals = mint_info.get('decimals', 'N/A')
            supply = mint_info.get('supply', 'N/A') 
            mint_authority = mint_info.get('mintAuthority', 'N/A')
            freeze_authority = mint_info.get('freezeAuthority', 'N/A')
            
            print(f"📊 Decimals: {decimals}")
            print(f"🏪 Supply: {supply}")
            print(f"🔐 Mint Authority: {mint_authority}")
            print(f"❄️ Freeze Authority: {freeze_authority}")
            print()
            
            # Анализ mint authority
            print("🔍 АНАЛИЗ MINT AUTHORITY:")
            print("========================")
            
            wormhole_addresses = [
                "wormDTUJ6AWPNvk59vGQbDvGJmqbDTdgWgAqcLBCgUb",  # Token Bridge
                "worm2ZoG2kUd4vFXhvjh93UUH596ayRfgQ2MgjNMTth",  # Core Bridge
            ]
            
            is_wormhole_bridge = mint_authority in wormhole_addresses
            
            if is_wormhole_bridge:
                print("🌉 ✅ ПОДТВЕРЖДЕНО: Это Wormhole/Portal bridge токен!")
                print(f"   • Mint Authority: {mint_authority}")
                print(f"   • Это программа Token Bridge Wormhole")
                print()
                
                print("❌ ПРОБЛЕМЫ С МЕТАДАННЫМИ:")
                print("   • Mint Authority принадлежит Wormhole")
                print("   • VitaDAO не может использовать CreateMetadataV2")
                print("   • Нужны альтернативные решения")
                print()
                
            elif mint_authority == vita_mint:
                print("🤔 СТРАННО: Mint Authority = сам mint address")
                print("   • Это может означать, что authority отозван")
                print("   • Или это особая конфигурация")
                print()
                
            elif mint_authority is None or mint_authority == 'null':
                print("🚫 Mint Authority отозван (null)")
                print("   • Невозможно создать метаданные через Metaplex")
                print("   • Supply токена зафиксирован")
                print()
                
            else:
                print(f"🔍 НЕИЗВЕСТНЫЙ Mint Authority: {mint_authority}")
                print("   • Не является стандартным Wormhole адресом")
                print("   • Нужно дополнительное исследование")
                print()
            
            # Проверяем совпадение decimals с Ethereum
            print("🔗 СРАВНЕНИЕ С ETHEREUM:")
            print("========================")
            print(f"   • Solana decimals: {decimals}")
            print("   • Ethereum decimals: 18 (из Alchemy API)")
            
            if str(decimals) == "18":
                print("   ✅ Decimals совпадают - индикатор bridge токена")
            else:
                print("   ❓ Decimals не совпадают - может быть нативный токен")
            print()
            
            # Выводим полную структуру для анализа
            print("📄 ПОЛНАЯ СТРУКТУРА MINT ACCOUNT:")
            print("=================================")
            print(json.dumps(mint_info, indent=2))
            print()
            
        else:
            print("❌ MINT ACCOUNT НЕ НАЙДЕН!")
            error = data.get('error', {})
            print(f"Ошибка: {error}")
            print()
            
    except Exception as e:
        print(f"❌ ОШИБКА ЗАПРОСА: {e}")
        print()
    
    # Заключение и рекомендации
    print("🎯 ЗАКЛЮЧЕНИЕ:")
    print("==============")
    print()
    print("Если VITA - это Wormhole bridge токен:")
    print("   ❌ Традиционные метаданные невозможны")
    print("   ✅ Нужны альтернативные решения")
    print()
    print("💡 РЕКОМЕНДУЕМЫЕ АЛЬТЕРНАТИВЫ:")
    print("   1. Внешний реестр метаданных")
    print("   2. Интеграция с dApps напрямую")
    print("   3. Обращение к команде Wormhole")
    print("   4. Ожидание Token Extensions поддержки")
    print()

if __name__ == "__main__":
    check_vita_mint_structure()
