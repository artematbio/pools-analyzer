#!/usr/bin/env python3

import json
from datetime import datetime

def create_metadata_plan():
    """Создаем план добавления метаданных для VITA токена на Solana"""
    
    print("📋 ПЛАН ДОБАВЛЕНИЯ МЕТАДАННЫХ VITA НА SOLANA")
    print("============================================")
    print()
    
    # Основываясь на метаданных VITA с Ethereum
    vita_metadata = {
        "name": "VitaDAO",
        "symbol": "VITA", 
        "description": "VitaDAO token for decentralized longevity research funding",
        "image": "https://static.alchemyapi.io/images/assets/19214.png",
        "external_url": "https://vitadao.org",
        "properties": {
            "category": "fungible",
            "creators": [
                {
                    "address": "vita3LfgKErA37DWA7W8RBks3c7Rym2hPFgizNRshBi",
                    "share": 100
                }
            ]
        },
        "attributes": [
            {
                "trait_type": "Type",
                "value": "Governance Token"
            },
            {
                "trait_type": "Blockchain",
                "value": "Solana"
            },
            {
                "trait_type": "Use Case", 
                "value": "Longevity Research"
            }
        ]
    }
    
    # Metaplex Metadata format
    metaplex_metadata = {
        "name": "VitaDAO",
        "symbol": "VITA",
        "uri": "https://your-domain.com/vita-metadata.json",  # Нужно загрузить JSON
        "sellerFeeBasisPoints": 0,
        "creators": None,
        "collection": None,
        "uses": None
    }
    
    print("1️⃣ JSON МЕТАДАННЫЕ (для загрузки на IPFS/Arweave):")
    print("=" * 50)
    print(json.dumps(vita_metadata, indent=2, ensure_ascii=False))
    print()
    
    print("2️⃣ METAPLEX METADATA FORMAT:")
    print("=" * 50)
    print(json.dumps(metaplex_metadata, indent=2, ensure_ascii=False))
    print()
    
    # Сохраняем в файлы
    with open('vita_metadata.json', 'w', encoding='utf-8') as f:
        json.dump(vita_metadata, f, indent=2, ensure_ascii=False)
    
    with open('vita_metaplex_format.json', 'w', encoding='utf-8') as f:
        json.dump(metaplex_metadata, f, indent=2, ensure_ascii=False)
    
    print("3️⃣ ТЕХНИЧЕСКИЙ ПЛАН РЕАЛИЗАЦИИ:")
    print("=" * 50)
    print()
    print("🔧 ШАГ 1: Подготовка метаданных")
    print("   • ✅ JSON файл создан: vita_metadata.json")
    print("   • ✅ Metaplex формат: vita_metaplex_format.json")
    print("   • 🔄 Загрузить JSON на IPFS/Arweave")
    print("   • 🔄 Получить постоянный URI")
    print()
    
    print("🔧 ШАГ 2: Создание метаданных через Metaplex")
    print("   • Использовать @metaplex-foundation/js SDK")
    print("   • CreateMetadataV2 instruction")
    print("   • Нужны права mint authority")
    print()
    
    print("🔧 ШАГ 3: Альтернативы (без mint authority)")
    print("   • Token Extensions Program")
    print("   • Metadata Pointer extension")
    print("   • Embedded metadata в mint account")
    print()
    
    # JavaScript код для создания метаданных
    js_code = '''
// JAVASCRIPT КОД ДЛЯ СОЗДАНИЯ МЕТАДАННЫХ
// =====================================

import { 
  createCreateMetadataAccountV2Instruction,
  PROGRAM_ID as METADATA_PROGRAM_ID,
  createUpdateMetadataAccountV2Instruction
} from '@metaplex-foundation/mpl-token-metadata';
import { PublicKey, Transaction } from '@solana/web3.js';

// Конфигурация
const VITA_MINT = new PublicKey('vita3LfgKErA37DWA7W8RBks3c7Rym2hPFgizNRshBi');
const METADATA_URI = 'https://your-ipfs-or-arweave-url/vita-metadata.json';

// Функция создания метаданных
async function createVitaMetadata(connection, payer) {
  try {
    // Вычисляем Metadata PDA
    const [metadataPDA] = PublicKey.findProgramAddressSync(
      [
        Buffer.from('metadata'),
        METADATA_PROGRAM_ID.toBuffer(),
        VITA_MINT.toBuffer(),
      ],
      METADATA_PROGRAM_ID
    );

    // Метаданные в формате Metaplex
    const metadataData = {
      name: 'VitaDAO',
      symbol: 'VITA', 
      uri: METADATA_URI,
      sellerFeeBasisPoints: 0,
      creators: null,
      collection: null,
      uses: null,
    };

    // Создаем instruction
    const createMetadataInstruction = createCreateMetadataAccountV2Instruction(
      {
        metadata: metadataPDA,
        mint: VITA_MINT,
        mintAuthority: payer.publicKey, // Нужны права!
        payer: payer.publicKey,
        updateAuthority: payer.publicKey,
      },
      {
        createMetadataAccountArgsV2: {
          data: metadataData,
          isMutable: true,
        },
      }
    );

    // Создаем и отправляем транзакцию
    const transaction = new Transaction().add(createMetadataInstruction);
    
    const signature = await connection.sendTransaction(transaction, [payer]);
    await connection.confirmTransaction(signature);
    
    console.log('✅ Метаданные созданы!');
    console.log('📝 Metadata PDA:', metadataPDA.toString());
    console.log('🔗 Signature:', signature);
    
  } catch (error) {
    console.error('❌ Ошибка создания метаданных:', error);
  }
}

// Использование
// createVitaMetadata(connection, wallet);
'''
    
    print("4️⃣ JAVASCRIPT КОД:")
    print("=" * 50)
    print(js_code)
    
    # Сохраняем JS код
    with open('create_vita_metadata.js', 'w', encoding='utf-8') as f:
        f.write(js_code)
    
    print("💾 ФАЙЛЫ СОЗДАНЫ:")
    print("   • vita_metadata.json - метаданные для IPFS")
    print("   • vita_metaplex_format.json - формат Metaplex") 
    print("   • create_vita_metadata.js - JavaScript код")
    print()
    
    print("⚠️ ВАЖНЫЕ ЗАМЕЧАНИЯ:")
    print("   • Нужны права mint authority для токена VITA")
    print("   • JSON файл должен быть загружен на IPFS/Arweave")
    print("   • URI должен быть постоянным и доступным")
    print("   • Рекомендуется тестирование на devnet")
    print()

if __name__ == "__main__":
    create_metadata_plan()
