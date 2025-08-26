#!/usr/bin/env python3
"""
Collect 24h volumes per pool daily and store in Supabase.
- EVM/Base: Bitquery dexTrades aggregates by pool address (since 24h)
- Solana: GeckoTerminal pool endpoint volume_24h_usd as fallback per pool

Saves into lp_pool_volumes via database_handler.supabase_handler.save_pool_volume_data
with fields: date (YYYY-MM-DD), pool_address, network, pool_name, volume_24h_usd,
             buy_24h_usd, sell_24h_usd, trades_24h, source
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

import httpx

from database_handler import supabase_handler
from bitquery_adapter import BitqueryAdapter

TOKENS_POOLS_CONFIG = 'tokens_pools_config.json'

NETWORK_MAP_GT = {
  'ethereum': 'eth',
  'base': 'base',
  'solana': 'solana',
}

async def fetch_geckoterminal_pool(network: str, pool_address: str) -> Dict[str, Any]:
  base = 'https://api.geckoterminal.com/api/v2'
  net = NETWORK_MAP_GT.get(network, network)
  url = f"{base}/networks/{net}/pools/{pool_address}"
  async with httpx.AsyncClient() as client:
    r = await client.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

async def collect_for_pool(adapter: BitqueryAdapter, network: str, pool: Dict[str, Any]) -> Dict[str, Any]:
  pool_address = pool['address']
  pool_name = pool.get('name', pool_address)
  result = {
    'network': network,
    'pool_address': pool_address,
    'pool_name': pool_name,
    'volume_24h_usd': None,
    'buy_24h_usd': None,
    'sell_24h_usd': None,
    'trades_24h': None,
    'source': None,
  }

  if network in ('ethereum', 'base'):
    agg = await adapter.get_evm_pool_24h_aggregates(network, pool_address)
    result.update({
      'volume_24h_usd': agg.get('volume_24h_usd'),
      'buy_24h_usd': agg.get('buy_24h_usd'),
      'sell_24h_usd': agg.get('sell_24h_usd'),
      'trades_24h': agg.get('trades_24h'),
      'source': 'bitquery',
    })
  else:
    # Solana fallback to GeckoTerminal (per-pool volume)
    try:
      data = await fetch_geckoterminal_pool(network, pool_address)
      attrs = data.get('data', {}).get('attributes', {})
      vol24 = 0.0
      try:
        vol24 = float((attrs.get('volume_usd') or {}).get('h24') or 0)
      except Exception:
        vol24 = 0.0
      result.update({
        'volume_24h_usd': round(vol24, 2) if vol24 else None,
        'buy_24h_usd': None,
        'sell_24h_usd': None,
        'trades_24h': None,
        'source': 'geckoterminal',
      })
    except Exception as e:
      print(f"Solana GT error for {pool_name}: {e}")

  return result

async def main():
  print('📈 Collecting 24h volumes per pool...')
  if not supabase_handler or not supabase_handler.is_connected():
    print('❌ Supabase not connected')
    sys.exit(1)

  with open(TOKENS_POOLS_CONFIG, 'r') as f:
    cfg = json.load(f)
  pools_cfg = cfg.get('pools', {})

  adapter = BitqueryAdapter()
  today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

  import asyncio
  tasks = []
  for network, pools in pools_cfg.items():
    for pool in pools:
      tasks.append(collect_for_pool(adapter, network, pool))

  results: List[Dict[str, Any]] = await asyncio.gather(*tasks)

  saved = 0
  for r in results:
    payload = {
      'date': today,
      'network': r['network'],
      'pool_address': r['pool_address'],
      'pool_name': r['pool_name'],
      'volume_24h_usd': r['volume_24h_usd'],
      'buy_24h_usd': r['buy_24h_usd'],
      'sell_24h_usd': r['sell_24h_usd'],
      'trades_24h': r['trades_24h'],
      'source': r['source'] or 'unknown'
    }
    if supabase_handler.save_pool_volume_data(payload):
      saved += 1

  print(f'✅ Saved {saved}/{len(results)} daily volume rows')

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
