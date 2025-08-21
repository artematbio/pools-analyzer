# Trading Analysis Scripts for Uniswap V3 Pools

## Overview
These Node.js scripts analyze trading activity in Uniswap V3 pools to determine sell pressure, identify top traders, and classify addresses by trading behavior.

## Scripts Description

### 1. `get_pool_transactions.js`
Analyzes token sales in a specific pool and exports to CSV.
- **Input**: Pool address, token address, time period
- **Output**: CSV with all sales > threshold amount
- **Use case**: Finding all large sales of a token

### 2. `sell_pressure_analysis.js` 
Full sell pressure analysis for a custom time period.
- **Input**: Pool address, start block, end block
- **Output**: Buy vs sell pressure metrics
- **Use case**: Understanding market sentiment over time

### 3. `sell_pressure_24h.js`
24-hour sell pressure analysis (quick version).
- **Input**: Pool address (last 24 hours automatic)
- **Output**: Recent buy vs sell pressure
- **Use case**: Current market conditions

### 4. `top_sellers_24h.js`
Identifies top sellers and their trading volumes.
- **Input**: Pool address (last 24 hours)
- **Output**: Ranked list of sellers with volumes
- **Use case**: Finding who is dumping tokens

### 5. `net_position_analysis.js`
Analyzes net positions (buys - sells) for specific addresses.
- **Input**: Pool address, list of addresses to analyze
- **Output**: Net trading positions for each address
- **Use case**: Understanding if "sellers" are actually net buyers

### 6. `create_detailed_trading_csv.js`
Creates comprehensive CSV report with trader classification.
- **Input**: Pool address, list of addresses
- **Output**: 19-column CSV with full trading analysis
- **Use case**: Complete trading behavior analysis

## Core Concepts

### Swap Direction Logic
```javascript
// In Uniswap V3, determine if token is being bought or sold
const tokenIsToken0 = token0.toLowerCase() === TARGET_TOKEN.toLowerCase();
const isTokenSale = tokenIsToken0 ? (amount0 > 0n) : (amount1 > 0n);

// Token enters pool (positive amount) = SALE
// Token exits pool (negative amount) = PURCHASE
```

### Trader Classification
- **Only_Seller**: Addresses that only sell, never buy
- **Only_Buyer**: Addresses that only buy, never sell  
- **Active_Trader**: Addresses with both buys and sells

### Position Status
- **Net_Seller**: More sells than buys (positive net position)
- **Net_Buyer**: More buys than sells (negative net position)
- **Balanced**: Roughly equal buys and sells

### Sell Pressure Calculation
```
Sell Pressure = Total Sell Volume - Total Buy Volume
Positive = More selling pressure
Negative = More buying pressure
```

## Configuration

### Required Constants
```javascript
const POOL_ADDRESS = '0x...'; // Uniswap V3 pool address
const TARGET_TOKEN = '0x...'; // Token to analyze
const WETH_TOKEN = '0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2';
const WETH_PRICE_USD = 3400; // For USD conversion
const ALCHEMY_KEY = process.env.ALCHEMY_API_KEY || 'fallback_key';
```

### Time Periods
```javascript
const BLOCKS_24H = 7200; // ~24 hours (12 sec/block)
const BLOCKS_WEEK = 50400; // ~1 week
const currentBlock = await provider.getBlockNumber();
const fromBlock = currentBlock - BLOCKS_24H;
```

## Usage Examples

### Analyze New Pool
1. Update `POOL_ADDRESS` and `TARGET_TOKEN` constants
2. Run `sell_pressure_24h.js` for quick overview
3. If interesting, run `top_sellers_24h.js` for details
4. Run `net_position_analysis.js` to check if sellers are actually buyers
5. Generate full CSV with `create_detailed_trading_csv.js`

### Custom Time Period
1. Modify `fromBlock` calculation in any script
2. For specific dates, calculate block numbers manually
3. Use `sell_pressure_analysis.js` for custom periods

### Different Networks
1. Update RPC URL for different chains
2. Adjust WETH address for network (WMATIC for Polygon, etc.)
3. Update price constants accordingly

## CSV Output Columns

The detailed CSV includes 19 columns:
1. Address
2. Total_Transactions  
3. Sales_Count
4. Purchases_Count
5. BIO_Sold
6. BIO_Bought
7. WETH_From_Sales
8. WETH_To_Purchases
9. USD_From_Sales
10. USD_To_Purchases
11. Net_BIO_Position
12. Net_WETH_Position  
13. Net_USD_Position
14. Trading_Type
15. Net_Position_Status
16. Average_Sale_Size_BIO
17. Average_Purchase_Size_BIO
18. Sales_USD_per_Transaction
19. Purchases_USD_per_Transaction

## Dependencies
- ethers.js v6 (blockchain interaction)
- fs (file system, built-in)
- Node.js environment variables for API keys

## Error Handling
- RPC failures: Automatic retry with fallback keys
- Invalid transactions: Skip and continue processing
- Empty results: Graceful handling with appropriate messages

## Performance Notes
- Large block ranges (>20,000) may be slow
- Use smaller ranges for testing
- Consider batching for very large analyses
- Progress indicators every 100-500 events
