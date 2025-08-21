const fs = require('fs');
const ethers = require('ethers');

// ================================
// CONFIGURATION - UPDATE THESE FOR NEW POOLS
// ================================
const POOL_ADDRESS = '0x08a5a1e2671839dadc25e2e20f9206fd33c88092'; // UPDATE: Target Uniswap V3 pool
const TARGET_TOKEN = '0xcb1592591996765ec0efc1f92599a19767ee5ffa'; // UPDATE: Token to analyze (BIO in this example)
const PAIR_TOKEN = '0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2'; // UPDATE: Pair token (usually WETH)
const PAIR_TOKEN_PRICE_USD = 3400; // UPDATE: Price of pair token in USD
const MIN_USD_AMOUNT = 100; // UPDATE: Minimum transaction size to include

// Time period configuration
const HOURS_TO_ANALYZE = 24; // UPDATE: How many hours back to analyze
const BLOCKS_PER_HOUR = 300; // ~12 seconds per block = 300 blocks per hour
const BLOCKS_TO_ANALYZE = HOURS_TO_ANALYZE * BLOCKS_PER_HOUR;

// ================================
// RPC CONFIGURATION
// ================================
const ALCHEMY_KEY = process.env.ALCHEMY_API_KEY || 'YOUR_FALLBACK_KEY'; // UPDATE: Your Alchemy key
const RPC_URL = `https://eth-mainnet.g.alchemy.com/v2/${ALCHEMY_KEY}`;
const provider = new ethers.JsonRpcProvider(RPC_URL);

// ================================
// CONTRACT ABI
// ================================
const SWAP_EVENT_ABI = [
    "event Swap(address indexed sender, address indexed recipient, int256 amount0, int256 amount1, uint160 sqrtPriceX96, uint128 liquidity, int24 tick)"
];

const POOL_ABI = [
    "function token0() view returns (address)",
    "function token1() view returns (address)"
];

