#!/usr/bin/env python3
"""
Real-time large trades monitor (>1% of pool TVL) with Telegram alerts.
- EVM/Base: Bitquery dexTrades facts filtered by pool address, last N seconds
- Solana: Bitquery DEXTrades filtered by smartContract (market address)

For each matched trade:
- Compare trade USD amount against latest TVL from lp_pool_snapshots (Supabase) or GeckoTerminal fallback
- If >1% TVL, send Telegram alert and store in lp_pool_activities

Run as a long-running process.
"""
import os
import sys
import json
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional, Tuple

try:
  from dotenv import load_dotenv
  load_dotenv()
  load_dotenv('env.example')
except Exception:
  pass

import httpx

from database_handler import supabase_handler
from bitquery_client import gql  # reuse headers + auth
from telegram_sender import TelegramSender

TOKENS_POOLS_CONFIG = 'tokens_pools_config.json'
POLL_INTERVAL_SECONDS = int(os.getenv('LARGE_TRADES_POLL_INTERVAL', '30'))
THRESHOLD_PERCENT = float(os.getenv('LARGE_TRADES_THRESHOLD_PERCENT', '1.0'))  # 1% of TVL
LOOKBACK_SECONDS = int(os.getenv('LARGE_TRADES_LOOKBACK_SEC', '60'))

NETWORK_MAP_GT = {
  'ethereum': 'eth',
  'base': 'base',
  'solana': 'solana',
}

async def fetch_geckoterminal_pool_tvl(network: str, pool_address: str) -> Optional[float]:
  try:
    base = 'https://api.geckoterminal.com/api/v2'
    net = NETWORK_MAP_GT.get(network, network)
    url = f"{base}/networks/{net}/pools/{pool_address}"
    async with httpx.AsyncClient() as client:
      r = await client.get(url, timeout=15)
      r.raise_for_status()
      attrs = r.json().get('data', {}).get('attributes', {})
      reserve = attrs.get('reserve_in_usd')
      return float(reserve) if reserve else None
  except Exception:
    return None

async def get_latest_tvl(network: str, pool_address: str) -> Optional[float]:
  # Try Supabase latest lp_pool_snapshots
  try:
    if supabase_handler and supabase_handler.is_connected():
      res = supabase_handler.client.table('lp_pool_snapshots').select('tvl_usd').eq('network', network).eq('pool_address', pool_address).order('created_at', desc=True).limit(1).execute()
      if res.data:
        tvl = res.data[0].get('tvl_usd')
        if tvl is not None:
          return float(tvl)
  except Exception:
    pass
  # Fallback to GeckoTerminal
  return await fetch_geckoterminal_pool_tvl(network, pool_address)

def since_iso(seconds: int) -> str:
  return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()

EVM_TRADES_Q = """
query ($network: EthereumNetwork!, $pool: String!, $since: ISO8601DateTime!) {
  ethereum(network: $network) {
    dexTrades(
      smartContractAddress: {is: $pool}
      date: {since: $since}
    ) {
      tradeAmount
      side
      block { time } 
      transaction { hash }
    }
  }
}
"""

SOL_TRADES_Q = """
query ($market: String!, $since: ISO8601DateTime!) {
  Solana {
    DEXTrades(
      where: { Block: { Time: { since: $since } }, Trade: { Dex: { ProgramAddress: {is: $market} } } }
    ) {
      Trade {
        Amount
      }
      Block { Time }
      Transaction { Signature }
    }
  }
}
"""

async def fetch_recent_trades(network: str, pool_address: str) -> List[Dict[str, Any]]:
  try:
    if network in ('ethereum', 'base'):
      data = await gql(EVM_TRADES_Q, {'network': network, 'pool': pool_address.lower(), 'since': since_iso(LOOKBACK_SECONDS)})
      return data.get('data', {}).get('ethereum', {}).get('dexTrades', [])
    else:
      data = await gql(SOL_TRADES_Q, {'market': pool_address, 'since': since_iso(LOOKBACK_SECONDS)})
      return data.get('data', {}).get('Solana', {}).get('DEXTrades', [])
  except Exception as e:
    print(f"Trade fetch error {network}:{pool_address}: {e}")
    return []

def extract_trade_amount_usd(network: str, trade: Dict[str, Any]) -> Tuple[Optional[float], str]:
  if network in ('ethereum', 'base'):
    amt = trade.get('tradeAmount')
    tx = (trade.get('transaction') or {}).get('hash', '')
    return (float(amt) if amt is not None else None, tx)
  else:
    t = trade.get('Trade') or {}
    amt = t.get('Amount')
    tx = (trade.get('Transaction') or {}).get('Signature', '')
    return (float(amt) if amt is not None else None, tx)

async def alert_and_store(telegram: TelegramSender, payload: Dict[str, Any]):
  # Store in lp_pool_activities
  try:
    if supabase_handler and supabase_handler.is_connected():
      supabase_handler.save_pool_activity({
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'network': payload['network'],
        'pool_address': payload['pool_address'],
        'market_address': payload.get('market_address'),
        'event_type': 'large_trade',
        'amount_usd': payload['amount_usd'],
        'tx_hash': payload.get('tx_hash'),
        'details': payload
      })
  except Exception as e:
    print(f"Store activity error: {e}")
  # Telegram
  try:
    msg = (
      f"🚨 Large trade detected\n"
      f"Pool: {payload['pool_name']} ({payload['network']})\n"
      f"Amount: ${payload['amount_usd']:,.0f} ({payload['percent_of_tvl']:.2f}% TVL)\n"
      f"TVL: ${payload['tvl_usd']:,.0f}\n"
      f"TX: {payload.get('tx_hash','N/A')}\n"
      f"Time: {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
    )
    await telegram.send_message(msg)
  except Exception as e:
    print(f"Telegram error: {e}")

async def monitor_once(telegram: TelegramSender):
  with open(TOKENS_POOLS_CONFIG, 'r') as f:
    cfg = json.load(f)
  pools_cfg = cfg.get('pools', {})

  tasks = []
  for network, pools in pools_cfg.items():
    for p in pools:
      tasks.append(handle_pool(network, p, telegram))
  await asyncio.gather(*tasks)

async def handle_pool(network: str, pool: Dict[str, Any], telegram: TelegramSender):
  pool_address = pool['address']
  pool_name = pool.get('name', pool_address)
  tvl = await get_latest_tvl(network, pool_address)
  if not tvl or tvl <= 0:
    return
  trades = await fetch_recent_trades(network, pool_address)
  threshold = tvl * (THRESHOLD_PERCENT / 100.0)
  for t in trades:
    amount_usd, tx = extract_trade_amount_usd(network, t)
    if amount_usd and amount_usd >= threshold:
      payload = {
        'network': network,
        'pool_address': pool_address,
        'pool_name': pool_name,
        'amount_usd': amount_usd,
        'tvl_usd': tvl,
        'percent_of_tvl': (amount_usd / tvl) * 100.0,
        'tx_hash': tx,
      }
      await alert_and_store(telegram, payload)

async def main():
  print('🚨 Starting large trades monitor...')
  telegram = TelegramSender()
  while True:
    try:
      await monitor_once(telegram)
    except Exception as e:
      print(f"Monitor loop error: {e}")
    await asyncio.sleep(POLL_INTERVAL_SECONDS)

if __name__ == '__main__':
  asyncio.run(main())
