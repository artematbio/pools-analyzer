const fs = require('fs');
const ethers = require('ethers');

// Константы
const POOL_ADDRESS = '0x08a5a1e2671839dadc25e2e20f9206fd33c88092'; // BIO/WETH pool
const BIO_TOKEN = '0xcb1592591996765ec0efc1f92599a19767ee5ffa';
const WETH_TOKEN = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2';
const WETH_PRICE_USD = 3400; // Примерная цена WETH для оценки

// Настройка провайдера
const ALCHEMY_KEY = process.env.ALCHEMY_API_KEY || 'Hkg1Oi9c8x3JEiXj2cL62';
const RPC_URL = `https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`;
const provider = new ethers.JsonRpcProvider(RPC_URL);

// ABI для Swap события
const SWAP_EVENT_ABI = [
    "event Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)"
];

async function analyzeTopSellers24h() {
    try {
        console.log('🔍 Анализ крупнейших продавцов BIO за последние 24 часа');
        console.log('========================================================');
        console.log('');

        // Получаем текущий блок
        const currentBlock = await provider.getBlockNumber();
        
        // 24 часа = 7200 блоков (примерно)
        const BLOCKS_24H = 7200;
        const fromBlock24h = currentBlock - BLOCKS_24H;

        console.log(`📊 Блоки: ${fromBlock24h} → ${currentBlock}`);
        console.log(`📈 Диапазон: ${BLOCKS_24H} блоков (24 часа)`);
        console.log('');

        // Получаем информацию о токенах в пуле
        const poolContract = new ethers.Contract(POOL_ADDRESS, [
            "function token0() view returns (address)",
            "function token1() view returns (address)"
        ], provider);

        const token0 = await poolContract.token0();
        const token1 = await poolContract.token1();
        
        const bioIsToken0 = token0.toLowerCase() === BIO_TOKEN.toLowerCase();
        console.log(`🔍 BIO позиция в пуле: ${bioIsToken0 ? 'token0' : 'token1'}`);
        console.log('');

        // Получаем логи Swap событий за последние 24 часа
        console.log(`🔄 Получение всех Swap событий за последние 24 часа...`);

        const filter = {
            address: POOL_ADDRESS,
            topics: [ethers.id("Swap(address,address,int256,int256,uint160,uint128,int24)")],
            fromBlock: fromBlock24h,
            toBlock: "latest"
        };

        const logs = await provider.getLogs(filter);
        console.log(`📦 Найдено событий: ${logs.length}`);
        console.log('');

        // Создаем интерфейс для парсинга
        const iface = new ethers.Interface(SWAP_EVENT_ABI);

        // Объект для хранения данных по продавцам
        const sellerData = {};

        console.log(`🔍 Анализ продаж BIO...`);

        for (let i = 0; i < logs.length; i++) {
            try {
                const log = logs[i];
                const decoded = iface.parseLog({
                    topics: log.topics,
                    data: log.data
                });

                const sender = decoded.args.sender;
                const amount0 = decoded.args.amount0;
                const amount1 = decoded.args.amount1;

                // ИСПРАВЛЕННАЯ ЛОГИКА: Определяем продажу BIO
                let bioAmount, wethAmount, isBioSale;
                
                if (bioIsToken0) {
                    // BIO = token0
                    bioAmount = Math.abs(Number(ethers.formatEther(amount0)));
                    wethAmount = Math.abs(Number(ethers.formatEther(amount1)));
                    isBioSale = amount0 > 0n; // BIO ВХОДИТ в пул = ПРОДАЖА BIO
                } else {
                    // BIO = token1
                    bioAmount = Math.abs(Number(ethers.formatEther(amount1)));
                    wethAmount = Math.abs(Number(ethers.formatEther(amount0)));
                    isBioSale = amount1 > 0n; // BIO ВХОДИТ в пул = ПРОДАЖА BIO
                }

                // Собираем только продажи BIO
                if (isBioSale) {
                    if (!sellerData[sender]) {
                        sellerData[sender] = {
                            address: sender,
                            totalBioSold: 0,
                            totalWethReceived: 0,
                            transactionCount: 0,
                            transactions: []
                        };
                    }

                    sellerData[sender].totalBioSold += bioAmount;
                    sellerData[sender].totalWethReceived += wethAmount;
                    sellerData[sender].transactionCount += 1;
                    sellerData[sender].transactions.push({
                        txHash: log.transactionHash,
                        blockNumber: log.blockNumber,
                        bioAmount: bioAmount,
                        wethAmount: wethAmount,
                        usdValue: wethAmount * WETH_PRICE_USD
                    });
                }

                // Прогресс
                if (i % 100 === 0 && i > 0) {
                    console.log(`   📊 Обработано ${i}/${logs.length} событий...`);
                }

            } catch (error) {
                console.log(`⚠️ Ошибка обработки лога ${i}: ${error.message}`);
            }
        }

        // Преобразуем в массив и сортируем по USD стоимости
        const sortedSellers = Object.values(sellerData)
            .map(seller => ({
                ...seller,
                totalUsdValue: seller.totalWethReceived * WETH_PRICE_USD
            }))
            .sort((a, b) => b.totalUsdValue - a.totalUsdValue);

        console.log('');
        console.log('🏆 ТОП КРУПНЕЙШИХ ПРОДАВЦОВ BIO (последние 24 часа)');
        console.log('==================================================');
        console.log('');

        if (sortedSellers.length === 0) {
            console.log('❌ Продаж BIO не найдено за последние 24 часа');
            return;
        }

        // Показываем топ-20 продавцов
        const topCount = Math.min(20, sortedSellers.length);
        
        for (let i = 0; i < topCount; i++) {
            const seller = sortedSellers[i];
            console.log(`${i + 1}. 💰 ${seller.address}`);
            console.log(`   📊 Продано BIO: ${seller.totalBioSold.toLocaleString()} BIO`);
            console.log(`   💎 Получено WETH: ${seller.totalWethReceived.toFixed(6)} WETH`);
            console.log(`   💵 USD стоимость: $${seller.totalUsdValue.toLocaleString()}`);
            console.log(`   🔢 Транзакций: ${seller.transactionCount}`);
            console.log(`   📈 Средний размер: ${(seller.totalBioSold / seller.transactionCount).toLocaleString()} BIO`);
            
            // Показываем самую крупную транзакцию этого продавца
            const largestTx = seller.transactions.sort((a, b) => b.usdValue - a.usdValue)[0];
            console.log(`   🎯 Крупнейшая продажа: $${largestTx.usdValue.toLocaleString()} (${largestTx.bioAmount.toLocaleString()} BIO)`);
            console.log(`      TX: ${largestTx.txHash}`);
            console.log('');
        }

        // Статистика
        const totalSellers = sortedSellers.length;
        const totalBioSold = sortedSellers.reduce((sum, seller) => sum + seller.totalBioSold, 0);
        const totalUsdValue = sortedSellers.reduce((sum, seller) => sum + seller.totalUsdValue, 0);

        console.log('📊 ОБЩАЯ СТАТИСТИКА ПРОДАЖ:');
        console.log(`   • Всего уникальных продавцов: ${totalSellers}`);
        console.log(`   • Общий объем продаж: ${totalBioSold.toLocaleString()} BIO`);
        console.log(`   • Общая USD стоимость: $${totalUsdValue.toLocaleString()}`);
        console.log(`   • Средняя продажа на адрес: ${(totalBioSold / totalSellers).toLocaleString()} BIO`);

        // Анализ концентрации
        const top5Volume = sortedSellers.slice(0, 5).reduce((sum, seller) => sum + seller.totalUsdValue, 0);
        const top10Volume = sortedSellers.slice(0, 10).reduce((sum, seller) => sum + seller.totalUsdValue, 0);
        
        console.log('');
        console.log('🎯 КОНЦЕНТРАЦИЯ ПРОДАЖ:');
        console.log(`   • Топ-5 продавцов: ${((top5Volume / totalUsdValue) * 100).toFixed(1)}% от общего объема`);
        console.log(`   • Топ-10 продавцов: ${((top10Volume / totalUsdValue) * 100).toFixed(1)}% от общего объема`);

        // Сохраняем детальный отчет в CSV
        const csvLines = ['Address,Total BIO Sold,Total WETH Received,USD Value,Transaction Count,Average Sale Size'];
        
        sortedSellers.forEach(seller => {
            csvLines.push([
                seller.address,
                seller.totalBioSold.toFixed(6),
                seller.totalWethReceived.toFixed(6),
                seller.totalUsdValue.toFixed(2),
                seller.transactionCount,
                (seller.totalBioSold / seller.transactionCount).toFixed(6)
            ].join(','));
        });

        const csvContent = csvLines.join('\n');
        const csvFilename = `top_bio_sellers_24h_${Date.now()}.csv`;
        fs.writeFileSync(csvFilename, csvContent);
        
        console.log('');
        console.log(`💾 Детальный отчет сохранен: ${csvFilename}`);

    } catch (error) {
        console.error('❌ Ошибка анализа:', error);
    }
}

// Запуск анализа
analyzeTopSellers24h();
