#!/usr/bin/env python3
"""
Helius Solana client
- JSON-RPC endpoint: https://mainnet.helius-rpc.com/?api-key=KEY or HELIUS_RPC_URL from env
- REST balances:     https://api.helius.xyz/v0/addresses/{address}/balances?api-key=KEY

Usage examples:
  python3 scripts/helius_client.py rpc.getBalance --wallet BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD
  python3 scripts/helius_client.py rest.balances --wallet BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD
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

API_KEY = os.getenv('HELIUS_API_KEY')
RPC_ENV_URL = os.getenv('HELIUS_RPC_URL')
RPC_URL = RPC_ENV_URL or (f"https://mainnet.helius-rpc.com/?api-key={API_KEY}" if API_KEY else "https://mainnet.helius-rpc.com")
REST_BASE = "https://api.helius.xyz"

async def rpc(method: str, params: list) -> dict:
  async with httpx.AsyncClient() as client:
    r = await client.post(RPC_URL, json={"jsonrpc":"2.0","id":1,"method":method,"params":params}, timeout=30)
    r.raise_for_status()
    return r.json()

async def rest_balances(wallet: str) -> dict:
  if not API_KEY:
    raise RuntimeError('HELIUS_API_KEY required for REST balances')
  url = f"{REST_BASE}/v0/addresses/{wallet}/balances?api-key={API_KEY}"
  async with httpx.AsyncClient() as client:
    r = await client.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

async def main():
  p = argparse.ArgumentParser()
  sub = p.add_subparsers(dest='cmd', required=True)

  rb = sub.add_parser('rpc.getBalance')
  rb.add_argument('--wallet', required=True)

  rta = sub.add_parser('rpc.getTokenAccountsByOwner')
  rta.add_argument('--wallet', required=True)

  restb = sub.add_parser('rest.balances')
  restb.add_argument('--wallet', required=True)

  args = p.parse_args()
  try:
    import asyncio
    if args.cmd == 'rpc.getBalance':
      data = await rpc('getBalance', [args.wallet, {"commitment":"confirmed"}])
    elif args.cmd == 'rpc.getTokenAccountsByOwner':
      data = await rpc('getTokenAccountsByOwner', [args.wallet, {"programId":"TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"}, {"encoding":"jsonParsed"}])
    else:
      data = await rest_balances(args.wallet)
    print(json.dumps(data, indent=2))
  except Exception as e:
    print(f"ERR: {e}")
    sys.exit(1)

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
