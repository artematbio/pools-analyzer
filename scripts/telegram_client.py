#!/usr/bin/env python3
"""
Telegram diagnostics client (no PTB dependency)
- getMe: https://api.telegram.org/bot{token}/getMe
- sendMessage: https://api.telegram.org/bot{token}/sendMessage

Usage:
  python3 scripts/telegram_client.py getMe
  python3 scripts/telegram_client.py send --chat $TELEGRAM_CHAT_ID --text "Hello from analyzer"
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

TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
BASE = f"https://api.telegram.org/bot{TOKEN}" if TOKEN else None

async def call(method: str, params: dict) -> dict:
  if not BASE:
    raise RuntimeError('TELEGRAM_BOT_TOKEN not set')
  async with httpx.AsyncClient() as client:
    r = await client.post(f"{BASE}/{method}", data=params, timeout=20)
    r.raise_for_status()
    return r.json()

async def main():
  p = argparse.ArgumentParser()
  sub = p.add_subparsers(dest='cmd', required=True)

  sub.add_parser('getMe')
  s = sub.add_parser('send')
  s.add_argument('--chat', default=os.getenv('TELEGRAM_CHAT_ID'))
  s.add_argument('--text', required=True)

  args = p.parse_args()
  try:
    import asyncio
    if args.cmd == 'getMe':
      data = await call('getMe', {})
    else:
      if not args.chat:
        raise RuntimeError('chat id required')
      data = await call('sendMessage', {'chat_id': args.chat, 'text': args.text})
    print(json.dumps(data, indent=2))
  except Exception as e:
    print(f"ERR: {e}")
    sys.exit(1)

if __name__ == '__main__':
  import asyncio
  asyncio.run(main())
