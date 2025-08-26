#!/usr/bin/env python3
"""
Weekly top traders per pool (focus on token1 side) saved to Supabase as snapshot events.
- EVM/Base: use dexTrades grouped by trader address with sum USD amounts, filtered by token1 (quote/base logic)
- Solana: use DEXTradeByTokens grouped by Trade.Account.Owner (where available) or Account.Address

Stores a JSON payload per pool in lp_pool_activities with event_type 'top_traders_weekly'.
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List

try:
  from dotenv import load_dotenv
  load_dotenv()
  load_dotenv('env.example')
except Exception:
  pass

from database_handler import supabase_handler
from bitquery_client import gql

TOKENS_POOLS_CONFIG = 'tokens_pools_config.json'

DAYS = int(os.getenv('TOP_TRADERS_DAYS', '7'))
LIMIT = int(os.getenv('TOP_TRADERS_LIMIT', '50'))

EVM_TOP_Q = """
query ($network: EthereumNetwork!, $pool: String!, $since: ISO8601DateTime!) {
  ethereum(network: $network) {
    dexTrades(
      smartContractAddress: {is: $pool}
      date: {since: $since}
    ) {
      trader: taker { address }
      buy_usd:  sum(of: Trade_Amount, in: USD, if: {side: {is: buy}})
      sell_usd: sum(of: Trade_Amount, in: USD, if: {side: {is: sell}})
      volume_usd: sum(of: Trade_Amount, in: USD)
    }
  }
}
"""

SOL_TOP_Q = """
query ($market: String!, $since: ISO8601DateTime!) {
  Solana {
    DEXTrades(
      where: { Block: { Time: { since: $since } }, Trade: { Dex: { ProgramAddress: {is: $market} } } }
    ) {
      Trade {
        Account { Owner }
      }
      buy_usd: sum(of: Trade_Side_AmountInUSD, if: {Trade: {Side: {Type: {is: buy}}}})
      sell_usd: sum(of: Trade_Side_AmountInUSD, if: {Trade: {Side: {Type: {is: sell}}}})
      volume_usd: sum(of: Trade_Side_AmountInUSD)
    }
  }
}
"""

def since_days_iso(days: int) -> str:
  return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

def normalize_traders_evm(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out = {}
  for r in rows:
    addr = ((r.get('trader') or {}).get('address')) or 'unknown'
    obj = out.setdefault(addr, {'address': addr, 'buy_usd': 0.0, 'sell_usd': 0.0, 'volume_usd': 0.0})
    obj['buy_usd'] += float(r.get('buy_usd') or 0)
    obj['sell_usd'] += float(r.get('sell_usd') or 0)
    obj['volume_usd'] += float(r.get('volume_usd') or 0)
  arr = list(out.values())
  arr.sort(key=lambda x: x['volume_usd'], reverse=True)
  return arr[:LIMIT]

def normalize_traders_sol(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
  out = {}
  for r in rows:
    owner = (((r.get('Trade') or {}).get('Account') or {}).get('Owner')) or 'unknown'
    obj = out.setdefault(owner, {'address': owner, 'buy_usd': 0.0, 'sell_usd': 0.0, 'volume_usd': 0.0})
    obj['buy_usd'] += float(r.get('buy_usd') or 0)
    obj['sell_usd'] += float(r.get('sell_usd') or 0)
    obj['volume_usd'] += float(r.get('volume_usd') or 0)
  arr = list(out.values())
  arr.sort(key=lambda x: x['volume_usd'], reverse=True)
  return arr[:LIMIT]

async def main():
  print('📊 Weekly top traders snapshot...')
  if not supabase_handler or not supabase_handler.is_connected():
    print('❌ Supabase not connected')
    sys.exit(1)

  with open(TOKENS_POOLS_CONFIG, 'r') as f:
    cfg = json.load(f)
  pools_cfg = cfg.get('pools', {})

  since = since_days_iso(DAYS)

  # For each pool, compute top traders
  saved = 0
  for network, pools in pools_cfg.items():
    for p in pools:
      pool_address = p['address']
      pool_name = p.get('name', pool_address)
      try:
        if network in ('ethereum', 'base'):
          data = await gql(EVM_TOP_Q, {'network': network, 'pool': pool_address.lower(), 'since': since})
          rows = data.get('data', {}).get('ethereum', {}).get('dexTrades', [])
          top = normalize_traders_evm(rows)
        else:
          data = await gql(SOL_TOP_Q, {'market': pool_address, 'since': since})
          rows = data.get('data', {}).get('Solana', {}).get('DEXTrades', [])
          top = normalize_traders_sol(rows)

        payload = {
          'timestamp': datetime.now(timezone.utc).isoformat(),
          'network': network,
          'pool_address': pool_address,
          'event_type': 'top_traders_weekly',
          'details': {
            'pool_name': pool_name,
            'since': since,
            'top': top
          }
        }
        supabase_handler.save_pool_activity(payload)
        saved += 1
      except Exception as e:
        print(f"Top traders error {network}:{pool_address}: {e}")

  print(f'✅ Saved top traders snapshots for {saved} pools')

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
