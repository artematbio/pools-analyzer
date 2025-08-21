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

async function analyzeSellPressure24h() {
    try {
        console.log('🚀 Анализ Sell Pressure для BIO токена (последние 24 часа)');
        console.log('==========================================================');
        console.log('');

        // Получаем текущий блок
        const currentBlock = await provider.getBlockNumber();
        
        // 24 часа = 24 * 60 * 60 / 12 = 7200 блоков (примерно)
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
        
        console.log(`🔍 Токены в пуле:`);
        console.log(`   Token0: ${token0}`);
        console.log(`   Token1: ${token1}`);
        
        const bioIsToken0 = token0.toLowerCase() === BIO_TOKEN.toLowerCase();
        console.log(`   BIO позиция: ${bioIsToken0 ? 'token0' : 'token1'}`);
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

        // Переменные для суммирования
        let totalBioSold = 0;    // BIO продано (из пула)
        let totalBioBought = 0;  // BIO куплено (в пул)
        let totalWethFromSales = 0;   // WETH получено от продаж BIO
        let totalWethFromPurchases = 0; // WETH потрачено на покупки BIO
        
        let salesCount = 0;
        let purchasesCount = 0;

        console.log(`🔍 Анализ ${logs.length} транзакций за последние 24 часа...`);

        for (let i = 0; i < logs.length; i++) {
            try {
                const log = logs[i];
                const decoded = iface.parseLog({
                    topics: log.topics,
                    data: log.data
                });

                const amount0 = decoded.args.amount0;
                const amount1 = decoded.args.amount1;

                // Определяем направление обмена для BIO
                let bioAmount, wethAmount, isBioSale;
                
                if (bioIsToken0) {
                    bioAmount = Math.abs(Number(ethers.formatEther(amount0)));
                    wethAmount = Math.abs(Number(ethers.formatEther(amount1)));
                    isBioSale = amount0 < 0n; // BIO выходит из пула (продажа)
                } else {
                    bioAmount = Math.abs(Number(ethers.formatEther(amount1)));
                    wethAmount = Math.abs(Number(ethers.formatEther(amount0)));
                    isBioSale = amount1 < 0n; // BIO выходит из пула (продажа)
                }

                if (isBioSale) {
                    // Продажа BIO (BIO → WETH)
                    totalBioSold += bioAmount;
                    totalWethFromSales += wethAmount;
                    salesCount++;
                } else {
                    // Покупка BIO (WETH → BIO)
                    totalBioBought += bioAmount;
                    totalWethFromPurchases += wethAmount;
                    purchasesCount++;
                }

                // Прогресс
                if (i % 200 === 0 && i > 0) {
                    console.log(`   📊 Обработано ${i}/${logs.length} событий... (Продажи: ${salesCount}, Покупки: ${purchasesCount})`);
                }

            } catch (error) {
                console.log(`⚠️ Ошибка обработки лога ${i}: ${error.message}`);
            }
        }

        console.log('');
        console.log('🎯 РЕЗУЛЬТАТЫ АНАЛИЗА SELL PRESSURE (24 ЧАСА)');
        console.log('===============================================');
        console.log('');
        
        console.log('📉 ПРОДАЖИ BIO:');
        console.log(`   • Количество операций: ${salesCount.toLocaleString()}`);
        console.log(`   • Объем BIO продано: ${totalBioSold.toLocaleString()} BIO`);
        console.log(`   • Получено WETH: ${totalWethFromSales.toFixed(6)} WETH`);
        console.log(`   • Оценочная стоимость: $${(totalWethFromSales * WETH_PRICE_USD).toLocaleString()}`);
        console.log('');
        
        console.log('📈 ПОКУПКИ BIO:');
        console.log(`   • Количество операций: ${purchasesCount.toLocaleString()}`);
        console.log(`   • Объем BIO куплено: ${totalBioBought.toLocaleString()} BIO`);
        console.log(`   • Потрачено WETH: ${totalWethFromPurchases.toFixed(6)} WETH`);
        console.log(`   • Оценочная стоимость: $${(totalWethFromPurchases * WETH_PRICE_USD).toLocaleString()}`);
        console.log('');

        // Рассчитываем sell pressure
        const netBioFlow = totalBioSold - totalBioBought;
        const netWethFlow = totalWethFromSales - totalWethFromPurchases;
        const netUsdFlow = netWethFlow * WETH_PRICE_USD;

        console.log('⚖️ SELL PRESSURE (ЧИСТЫЙ ПОТОК ЗА 24 ЧАСА):');
        console.log(`   • Чистый поток BIO: ${netBioFlow > 0 ? '+' : ''}${netBioFlow.toLocaleString()} BIO`);
        console.log(`   • Чистый поток WETH: ${netWethFlow > 0 ? '+' : ''}${netWethFlow.toFixed(6)} WETH`);
        console.log(`   • Оценочная стоимость: ${netUsdFlow > 0 ? '+' : ''}$${netUsdFlow.toLocaleString()}`);
        console.log('');

        if (netBioFlow > 0) {
            console.log('🔴 РЕЗУЛЬТАТ: Преобладает sell pressure (больше продаж)');
            const sellPressurePercent = ((netBioFlow / totalBioBought) * 100).toFixed(1);
            console.log(`   📊 Избыток продаж: ${sellPressurePercent}%`);
        } else if (netBioFlow < 0) {
            console.log('🟢 РЕЗУЛЬТАТ: Преобладает buy pressure (больше покупок)');
            const buyPressurePercent = ((-netBioFlow / totalBioSold) * 100).toFixed(1);
            console.log(`   📊 Избыток покупок: ${buyPressurePercent}%`);
        } else {
            console.log('🟡 РЕЗУЛЬТАТ: Сбалансированная торговля');
        }

        console.log('');
        console.log('📊 ДОПОЛНИТЕЛЬНАЯ СТАТИСТИКА:');
        console.log(`   • Общее количество операций: ${(salesCount + purchasesCount).toLocaleString()}`);
        console.log(`   • Соотношение продажи/покупки: ${(salesCount / purchasesCount).toFixed(2)}`);
        console.log(`   • Средний размер продажи: ${(totalBioSold / salesCount).toLocaleString()} BIO`);
        console.log(`   • Средний размер покупки: ${(totalBioBought / purchasesCount).toLocaleString()} BIO`);

        // Получаем временные рамки
        const firstBlock = await provider.getBlock(fromBlock24h);
        const lastBlock = await provider.getBlock(currentBlock);
        
        console.log('');
        console.log('📅 ВРЕМЕННЫЕ РАМКИ (ПОСЛЕДНИЕ 24 ЧАСА):');
        console.log(`   • Начало: ${new Date(firstBlock.timestamp * 1000).toISOString()}`);
        console.log(`   • Конец: ${new Date(lastBlock.timestamp * 1000).toISOString()}`);
        console.log(`   • Продолжительность: ${((lastBlock.timestamp - firstBlock.timestamp) / 3600).toFixed(1)} часов`);

        // Сравнение с предыдущим анализом
        console.log('');
        console.log('🔄 СРАВНЕНИЕ С ОБЩИМ ТРЕНДОМ (12-14 августа):');
        console.log('   Предыдущий анализ показал buy pressure +20.9%');
        if (netBioFlow < 0) {
            const currentBuyPressure = ((-netBioFlow / totalBioSold) * 100);
            if (currentBuyPressure > 20.9) {
                console.log('   📈 Buy pressure УСИЛИЛОСЬ за последние 24 часа!');
            } else if (currentBuyPressure > 10) {
                console.log('   📊 Buy pressure сохраняется, но слабее общего тренда');
            } else {
                console.log('   📉 Buy pressure ослабло по сравнению с общим трендом');
            }
        } else if (netBioFlow > 0) {
            console.log('   🔄 ИЗМЕНЕНИЕ ТРЕНДА: теперь преобладает sell pressure!');
        }

    } catch (error) {
        console.error('❌ Ошибка анализа:', error);
    }
}

// Запуск анализа
analyzeSellPressure24h();