// ================================
// MAIN ANALYSIS FUNCTION
// ================================
async function analyzePoolTradingActivity() {
    try {
        console.log('🔍 Pool Trading Activity Analysis');
        console.log('================================');
        console.log(`📊 Pool: ${POOL_ADDRESS}`);
        console.log(`🪙 Target Token: ${TARGET_TOKEN}`);
        console.log(`⏰ Period: Last ${HOURS_TO_ANALYZE} hours`);
        console.log('');

        // Get current block and calculate range
        const currentBlock = await provider.getBlockNumber();
        const fromBlock = currentBlock - BLOCKS_TO_ANALYZE;
        
        console.log(`📈 Blocks: ${fromBlock} → ${currentBlock} (${BLOCKS_TO_ANALYZE} blocks)`);
        console.log('');

        // Get pool token information
        const poolContract = new ethers.Contract(POOL_ADDRESS, POOL_ABI, provider);
        const token0 = await poolContract.token0();
        const token1 = await poolContract.token1();
        
        console.log(`🔍 Pool Tokens:`);
        console.log(`   Token0: ${token0}`);
        console.log(`   Token1: ${token1}`);
        
        // Determine target token position
        const targetIsToken0 = token0.toLowerCase() === TARGET_TOKEN.toLowerCase();
        console.log(`   Target Token Position: ${targetIsToken0 ? 'token0' : 'token1'}`);
        console.log('');

        // Get Swap events
        console.log(`🔄 Fetching Swap events...`);
        const filter = {
            address: POOL_ADDRESS,
            topics: [ethers.id("Swap(address,address,int256,int256,uint160,uint128,int24)")],
            fromBlock: fromBlock,
            toBlock: "latest"
        };

        const logs = await provider.getLogs(filter);
        console.log(`📦 Found ${logs.length} swap events`);
        console.log('');

        // Parse events
        const iface = new ethers.Interface(SWAP_EVENT_ABI);
        
        // Tracking variables
        let totalTargetSold = 0;
        let totalTargetBought = 0;
        let totalPairFromSales = 0;
        let totalPairToPurchases = 0;
        let salesCount = 0;
        let purchasesCount = 0;
        
        const addressActivity = {};
        
        console.log(`🔍 Analyzing ${logs.length} transactions...`);

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

                // Determine swap direction
                let targetAmount, pairAmount, isTargetSale;
                
                if (targetIsToken0) {
                    targetAmount = Math.abs(Number(ethers.formatEther(amount0)));
                    pairAmount = Math.abs(Number(ethers.formatEther(amount1)));
                    isTargetSale = amount0 > 0n; // Target token enters pool = SALE
                } else {
                    targetAmount = Math.abs(Number(ethers.formatEther(amount1)));
                    pairAmount = Math.abs(Number(ethers.formatEther(amount0)));
                    isTargetSale = amount1 > 0n; // Target token enters pool = SALE
                }

                // Calculate USD value
                const usdValue = pairAmount * PAIR_TOKEN_PRICE_USD;
                
                // Filter by minimum amount
                if (usdValue >= MIN_USD_AMOUNT) {
                    // Track global statistics
                    if (isTargetSale) {
                        totalTargetSold += targetAmount;
                        totalPairFromSales += pairAmount;
                        salesCount++;
                    } else {
                        totalTargetBought += targetAmount;
                        totalPairToPurchases += pairAmount;
                        purchasesCount++;
                    }

                    // Track per-address activity
                    if (!addressActivity[sender]) {
                        addressActivity[sender] = {
                            address: sender,
                            targetSold: 0,
                            targetBought: 0,
                            pairFromSales: 0,
                            pairToPurchases: 0,
                            salesCount: 0,
                            purchasesCount: 0
                        };
                    }

                    if (isTargetSale) {
                        addressActivity[sender].targetSold += targetAmount;
                        addressActivity[sender].pairFromSales += pairAmount;
                        addressActivity[sender].salesCount++;
                    } else {
                        addressActivity[sender].targetBought += targetAmount;
                        addressActivity[sender].pairToPurchases += pairAmount;
                        addressActivity[sender].purchasesCount++;
                    }
                }

                // Progress indicator
                if (i % 100 === 0 && i > 0) {
                    console.log(`   📊 Processed ${i}/${logs.length} events... (Sales: ${salesCount}, Buys: ${purchasesCount})`);
                }

            } catch (error) {
                console.log(`⚠️ Error processing log ${i}: ${error.message}`);
            }
        }

        // Calculate results
        console.log('');
        console.log('🎯 ANALYSIS RESULTS');
        console.log('==================');
        console.log('');
        
        const totalSalesUSD = totalPairFromSales * PAIR_TOKEN_PRICE_USD;
        const totalPurchasesUSD = totalPairToPurchases * PAIR_TOKEN_PRICE_USD;
        const netFlow = totalTargetSold - totalTargetBought;
        const netUSD = totalSalesUSD - totalPurchasesUSD;

        console.log('📉 SALES:');
        console.log(`   • Transactions: ${salesCount.toLocaleString()}`);
        console.log(`   • Target tokens sold: ${totalTargetSold.toLocaleString()}`);
        console.log(`   • USD value: $${totalSalesUSD.toLocaleString()}`);
        console.log('');
        
        console.log('📈 PURCHASES:');
        console.log(`   • Transactions: ${purchasesCount.toLocaleString()}`);
        console.log(`   • Target tokens bought: ${totalTargetBought.toLocaleString()}`);
        console.log(`   • USD value: $${totalPurchasesUSD.toLocaleString()}`);
        console.log('');
        
        console.log('⚖️ NET PRESSURE:');
        console.log(`   • Net token flow: ${netFlow > 0 ? '+' : ''}${netFlow.toLocaleString()}`);
        console.log(`   • Net USD flow: ${netUSD > 0 ? '+' : ''}$${netUSD.toLocaleString()}`);
        
        if (netFlow > 0) {
            console.log(`   🔴 Result: SELL PRESSURE (${((netFlow / totalTargetBought) * 100).toFixed(1)}% excess)`);
        } else if (netFlow < 0) {
            console.log(`   🟢 Result: BUY PRESSURE (${((-netFlow / totalTargetSold) * 100).toFixed(1)}% excess)`);
        } else {
            console.log(`   🟡 Result: BALANCED TRADING`);
        }

        // Top traders analysis
        console.log('');
        console.log('🏆 TOP TRADERS (by USD volume):');
        console.log('');

        const sortedTraders = Object.values(addressActivity)
            .map(trader => ({
                ...trader,
                totalUSD: (trader.pairFromSales + trader.pairToPurchases) * PAIR_TOKEN_PRICE_USD,
                netTarget: trader.targetSold - trader.targetBought,
                netUSD: (trader.pairFromSales - trader.pairToPurchases) * PAIR_TOKEN_PRICE_USD
            }))
            .sort((a, b) => b.totalUSD - a.totalUSD)
            .slice(0, 10);

        sortedTraders.forEach((trader, index) => {
            const type = trader.salesCount > 0 && trader.purchasesCount > 0 ? 'TRADER' : 
                        trader.salesCount > 0 ? 'SELLER' : 'BUYER';
            const netStatus = trader.netTarget > 100 ? 'Net Seller' :
                             trader.netTarget < -100 ? 'Net Buyer' : 'Balanced';
            
            console.log(`${index + 1}. ${trader.address}`);
            console.log(`   Type: ${type} | Status: ${netStatus}`);
            console.log(`   Total Volume: $${trader.totalUSD.toLocaleString()}`);
            console.log(`   Sales: ${trader.salesCount} txs, $${(trader.pairFromSales * PAIR_TOKEN_PRICE_USD).toLocaleString()}`);
            console.log(`   Buys: ${trader.purchasesCount} txs, $${(trader.pairToPurchases * PAIR_TOKEN_PRICE_USD).toLocaleString()}`);
            console.log(`   Net: ${trader.netUSD > 0 ? '+' : ''}$${trader.netUSD.toLocaleString()}`);
            console.log('');
        });

        // Save detailed CSV
        const csvFilename = `pool_analysis_${Date.now()}.csv`;
        const csvLines = [
            'Address,Type,Total_Transactions,Sales_Count,Buys_Count,Target_Sold,Target_Bought,Net_Target,USD_Sales,USD_Buys,Net_USD,Status'
        ];
        
        Object.values(addressActivity).forEach(trader => {
            const type = trader.salesCount > 0 && trader.purchasesCount > 0 ? 'TRADER' : 
                        trader.salesCount > 0 ? 'SELLER' : 'BUYER';
            const netTarget = trader.targetSold - trader.targetBought;
            const netUSD = (trader.pairFromSales - trader.pairToPurchases) * PAIR_TOKEN_PRICE_USD;
            const status = netTarget > 100 ? 'Net_Seller' :
                          netTarget < -100 ? 'Net_Buyer' : 'Balanced';
            
            csvLines.push([
                trader.address,
                type,
                trader.salesCount + trader.purchasesCount,
                trader.salesCount,
                trader.purchasesCount,
                trader.targetSold.toFixed(6),
                trader.targetBought.toFixed(6),
                netTarget.toFixed(6),
                (trader.pairFromSales * PAIR_TOKEN_PRICE_USD).toFixed(2),
                (trader.pairToPurchases * PAIR_TOKEN_PRICE_USD).toFixed(2),
                netUSD.toFixed(2),
                status
            ].join(','));
        });

        fs.writeFileSync(csvFilename, csvLines.join('\n'));
        console.log(`💾 Detailed report saved: ${csvFilename}`);

    } catch (error) {
        console.error('❌ Analysis error:', error);
    }
}

// Run analysis
analyzePoolTradingActivity();
