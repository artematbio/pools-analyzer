#!/usr/bin/env python3
"""
CoinGecko client (Pro if COINGECKO_API_KEY set)
- Simple price: /simple/price?ids=...&vs_currencies=usd
- Token by contract: /coins/ethereum/contract/{address}
- Markets: /coins/markets?vs_currency=usd&ids=...

Usage examples:
  python3 scripts/coingecko_client.py simple --ids vitadao,bio-protocol
  python3 scripts/coingecko_client.py contract --platform ethereum --address 0x81f8f0bb1cb2a06649e51913a151f0e7ef6fa321
  python3 scripts/coingecko_client.py markets --ids vitadao,bio-protocol
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

API_KEY = os.getenv('COINGECKO_API_KEY')
BASE = 'https://pro-api.coingecko.com/api/v3' if API_KEY else 'https://api.coingecko.com/api/v3'

async def fetch_json(path: str, params: dict) -> dict:
  headers = {}
  if API_KEY:
    headers['x-cg-pro-api-key'] = API_KEY
  async with httpx.AsyncClient() as client:
    r = await client.get(f"{BASE}{path}", params=params, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()

async def simple_price(ids: str) -> dict:
  return await fetch_json('/simple/price', {'ids': ids, 'vs_currencies': 'usd'})

async def contract(platform: str, address: str) -> dict:
  return await fetch_json(f"/coins/{platform}/contract/{address}", {})

async def markets(ids: str) -> dict:
  return await fetch_json('/coins/markets', {'vs_currency': 'usd', 'ids': ids})

async def main():
  p = argparse.ArgumentParser()
  sub = p.add_subparsers(dest='cmd', required=True)

  s = sub.add_parser('simple')
  s.add_argument('--ids', required=True)

  c = sub.add_parser('contract')
  c.add_argument('--platform', required=True)
  c.add_argument('--address', required=True)

  m = sub.add_parser('markets')
  m.add_argument('--ids', required=True)

  args = p.parse_args()
  try:
    import asyncio
    if args.cmd == 'simple':
      data = await simple_price(args.ids)
    elif args.cmd == 'contract':
      data = await contract(args.platform, args.address)
    else:
      data = await markets(args.ids)
    print(json.dumps(data, indent=2))
  except Exception as e:
    print(f"ERR: {e}")
    sys.exit(1)

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
