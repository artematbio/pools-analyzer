#!/usr/bin/env python3
"""
Bitquery GraphQL client
- Uses BITQUERY_API_KEY. Sends both Authorization: Bearer and X-API-KEY for compatibility
- Base URL: https://graphql.bitquery.io

Usage examples:
  python3 scripts/bitquery_client.py run --query '{ ethereum { blocks(limit: 1) { number } } }'
  python3 scripts/bitquery_client.py evm-dex --network ethereum --pool 0x08a5a1e2671839dadc25e2e20f9206fd33c88092
  python3 scripts/bitquery_client.py solana-dex --market DojNuRx9Ncky7BbWRfsLmJg2oYb8qsYD344XufUHAjbJ
"""
import os
import sys
import json
import argparse
import httpx
from typing import Optional, Dict

try:
  from dotenv import load_dotenv
  load_dotenv()
  load_dotenv('env.example')
except Exception:
  pass

BASE = os.getenv('BITQUERY_GRAPHQL_URL', 'https://graphql.bitquery.io')
KEY = os.getenv('BITQUERY_API_KEY')

async def gql(query: str, variables: Optional[Dict] = None) -> dict:
  headers = {'Content-Type': 'application/json'}
  if KEY:
    headers['X-API-KEY'] = KEY
    headers['Authorization'] = f"Bearer {KEY}"
  async with httpx.AsyncClient() as client:
    r = await client.post(BASE, json={'query': query, 'variables': variables or {}}, headers=headers, timeout=40)
    r.raise_for_status()
    data = r.json()
    if 'errors' in data:
      raise RuntimeError(data['errors'])
    return data

EVM_DEX_Q = """
query ($network: EthereumNetwork!, $address: String!, $since: ISO8601DateTime!) {
  ethereum(network: $network) {
    dexTrades(
      smartContractAddress: {is: $address}
      date: {since: $since}
    ) {
      tradeAmount(in: USD)
      side
      count
    }
  }
}
"""

SOLANA_DEX_Q = """
query ($since: ISO8601DateTime!, $market: String!) {
  solana {
    dexTrades(
      date: {since: $since}
      smartContract: {is: $market}
    ) {
      tradeAmount(in: USD)
      side
      count
    }
  }
}
"""

from datetime import datetime, timezone, timedelta

def since_24h() -> str:
  return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

async def main():
  p = argparse.ArgumentParser()
  sub = p.add_subparsers(dest='cmd', required=True)

  r = sub.add_parser('run')
  r.add_argument('--query', required=True)

  e = sub.add_parser('evm-dex')
  e.add_argument('--network', default='ethereum')
  e.add_argument('--pool', required=True)

  s = sub.add_parser('solana-dex')
  s.add_argument('--market', required=True)

  args = p.parse_args()
  try:
    import asyncio
    if args.cmd == 'run':
      data = await gql(args.query)
    elif args.cmd == 'evm-dex':
      data = await gql(EVM_DEX_Q, {'network': args.network, 'address': args.pool.lower(), 'since': since_24h()})
    else:
      data = await gql(SOLANA_DEX_Q, {'market': args.market, 'since': since_24h()})
    print(json.dumps(data, indent=2))
  except Exception as e:
    print(f"ERR: {e}")
    sys.exit(1)

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
