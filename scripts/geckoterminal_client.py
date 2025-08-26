#!/usr/bin/env python3
"""
GeckoTerminal API client (v2)
- Tokens: /api/v2/networks/{network}/tokens/{address}
- Pools:  /api/v2/networks/{network}/pools/{address}
- OHLCV:  /api/v2/networks/{network}/pools/{address}/ohlcv/day?limit=N

Usage examples:
  python3 scripts/geckoterminal_client.py token --network eth --address 0xcb1592591996765ec0efc1f92599a19767ee5ffa
  python3 scripts/geckoterminal_client.py pool --network eth --address 0x08a5a1e2671839dadc25e2e20f9206fd33c88092
  python3 scripts/geckoterminal_client.py ohlcv --network eth --address 0x08a5a1e2671839dadc25e2e20f9206fd33c88092 --limit 8
"""
import os
import sys
import json
import argparse
import httpx

try:
  from dotenv import load_dotenv
  load_dotenv()
  load_dotenv('env.example')
except Exception:
  pass

NETWORK_MAP = {
  'ethereum': 'eth',
  'eth': 'eth',
  'base': 'base',
  'solana': 'solana',
}

BASE_URL = 'https://api.geckoterminal.com/api/v2'

def _net_id(network: str) -> str:
  return NETWORK_MAP.get(network.lower(), network)

async def fetch_json(url: str) -> dict:
  async with httpx.AsyncClient() as client:
    r = await client.get(url, timeout=20)
    r.raise_for_status()
    return r.json()

async def get_token(network: str, address: str) -> dict:
  url = f"{BASE_URL}/networks/{_net_id(network)}/tokens/{address}"
  return await fetch_json(url)

async def get_pool(network: str, address: str) -> dict:
  url = f"{BASE_URL}/networks/{_net_id(network)}/pools/{address}"
  return await fetch_json(url)

async def get_pool_ohlcv(network: str, address: str, limit: int = 8) -> dict:
  url = f"{BASE_URL}/networks/{_net_id(network)}/pools/{address}/ohlcv/day?limit={int(limit)}"
  return await fetch_json(url)

async def main():
  p = argparse.ArgumentParser()
  sub = p.add_subparsers(dest='cmd', required=True)

  t = sub.add_parser('token')
  t.add_argument('--network', required=True)
  t.add_argument('--address', required=True)

  pl = sub.add_parser('pool')
  pl.add_argument('--network', required=True)
  pl.add_argument('--address', required=True)

  o = sub.add_parser('ohlcv')
  o.add_argument('--network', required=True)
  o.add_argument('--address', required=True)
  o.add_argument('--limit', type=int, default=8)

  args = p.parse_args()
  try:
    import asyncio
    if args.cmd == 'token':
      data = await get_token(args.network, args.address)
    elif args.cmd == 'pool':
      data = await get_pool(args.network, args.address)
    else:
      data = await get_pool_ohlcv(args.network, args.address, args.limit)
    print(json.dumps(data, indent=2))
  except Exception as e:
    print(f"ERR: {e}")
    sys.exit(1)

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
