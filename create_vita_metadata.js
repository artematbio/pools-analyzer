
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
