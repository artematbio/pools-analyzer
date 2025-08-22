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

async function createDetailedTradingCSV() {
    try {
        console.log('📊 Создание детального CSV отчета по торговле топ адресов');
        console.log('=========================================================');
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
                purchasesCount: 0
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
                }

                if (i % 100 === 0 && i > 0) {
                    console.log(`   📊 Обработано ${i}/${logs.length} событий...`);
                }

            } catch (error) {
                console.log(`⚠️ Ошибка обработки лога ${i}: ${error.message}`);
            }
        }

        console.log('');
        console.log('📋 Формирование CSV отчета...');

        // Подготавливаем данные для CSV
        const csvData = [];

        // Заголовки CSV
        const headers = [
            'Address',
            'Total_Transactions',
            'Sales_Count',
            'Purchases_Count',
            'BIO_Sold',
            'BIO_Bought',
            'WETH_From_Sales',
            'WETH_To_Purchases', 
            'USD_From_Sales',
            'USD_To_Purchases',
            'Net_BIO_Position',
            'Net_WETH_Position',
            'Net_USD_Position',
            'Trading_Type',
            'Net_Position_Status',
            'Average_Sale_Size_BIO',
            'Average_Purchase_Size_BIO',
            'Sales_USD_per_Transaction',
            'Purchases_USD_per_Transaction'
        ];

        csvData.push(headers.join(','));

        // Обрабатываем каждый адрес
        const processedAddresses = Object.values(addressData)
            .filter(data => data.salesCount > 0 || data.purchasesCount > 0)
            .map(data => {
                const usdFromSales = data.totalWethFromSales * WETH_PRICE_USD;
                const usdToPurchases = data.totalWethFromPurchases * WETH_PRICE_USD;
                const netBio = data.totalBioSold - data.totalBioBought;
                const netWeth = data.totalWethFromSales - data.totalWethFromPurchases;
                const netUsd = netWeth * WETH_PRICE_USD;
                const totalTransactions = data.salesCount + data.purchasesCount;

                // Определяем тип торговли
                let tradingType;
                if (data.salesCount > 0 && data.purchasesCount > 0) {
                    tradingType = 'Active_Trader';
                } else if (data.salesCount > 0 && data.purchasesCount === 0) {
                    tradingType = 'Only_Seller';
                } else if (data.salesCount === 0 && data.purchasesCount > 0) {
                    tradingType = 'Only_Buyer';
                } else {
                    tradingType = 'No_Activity';
                }

                // Определяем статус чистой позиции
                let netStatus;
                if (netBio > 1000) {
                    netStatus = 'Net_Seller';
                } else if (netBio < -1000) {
                    netStatus = 'Net_Buyer';
                } else {
                    netStatus = 'Balanced';
                }

                // Рассчитываем средние размеры
                const avgSaleSize = data.salesCount > 0 ? data.totalBioSold / data.salesCount : 0;
                const avgPurchaseSize = data.purchasesCount > 0 ? data.totalBioBought / data.purchasesCount : 0;
                const salesUsdPerTx = data.salesCount > 0 ? usdFromSales / data.salesCount : 0;
                const purchasesUsdPerTx = data.purchasesCount > 0 ? usdToPurchases / data.purchasesCount : 0;

                return [
                    data.address,
                    totalTransactions,
                    data.salesCount,
                    data.purchasesCount,
                    data.totalBioSold.toFixed(6),
                    data.totalBioBought.toFixed(6),
                    data.totalWethFromSales.toFixed(6),
                    data.totalWethFromPurchases.toFixed(6),
                    usdFromSales.toFixed(2),
                    usdToPurchases.toFixed(2),
                    netBio.toFixed(6),
                    netWeth.toFixed(6),
                    netUsd.toFixed(2),
                    tradingType,
                    netStatus,
                    avgSaleSize.toFixed(6),
                    avgPurchaseSize.toFixed(6),
                    salesUsdPerTx.toFixed(2),
                    purchasesUsdPerTx.toFixed(2)
                ];
            })
            .sort((a, b) => Math.abs(parseFloat(b[12])) - Math.abs(parseFloat(a[12]))); // Сортировка по абсолютному значению чистой USD позиции

        // Добавляем данные в CSV
        processedAddresses.forEach(row => {
            csvData.push(row.join(','));
        });

        // Сохраняем CSV файл
        const csvContent = csvData.join('\n');
        const csvFilename = `detailed_trading_analysis_24h_${Date.now()}.csv`;
        fs.writeFileSync(csvFilename, csvContent);

        console.log('');
        console.log('✅ CSV отчет создан успешно!');
        console.log(`📁 Файл: ${csvFilename}`);
        console.log(`📊 Записей: ${processedAddresses.length}`);
        console.log('');

        // Показываем краткую статистику
        const onlySellers = processedAddresses.filter(row => row[13] === 'Only_Seller');
        const onlyBuyers = processedAddresses.filter(row => row[13] === 'Only_Buyer');
        const activeTraders = processedAddresses.filter(row => row[13] === 'Active_Trader');
        const netSellers = processedAddresses.filter(row => row[14] === 'Net_Seller');
        const netBuyers = processedAddresses.filter(row => row[14] === 'Net_Buyer');

        console.log('📈 КРАТКАЯ СТАТИСТИКА CSV:');
        console.log(`   • Всего адресов с активностью: ${processedAddresses.length}`);
        console.log(`   • Только продавцы: ${onlySellers.length}`);
        console.log(`   • Только покупатели: ${onlyBuyers.length}`);
        console.log(`   • Активные торговцы: ${activeTraders.length}`);
        console.log(`   • Чистые продавцы: ${netSellers.length}`);
        console.log(`   • Чистые покупатели: ${netBuyers.length}`);
        console.log('');

        console.log('📋 CSV КОЛОНКИ:');
        console.log('   1. Address - адрес кошелька/контракта');
        console.log('   2. Total_Transactions - общее количество транзакций');
        console.log('   3. Sales_Count - количество продаж');
        console.log('   4. Purchases_Count - количество покупок');
        console.log('   5. BIO_Sold - общий объем проданного BIO');
        console.log('   6. BIO_Bought - общий объем купленного BIO');
        console.log('   7. WETH_From_Sales - WETH получено от продаж');
        console.log('   8. WETH_To_Purchases - WETH потрачено на покупки');
        console.log('   9. USD_From_Sales - USD стоимость продаж');
        console.log('   10. USD_To_Purchases - USD стоимость покупок');
        console.log('   11. Net_BIO_Position - чистая позиция в BIO');
        console.log('   12. Net_WETH_Position - чистая позиция в WETH');
        console.log('   13. Net_USD_Position - чистая позиция в USD');
        console.log('   14. Trading_Type - тип торговли (Only_Seller/Only_Buyer/Active_Trader)');
        console.log('   15. Net_Position_Status - статус чистой позиции (Net_Seller/Net_Buyer/Balanced)');
        console.log('   16. Average_Sale_Size_BIO - средний размер продажи');
        console.log('   17. Average_Purchase_Size_BIO - средний размер покупки');
        console.log('   18. Sales_USD_per_Transaction - USD продаж на транзакцию');
        console.log('   19. Purchases_USD_per_Transaction - USD покупок на транзакцию');

    } catch (error) {
        console.error('❌ Ошибка создания CSV:', error);
    }
}

// Запуск создания CSV
createDetailedTradingCSV();
