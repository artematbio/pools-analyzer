#!/usr/bin/env python3
"""
Bitquery Adapter
Мини-адаптер для запросов к Bitquery GraphQL API с кэшированием и бэкоффом.
Поддерживает:
- EVM: dexTrades по адресу пула (Uniswap V3)
- Solana: агрегаты по MarketAddress (DEXTradeByTokens)

Возвращает агрегаты за последние 24 часа:
- trades_24h, volume_24h_usd, buy_24h_usd, sell_24h_usd, net_flow_24h_usd
- market_address/dex_protocol (если применимо)
- источники price_source/volume_source = 'bitquery'

Зависимости: httpx, python-dotenv
Env: BITQUERY_API_KEY
"""

import os
import time
import json
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone, timedelta

import httpx
from dotenv import load_dotenv

load_dotenv()

BITQUERY_GRAPHQL_URL = os.getenv("BITQUERY_GRAPHQL_URL", "https://graphql.bitquery.io")
BITQUERY_API_KEY = os.getenv("BITQUERY_API_KEY")

@dataclass
class CacheEntry:
    value: Dict[str, Any]
    expire_at: float

class TTLCache:
    def __init__(self, default_ttl_seconds: int = 600):
        self._data: Dict[str, CacheEntry] = {}
        self._ttl = default_ttl_seconds

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        entry = self._data.get(key)
        if not entry:
            return None
        if time.time() > entry.expire_at:
            self._data.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Dict[str, Any], ttl_seconds: Optional[int] = None) -> None:
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        self._data[key] = CacheEntry(value=value, expire_at=time.time() + ttl)

