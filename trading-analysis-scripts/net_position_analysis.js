const fs = require('fs');
const ethers = require('ethers');

// Топ продавцы из предыдущего анализа
const TOP_SELLERS = [
    '0x98C3d3183C4b8A650614ad179A1a98be0a8d6B8E',
    '0xfBd4cdB413E45a52E2C8312f670e9cE67E794C37',
    '0xfbEedCFe378866DaB6abbaFd8B2986F5C1768737',
    '0x6747BcaF9bD5a5F0758Cbe08903490E45DdfACB5',
    '0x5141B82f5fFDa4c6fE1E372978F1C5427640a190',
    '0x66a9893cC07D91D95644AEDD05D03f95e1dBA8Af',
    '0x6E2c0F7C995E1e75b925512B1859eB3E9F9C11C0',
    '0x2905d7e4D048d29954F81b02171DD313F457a4a4',
    '0x3708F5c9533557B1633c7a255Ed385348488AeaE',
    '0x111111125421cA6dc452d289314280a0f8842A65',
    '0x00000000A991C429eE2Ec6df19d40fe0c80088B8',
    '0x8331f9ACcE69b02C281F40a00706f758665ccE77',
    '0xEff6cb8b614999d130E537751Ee99724D01aA167',
    '0x76600115C5Cbe56d82bDe2Af8CAfb3801AEE5EFe',
    '0xE592427A0AEce92De3Edee1F18E0157C05861564',
    '0xDf31A70a21A1931e02033dBBa7DEaCe6c45cfd0f',
    '0x2E1Dee213BA8d7af0934C49a23187BabEACa8764',
    '0x0B570b66cF3b5eAb1FD10c89230cad58aA2FCb59',
    '0x8189AFcC5B73Dc90600FeE92e5267Aff1D192884',
    '0x7C81247aE0A35B03e3f4A704DCD6b101dcA53Abd'
];

// Константы
const POOL_ADDRESS = '0x08a5a1e2671839dadc25e2e20f9206fd33c88092';
const BIO_TOKEN = '0xcb1592591996765ec0efc1f92599a19767ee5ffa';
const WETH_TOKEN = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2';
const WETH_PRICE_USD = 3400;

// Настройка провайдера
const ALCHEMY_KEY = process.env.ALCHEMY_API_KEY || 'Hkg1Oi9c8x3JEiXj2cL62';
const RPC_URL = `https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`;
const provider = new ethers.JsonRpcProvider(RPC_URL);

// ABI для Swap события
const SWAP_EVENT_ABI = [
    "event Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)"
];

