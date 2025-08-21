
// ТОКЕН EXTENSIONS ПОДХОД (БЕЗ MINT AUTHORITY)
// =============================================

import {
  TOKEN_2022_PROGRAM_ID,
  createInitializeMintInstruction,
  createInitializeMetadataPointerInstruction,
  createInitializeInstruction,
  createUpdateFieldInstruction,
  getMintLen,
  ExtensionType,
} from '@solana/spl-token';
import { PublicKey, SystemProgram, Transaction } from '@solana/web3.js';

// Конфигурация VITA токена
const VITA_MINT = new PublicKey('vita3LfgKErA37DWA7W8RBks3c7Rym2hPFgizNRshBi');

// Метаданные для встраивания
const tokenMetadata = {
  name: 'VitaDAO',
  symbol: 'VITA',
  uri: 'https://ipfs.io/ipfs/your-metadata-hash',
  additionalMetadata: [
    ['description', 'VitaDAO token for decentralized longevity research funding'],
    ['image', 'https://static.alchemyapi.io/images/assets/19214.png'],
    ['external_url', 'https://vitadao.org'],
    ['category', 'fungible'],
    ['use_case', 'longevity_research']
  ]
};

// Функция для добавления метаданных к существующему токену
async function addMetadataToExistingToken(connection, payer) {
  try {
    console.log('🔧 Добавляем метаданные к существующему VITA токену...');
    
    // ⚠️ ПРОБЛЕМА: Нельзя добавить extensions к существующему токену
    // Token Extensions работают только при создании нового токена
    
    console.log('❌ ОГРАНИЧЕНИЕ: Token Extensions нельзя добавить к существующему токену');
    console.log('   Они должны быть настроены при создании mint account');
    console.log();
    
    // Альтернатива: Создание нового токена с extensions
    console.log('🔄 АЛЬТЕРНАТИВА: Создание нового VITA токена с extensions');
    
    return false;
    
  } catch (error) {
    console.error('❌ Ошибка:', error);
    return false;
  }
}

// Функция для создания НОВОГО токена с extensions (для справки)
async function createTokenWithExtensions(connection, payer) {
  try {
    // Генерируем новый mint keypair
    const mint = Keypair.generate();
    
    // Рассчитываем размер account с extensions
    const extensions = [ExtensionType.MetadataPointer];
    const mintLen = getMintLen(extensions);
    
    // Создаем instruction для создания account
    const createAccountInstruction = SystemProgram.createAccount({
      fromPubkey: payer.publicKey,
      newAccountPubkey: mint.publicKey,
      space: mintLen,
      lamports: await connection.getMinimumBalanceForRentExemption(mintLen),
      programId: TOKEN_2022_PROGRAM_ID,
    });
    
    // Инициализируем Metadata Pointer extension
    const initializeMetadataPointerInstruction = 
      createInitializeMetadataPointerInstruction(
        mint.publicKey,
        payer.publicKey, // authority
        mint.publicKey,  // metadata address (same as mint)
        TOKEN_2022_PROGRAM_ID
      );
    
    // Инициализируем mint
    const initializeMintInstruction = createInitializeMintInstruction(
      mint.publicKey,
      9, // decimals
      payer.publicKey, // mint authority
      null, // freeze authority
      TOKEN_2022_PROGRAM_ID
    );
    
    // Инициализируем метаданные
    const initializeMetadataInstruction = createInitializeInstruction({
      programId: TOKEN_2022_PROGRAM_ID,
      mint: mint.publicKey,
      metadata: mint.publicKey,
      name: tokenMetadata.name,
      symbol: tokenMetadata.symbol,
      uri: tokenMetadata.uri,
      mintAuthority: payer.publicKey,
      updateAuthority: payer.publicKey,
    });
    
    // Добавляем дополнительные поля
    const additionalInstructions = tokenMetadata.additionalMetadata.map(
      ([key, value]) => createUpdateFieldInstruction({
        programId: TOKEN_2022_PROGRAM_ID,
        metadata: mint.publicKey,
        updateAuthority: payer.publicKey,
        field: key,
        value: value,
      })
    );
    
    // Создаем транзакцию
    const transaction = new Transaction().add(
      createAccountInstruction,
      initializeMetadataPointerInstruction,
      initializeMintInstruction,
      initializeMetadataInstruction,
      ...additionalInstructions
    );
    
    // Отправляем транзакцию
    const signature = await connection.sendTransaction(transaction, [payer, mint]);
    await connection.confirmTransaction(signature);
    
    console.log('✅ Новый токен с метаданными создан!');
    console.log('🔗 Mint:', mint.publicKey.toString());
    console.log('📝 Signature:', signature);
    
    return mint.publicKey;
    
  } catch (error) {
    console.error('❌ Ошибка создания токена:', error);
    return null;
  }
}

// Использование
// addMetadataToExistingToken(connection, wallet);
// createTokenWithExtensions(connection, wallet);
