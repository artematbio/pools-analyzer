#!/usr/bin/env python3
"""
Supabase quick diagnostics client
- Checks connection using env SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY
- Prints counts and latest rows of key tables

Usage:
  python3 scripts/supabase_client.py --tables lp_pool_snapshots,lp_position_snapshots,dao_pool_snapshots,token_price_history
"""
import os
import sys
import json
import argparse
from datetime import datetime

try:
  from dotenv import load_dotenv
  load_dotenv()
  load_dotenv('env.example')
except Exception:
  pass

from supabase import create_client

URL = os.getenv('SUPABASE_URL')
KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY') or os.getenv('SUPABASE_ANON_KEY')

def connect():
  if not URL or not KEY:
    raise RuntimeError('Supabase credentials not found')
  return create_client(URL, KEY)

def get_table_overview(c, table: str) -> dict:
  # Count (some clients return count attr, fallback to len)
  res = c.table(table).select('*', count='exact').limit(5).order('created_at', desc=True).execute()
  count_val = getattr(res, 'count', None)
  if count_val is None:
    count_val = len(res.data) if getattr(res, 'data', None) else 0
  latest = res.data if res.data else []
  return {'table': table, 'count': count_val, 'latest': latest}

def main():
  p = argparse.ArgumentParser()
  p.add_argument('--tables', default='lp_pool_snapshots,lp_position_snapshots,dao_pool_snapshots,token_price_history')
  args = p.parse_args()
  try:
    c = connect()
    out = []
    for t in [x.strip() for x in args.tables.split(',') if x.strip()]:
      out.append(get_table_overview(c, t))
    print(json.dumps(out, indent=2, default=str))
  except Exception as e:
    print(f"ERR: {e}")
    sys.exit(1)

if __name__ == '__main__':
  main()