class BitqueryAdapter:
    def __init__(self, api_key: Optional[str] = None, cache_ttl_seconds: int = 600):
        self.api_key = api_key or BITQUERY_API_KEY
        self.base_url = BITQUERY_GRAPHQL_URL
        self.cache = TTLCache(default_ttl_seconds=cache_ttl_seconds)
        if not self.api_key:
            print("⚠️ BITQUERY_API_KEY не задан. Адаптер будет работать только с фолбэками.")

    async def _post(self, client: httpx.AsyncClient, query: str, variables: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            # Bitquery обычно использует X-API-KEY
            headers["X-API-KEY"] = self.api_key
        payload = {"query": query}
        if variables:
            payload["variables"] = variables

        # Экспоненциальный бэкофф
        max_attempts = 5
        delay = 1.0
        last_error: Optional[Exception] = None
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.post(self.base_url, headers=headers, json=payload, timeout=30)
                if resp.status_code == 200:
                    data = resp.json()
                    if "errors" in data:
                        raise RuntimeError(f"Bitquery errors: {data['errors']}")
                    return data
                elif resp.status_code in (429, 502, 503):
                    # Rate limit / transient
                    print(f"🔄 Bitquery {resp.status_code}, попытка {attempt}/{max_attempts}, задержка {delay:.1f}s")
                    await client.aclose()
                    time.sleep(delay)
                    delay = min(delay * 1.8, 30.0)
                    continue
                else:
                    raise RuntimeError(f"HTTP {resp.status_code}: {resp.text[:180]}")
            except Exception as e:
                last_error = e
                print(f"⚠️ Bitquery запрос ошибка (попытка {attempt}): {e}")
                time.sleep(delay)
                delay = min(delay * 1.8, 30.0)
        raise RuntimeError(f"Bitquery запрос окончательно неуспешен: {last_error}")

    @staticmethod
    def _since_24h_iso() -> str:
        return (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

    async def get_evm_pool_24h_aggregates(self, network: str, pool_address: str) -> Dict[str, Any]:
        """
        Получить агрегаты для EVM пула (Uniswap V3) за 24 часа по адресу пула.
        network: 'ethereum' | 'base' | 'polygon' ... (по Bitquery - уточняется)
        Возвращает словарь с ключами из lp_pool_snapshots расширения.
        """
        key = f"evm:{network}:{pool_address.lower()}"
        cached = self.cache.get(key)
        if cached:
            return cached

        # Простой GraphQL запрос к dexTrades, суммируем buy/sell USD и количество сделок
        # Примечание: точное поле фильтра для пула может отличаться. Часто используют smartContractAddress
        # Вариант с time interval aggregation для получения 24h сумм
        query = """
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
        variables = {
            "network": network,
            "address": pool_address.lower(),
            "since": self._since_24h_iso()
        }

        volume_usd = 0.0
        buy_usd = 0.0
        sell_usd = 0.0
        trades = 0

        try:
            async with httpx.AsyncClient() as client:
                data = await self._post(client, query, variables)
            trades_list = data.get("data", {}).get("ethereum", {}).get("dexTrades", [])
            for t in trades_list:
                amt = float(t.get("tradeAmount", 0) or 0)
                side = (t.get("side") or "").upper()
                cnt = int(t.get("count", 1) or 1)
                volume_usd += amt
                trades += max(cnt, 1)
                if side == "BUY":
                    buy_usd += amt
                elif side == "SELL":
                    sell_usd += amt
        except Exception as e:
            print(f"⚠️ Bitquery EVM aggregates error for {network}:{pool_address}: {e}")

        result = {
            "trades_24h": trades or None,
            "volume_24h_usd": round(volume_usd, 2) if volume_usd else None,
            "buy_24h_usd": round(buy_usd, 2) if buy_usd else None,
            "sell_24h_usd": round(sell_usd, 2) if sell_usd else None,
            "net_flow_24h_usd": round((buy_usd - sell_usd), 2) if (buy_usd or sell_usd) else None,
            "price_source": "bitquery",
            "volume_source": "bitquery",
            "market_address": None,
            "dex_protocol": "uniswap_v3" if network in ("ethereum", "base") else None,
        }
        self.cache.set(key, result)
        return result

    async def get_solana_market_24h_aggregates(self, market_address: str) -> Dict[str, Any]:
        """
        Получить агрегаты для Solana по MarketAddress (Raydium CLMM и др.).
        Возвращает те же поля, что и EVM метод.
        """
        key = f"solana:{market_address}"
        cached = self.cache.get(key)
        if cached:
            return cached

        # EAP/Streaming схемы отличаются, но для бэтч-агрегаций используем общий graphql
        # В некоторых версиях используется объект solana { DEXTrades }
        query = """
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
        variables = {
            "since": self._since_24h_iso(),
            "market": market_address,
        }

        volume_usd = 0.0
        buy_usd = 0.0
        sell_usd = 0.0
        trades = 0
        try:
            async with httpx.AsyncClient() as client:
                data = await self._post(client, query, variables)
            trades_list = data.get("data", {}).get("solana", {}).get("dexTrades", [])
            for t in trades_list:
                amt = float(t.get("tradeAmount", 0) or 0)
                side = (t.get("side") or "").upper()
                cnt = int(t.get("count", 1) or 1)
                volume_usd += amt
                trades += max(cnt, 1)
                if side == "BUY":
                    buy_usd += amt
                elif side == "SELL":
                    sell_usd += amt
        except Exception as e:
            print(f"⚠️ Bitquery Solana aggregates error for {market_address}: {e}")

        result = {
            "trades_24h": trades or None,
            "volume_24h_usd": round(volume_usd, 2) if volume_usd else None,
            "buy_24h_usd": round(buy_usd, 2) if buy_usd else None,
            "sell_24h_usd": round(sell_usd, 2) if sell_usd else None,
            "net_flow_24h_usd": round((buy_usd - sell_usd), 2) if (buy_usd or sell_usd) else None,
            "price_source": "bitquery",
            "volume_source": "bitquery",
            "market_address": market_address,
            "dex_protocol": None,
        }
        self.cache.set(key, result)
        return result

    async def discover_solana_markets_by_token(self, token_mint: str) -> Dict[str, Any]:
        """
        Поиск лучших рынков для токена (market_address, dex protocol).
        Возвращает словарь с найденными рынками (можно выбрать лучший по объёму).
        """
        key = f"solana:discover:{token_mint.lower()}"
        cached = self.cache.get(key)
        if cached:
            return cached

        # Упрощенный discovery через dexTrades grouping by market
        query = """
        query ($since: ISO8601DateTime!, $token: String!) {
          solana {
            dexTrades(
              date: {since: $since}
              baseCurrency: {is: $token}
            ) {
              smartContract
              exchange {
                protocolType
                fullName
              }
              tradeAmount(in: USD)
            }
          }
        }
        """
        variables = {
            "since": self._since_24h_iso(),
            "token": token_mint,
        }

        markets: Dict[str, Dict[str, Any]] = {}
        try:
            async with httpx.AsyncClient() as client:
                data = await self._post(client, query, variables)
            trades_list = data.get("data", {}).get("solana", {}).get("dexTrades", [])
            for t in trades_list:
                market = t.get("smartContract")
                ex = t.get("exchange") or {}
                vol = float(t.get("tradeAmount", 0) or 0)
                if not market:
                    continue
                if market not in markets:
                    markets[market] = {
                        "market_address": market,
                        "dex_protocol": ex.get("protocolType") or ex.get("fullName"),
                        "volume_usd": 0.0,
                    }
                markets[market]["volume_usd"] += vol
        except Exception as e:
            print(f"⚠️ Bitquery Solana market discovery error for {token_mint}: {e}")

        # Преобразуем в список и выберем лучший по объёму
        best_market: Optional[Tuple[str, Dict[str, Any]]] = None
        for k, v in markets.items():
            if best_market is None or v.get("volume_usd", 0) > best_market[1].get("volume_usd", 0):
                best_market = (k, v)

        result = {
            "markets": list(markets.values()),
            "best_market": best_market[1] if best_market else None,
        }
        self.cache.set(key, result, ttl_seconds=900)
        return result

# CLI quick test
if __name__ == "__main__":
    import asyncio
    import argparse

    parser = argparse.ArgumentParser(description="Bitquery 24h aggregates tester")
    parser.add_argument("mode", choices=["evm", "solana", "discover"], help="Query mode")
    parser.add_argument("arg1", help="pool address (evm) or market/token (solana)")
    parser.add_argument("--network", default="ethereum", help="EVM network (ethereum/base)")
    args = parser.parse_args()

    async def run():
        client = BitqueryAdapter()
        if args.mode == "evm":
            res = await client.get_evm_pool_24h_aggregates(args.network, args.arg1)
            print(json.dumps(res, indent=2))
        elif args.mode == "solana":
            res = await client.get_solana_market_24h_aggregates(args.arg1)
            print(json.dumps(res, indent=2))
        else:
            res = await client.discover_solana_markets_by_token(args.arg1)
            print(json.dumps(res, indent=2))

    asyncio.run(run())