async function analyzeNetPositions() {
    try {
        console.log('📊 Анализ чистых позиций топ продавцов BIO');
        console.log('==========================================');
        console.log('');

        // Получаем текущий блок
        const currentBlock = await provider.getBlockNumber();
        const BLOCKS_24H = 7200;
        const fromBlock24h = currentBlock - BLOCKS_24H;

        console.log(`📅 Анализируем последние 24 часа (блоки ${fromBlock24h} → ${currentBlock})`);
        console.log(`🔍 Проверяем ${TOP_SELLERS.length} адресов`);
        console.log('');

        // Получаем информацию о токенах в пуле
        const poolContract = new ethers.Contract(POOL_ADDRESS, [
            "function token0() view returns (address)",
            "function token1() view returns (address)"
        ], provider);

        const token0 = await poolContract.token0();
        const bioIsToken0 = token0.toLowerCase() === BIO_TOKEN.toLowerCase();
        console.log(`💎 BIO позиция в пуле: ${bioIsToken0 ? 'token0' : 'token1'}`);
        console.log('');

        // Получаем логи Swap событий
        console.log(`🔄 Получение всех Swap событий...`);
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

        // Объект для хранения данных по адресам
        const addressData = {};

        // Инициализируем данные для топ продавцов
        TOP_SELLERS.forEach(address => {
            addressData[address.toLowerCase()] = {
                address: address,
                totalBioSold: 0,
                totalBioBought: 0,
                totalWethFromSales: 0,
                totalWethFromPurchases: 0,
                salesCount: 0,
                purchasesCount: 0,
                transactions: []
            };
        });

        console.log(`🔍 Анализ транзакций...`);

        for (let i = 0; i < logs.length; i++) {
            try {
                const log = logs[i];
                const decoded = iface.parseLog({
                    topics: log.topics,
                    data: log.data
                });

                const sender = decoded.args.sender.toLowerCase();
                const amount0 = decoded.args.amount0;
                const amount1 = decoded.args.amount1;

                // Проверяем, есть ли этот адрес в нашем списке
                if (addressData[sender]) {
                    let bioAmount, wethAmount, isBioSale;
                    
                    if (bioIsToken0) {
                        bioAmount = Math.abs(Number(ethers.formatEther(amount0)));
                        wethAmount = Math.abs(Number(ethers.formatEther(amount1)));
                        isBioSale = amount0 > 0n; // BIO входит в пул = продажа BIO
                    } else {
                        bioAmount = Math.abs(Number(ethers.formatEther(amount1)));
                        wethAmount = Math.abs(Number(ethers.formatEther(amount0)));
                        isBioSale = amount1 > 0n; // BIO входит в пул = продажа BIO
                    }

                    if (isBioSale) {
                        // Продажа BIO
                        addressData[sender].totalBioSold += bioAmount;
                        addressData[sender].totalWethFromSales += wethAmount;
                        addressData[sender].salesCount++;
                    } else {
                        // Покупка BIO
                        addressData[sender].totalBioBought += bioAmount;
                        addressData[sender].totalWethFromPurchases += wethAmount;
                        addressData[sender].purchasesCount++;
                    }

                    addressData[sender].transactions.push({
                        txHash: log.transactionHash,
                        blockNumber: log.blockNumber,
                        type: isBioSale ? 'SELL' : 'BUY',
                        bioAmount: bioAmount,
                        wethAmount: wethAmount,
                        usdValue: wethAmount * WETH_PRICE_USD
                    });
                }

                if (i % 100 === 0 && i > 0) {
                    console.log(`   📊 Обработано ${i}/${logs.length} событий...`);
                }

            } catch (error) {
                console.log(`⚠️ Ошибка обработки лога ${i}: ${error.message}`);
            }
        }

        console.log('');
        console.log('🎯 АНАЛИЗ ЧИСТЫХ ПОЗИЦИЙ ТОП ПРОДАВЦОВ');
        console.log('=====================================');
        console.log('');

        // Фильтруем только адреса, которые имели активность
        const activeAddresses = Object.values(addressData)
            .filter(data => data.salesCount > 0 || data.purchasesCount > 0)
            .map(data => ({
                ...data,
                netBio: data.totalBioSold - data.totalBioBought,
                netWeth: data.totalWethFromSales - data.totalWethFromPurchases,
                netUsd: (data.totalWethFromSales - data.totalWethFromPurchases) * WETH_PRICE_USD,
                totalTransactions: data.salesCount + data.purchasesCount
            }))
            .sort((a, b) => Math.abs(b.netUsd) - Math.abs(a.netUsd));

        if (activeAddresses.length === 0) {
            console.log('❌ Активности топ продавцов не найдено');
            return;
        }

        for (let i = 0; i < activeAddresses.length; i++) {
            const addr = activeAddresses[i];
            
            console.log(`${i + 1}. 🏛️ ${addr.address}`);
            console.log(`   📊 Всего транзакций: ${addr.totalTransactions} (${addr.salesCount} продаж, ${addr.purchasesCount} покупок)`);
            console.log('');
            
            if (addr.salesCount > 0) {
                console.log(`   📉 ПРОДАЖИ:`);
                console.log(`      • BIO продано: ${addr.totalBioSold.toLocaleString()} BIO`);
                console.log(`      • WETH получено: ${addr.totalWethFromSales.toFixed(6)} WETH`);
                console.log(`      • USD стоимость: $${(addr.totalWethFromSales * WETH_PRICE_USD).toLocaleString()}`);
            }
            
            if (addr.purchasesCount > 0) {
                console.log(`   📈 ПОКУПКИ:`);
                console.log(`      • BIO куплено: ${addr.totalBioBought.toLocaleString()} BIO`);
                console.log(`      • WETH потрачено: ${addr.totalWethFromPurchases.toFixed(6)} WETH`);
                console.log(`      • USD стоимость: $${(addr.totalWethFromPurchases * WETH_PRICE_USD).toLocaleString()}`);
            }

            console.log('');
            console.log(`   ⚖️ ЧИСТАЯ ПОЗИЦИЯ:`);
            console.log(`      • Чистый BIO: ${addr.netBio > 0 ? '+' : ''}${addr.netBio.toLocaleString()} BIO`);
            console.log(`      • Чистый WETH: ${addr.netWeth > 0 ? '+' : ''}${addr.netWeth.toFixed(6)} WETH`);
            console.log(`      • Чистый USD: ${addr.netUsd > 0 ? '+' : ''}$${addr.netUsd.toLocaleString()}`);
            
            if (addr.netBio > 0) {
                console.log(`      🔴 Статус: ЧИСТЫЙ ПРОДАВЕЦ (избыток продаж)`);
            } else if (addr.netBio < 0) {
                console.log(`      🟢 Статус: ЧИСТЫЙ ПОКУПАТЕЛЬ (избыток покупок)`);
            } else {
                console.log(`      🟡 Статус: СБАЛАНСИРОВАННАЯ ТОРГОВЛЯ`);
            }
            
            console.log('');
        }

        // Статистика
        const onlySellers = activeAddresses.filter(addr => addr.purchasesCount === 0);
        const onlyBuyers = activeAddresses.filter(addr => addr.salesCount === 0);
        const traders = activeAddresses.filter(addr => addr.salesCount > 0 && addr.purchasesCount > 0);
        const netSellers = activeAddresses.filter(addr => addr.netBio > 0);
        const netBuyers = activeAddresses.filter(addr => addr.netBio < 0);

        console.log('📊 ОБЩАЯ СТАТИСТИКА:');
        console.log(`   • Всего активных адресов: ${activeAddresses.length}`);
        console.log(`   • Только продавцы: ${onlySellers.length}`);
        console.log(`   • Только покупатели: ${onlyBuyers.length}`);
        console.log(`   • Торговцы (и покупки, и продажи): ${traders.length}`);
        console.log(`   • Чистые продавцы: ${netSellers.length}`);
        console.log(`   • Чистые покупатели: ${netBuyers.length}`);

        console.log('');
        console.log('🏆 КАТЕГОРИЗАЦИЯ АДРЕСОВ:');
        console.log('');

        if (onlySellers.length > 0) {
            console.log('🔴 ТОЛЬКО ПРОДАВЦЫ (дампят позиции):');
            onlySellers.forEach(addr => {
                console.log(`   • ${addr.address}: -$${(addr.netUsd * -1).toLocaleString()}`);
            });
            console.log('');
        }

        if (traders.length > 0) {
            console.log('🔄 АКТИВНЫЕ ТОРГОВЦЫ:');
            traders.forEach(addr => {
                const status = addr.netBio > 0 ? 'чистый продавец' : addr.netBio < 0 ? 'чистый покупатель' : 'сбалансирован';
                console.log(`   • ${addr.address}: ${addr.netUsd > 0 ? '+' : ''}$${addr.netUsd.toLocaleString()} (${status})`);
            });
            console.log('');
        }

        if (onlyBuyers.length > 0) {
            console.log('🟢 ТОЛЬКО ПОКУПАТЕЛИ (накапливают):');
            onlyBuyers.forEach(addr => {
                console.log(`   • ${addr.address}: +$${addr.netUsd.toLocaleString()}`);
            });
        }

    } catch (error) {
        console.error('❌ Ошибка анализа:', error);
    }
}

// Запуск анализа
analyzeNetPositions();
