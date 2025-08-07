#!/usr/bin/env python3
"""
Bio Daily Analyzer v2.0 - LP Management & Market Making Intelligence
Ежедневный анализ для оптимизации LP позиций и повышения эффективности токенов
"""

import os
import asyncio
import httpx
import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Any
from database_handler import supabase_handler
from telegram_sender import TelegramSender
import time

# API конфигурация
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
GROK_API_KEY = os.getenv('GROK_API_KEY')

# API URLs
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
GROK_API_URL = "https://api.x.ai/v1/chat/completions"

class BioLPAnalyzer:
    def __init__(self):
        self.supabase = supabase_handler
        self.analysis_time = datetime.utcnow()
        self.market_context = {}
        
    async def translate_to_russian(self, english_text: str) -> str:
        """Переводит английский анализ на русский язык"""
        
        if not english_text or not GROK_API_KEY:
            return english_text
            
        translation_prompt = f"""Переведи следующий анализ Bio Protocol LP Intelligence на русский язык. 
Сохрани всю структуру, форматирование, числа и ключевые термины.
Переводи технические термины корректно для DeFi контекста.

Текст для перевода:
{english_text}"""
        
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "grok-4-0709",
            "messages": [
                {"role": "system", "content": "Ты профессиональный переводчик DeFi и криптовалютных текстов. Переводи точно, сохраняя всю структуру и технические термины."},
                {"role": "user", "content": translation_prompt}
            ],
            "max_tokens": 4000,
            "temperature": 0.1
        }
        
        try:
            print("🌐 Переводим анализ на русский язык...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GROK_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        translation = data["choices"][0]["message"]["content"]
                        print(f"✅ Перевод выполнен ({len(translation)} символов)")
                        return translation
                    
                print(f"❌ Ошибка перевода: {response.status_code} - {response.text}")
                return english_text
                
        except Exception as e:
            print(f"❌ Ошибка API перевода: {e}")
            return english_text
        
    async def get_market_context(self) -> Dict[str, Any]:
        """Получает рыночный контекст SOL/ETH для стратегических решений"""
        
        market_data = {
            "sol_price": None,
            "eth_price": None,
            "sol_24h_change": None,
            "eth_24h_change": None,
            "btc_dominance": None,
            "total_market_cap": None
        }
        
        try:
            print("🌍 Получаю рыночный контекст SOL/ETH...")
            
            # CoinGecko API для базовых данных
            coingecko_url = "https://api.coingecko.com/api/v3/simple/price"
            params = {
                "ids": "solana,ethereum,bitcoin",
                "vs_currencies": "usd",
                "include_24hr_change": "true",
                "include_market_cap": "true"
            }
            
            async with httpx.AsyncClient() as client:
                response = await client.get(coingecko_url, params=params, timeout=10)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # SOL данные
                    if "solana" in data:
                        market_data["sol_price"] = data["solana"].get("usd")
                        market_data["sol_24h_change"] = data["solana"].get("usd_24h_change")
                    
                    # ETH данные 
                    if "ethereum" in data:
                        market_data["eth_price"] = data["ethereum"].get("usd")
                        market_data["eth_24h_change"] = data["ethereum"].get("usd_24h_change")
                    
                    # BTC для контекста
                    if "bitcoin" in data:
                        market_data["btc_price"] = data["bitcoin"].get("usd")
                        market_data["btc_24h_change"] = data["bitcoin"].get("usd_24h_change")
                    
                    print(f"     ✅ SOL: ${market_data['sol_price']:.2f} ({market_data['sol_24h_change']:+.2f}%)")
                    print(f"     ✅ ETH: ${market_data['eth_price']:.2f} ({market_data['eth_24h_change']:+.2f}%)")
                else:
                    print(f"     ⚠️ CoinGecko API ошибка: {response.status_code}")
                    
        except Exception as e:
            print(f"     ❌ Ошибка получения рыночных данных: {e}")
        
        return market_data
    
    async def validate_tokens_externally(self, tokens_data: List[Dict]) -> Dict[str, Any]:
        """Сверяет данные токенов с DexScreener для выявления расхождений"""
        
        validation_results = {
            "discrepancies": [],
            "missing_listings": [],
            "price_differences": [],
            "validation_summary": {}
        }
        
        try:
            print("🔍 Проверяю токены на DexScreener...")
            
            # Проверяем только топ-5 токенов по FDV чтобы не перегружать API
            top_tokens = sorted(tokens_data, key=lambda x: float(x.get('FDV', 0) or 0), reverse=True)[:5]
            
            for token in top_tokens:
                symbol = token.get('Token', '')
                our_price = token.get('Price', 0)
                our_fdv = float(token.get('FDV', 0) or 0)
                
                if not symbol or symbol == 'BIO':  # Пропускаем BIO и пустые
                    continue
                
                try:
                    # DexScreener API для поиска токена
                    search_url = f"https://api.dexscreener.com/latest/dex/search?q={symbol}"
                    
                    async with httpx.AsyncClient() as client:
                        response = await client.get(search_url, timeout=10)
                        
                        if response.status_code == 200:
                            data = response.json()
                            pairs = data.get('pairs', [])
                            
                            if pairs:
                                # Берем первую пару как ссылку
                                pair = pairs[0]
                                dex_price = float(pair.get('priceUsd', 0) or 0)
                                dex_fdv = float(pair.get('fdv', 0) or 0)
                                
                                # Сравниваем цены (разница > 5%)
                                if our_price and dex_price:
                                    price_diff = abs(our_price - dex_price) / our_price * 100
                                    if price_diff > 5:
                                        validation_results["price_differences"].append({
                                            "token": symbol,
                                            "our_price": our_price,
                                            "dex_price": dex_price,
                                            "difference_pct": price_diff
                                        })
                                
                                print(f"     ✅ {symbol}: DexScreener найден, цена ${dex_price:.6f}")
                            else:
                                validation_results["missing_listings"].append({
                                    "token": symbol,
                                    "reason": "Not found on DexScreener"
                                })
                                print(f"     ⚠️ {symbol}: Не найден на DexScreener")
                        else:
                            print(f"     ❌ {symbol}: DexScreener API ошибка {response.status_code}")
                            
                    # Пауза между запросами
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    print(f"     ❌ Ошибка проверки {symbol}: {e}")
                    
        except Exception as e:
            print(f"     ❌ Общая ошибка валидации: {e}")
        
        # Суммарная статистика
        validation_results["validation_summary"] = {
            "tokens_checked": len(top_tokens),
            "missing_count": len(validation_results["missing_listings"]),
            "price_discrepancies": len(validation_results["price_differences"]),
            "health_score": max(0, 100 - (len(validation_results["missing_listings"]) * 20) - (len(validation_results["price_differences"]) * 10))
        }
        
        print(f"     📊 Проверено {len(top_tokens)} токенов, здоровье экосистемы: {validation_results['validation_summary']['health_score']}/100")
        
        return validation_results
        
    async def collect_comprehensive_data(self) -> Dict[str, Any]:
        """Собирает полный набор данных для LP анализа"""
        
        print("📊 Собираю комплексные данные для LP анализа...")
        print(f"⏰ Время анализа: {self.analysis_time.strftime('%Y-%m-%d %H:%M UTC')}")
        
        # Получаем рыночный контекст
        self.market_context = await self.get_market_context()
        
        data = {
            "analysis_timestamp": self.analysis_time.isoformat(),
            "dao_tokens_overview": [],
            "bio_lp_support": [],
            "pool_performance": [],
            "position_details": [],
            "market_metrics": {},
            "market_context": self.market_context,
            "external_validation": {}
        }
        
        try:
            # 1. DAO Tokens Dashboard - исторические данные и тренды
            print("   📈 Получаю DAO Tokens Dashboard...")
            dao_dashboard = self.supabase.client.table('dao_tokens_dashboard').select('*').execute()
            
            if dao_dashboard.data:
                data["dao_tokens_overview"] = dao_dashboard.data
                print(f"     ✅ {len(dao_dashboard.data)} токенов с историческими данными")
                
                # Валидация токенов через внешние источники
                data["external_validation"] = await self.validate_tokens_externally(dao_dashboard.data)
                
                # Извлекаем ключевые метрики
                bio_token = next((t for t in dao_dashboard.data if 'BIO' in t.get('Token', '')), None)
                if bio_token:
                    data["market_metrics"]["bio_price"] = bio_token.get('Price')
                    data["market_metrics"]["bio_fdv"] = bio_token.get('FDV')
                    data["market_metrics"]["bio_24h_change"] = bio_token.get('24h Δ')
                    data["market_metrics"]["bio_7d_change"] = bio_token.get('7d Δ')
            
            # 2. Bio DAO LP Support - текущее состояние LP
            print("   🧬 Получаю Bio DAO LP Support...")
            bio_support = self.supabase.client.table('bio_dao_lp_support').select('*').execute()
            
            if bio_support.data:
                data["bio_lp_support"] = bio_support.data
                print(f"     ✅ {len(bio_support.data)} записей по BIO LP поддержке")
                
                # Улучшенный расчет LP coverage с четкой логикой 1% от FDV
                total_current = 0
                total_target_calculated = 0
                total_target_from_db = 0
                lp_coverage_by_chain = {}
                
                for item in bio_support.data:
                    token_symbol = item.get('token_symbol', '')
                    network = item.get('network', '')
                    fdv = float(item.get('token_fdv_usd', 0) or 0)
                    current_lp = float(item.get('our_position_value_usd', 0) or 0)
                    target_from_db = float(item.get('target_lp_value_usd', 0) or 0)
                    
                    # НОВАЯ ЛОГИКА: Target LP = 1% от FDV токена на чейн
                    target_calculated = fdv * 0.01  # 1% от FDV
                    
                    total_current += current_lp
                    total_target_calculated += target_calculated
                    total_target_from_db += target_from_db
                    
                    # Группируем по чейнам для детального анализа
                    chain_key = network
                    if chain_key not in lp_coverage_by_chain:
                        lp_coverage_by_chain[chain_key] = {
                            'tokens': [],
                            'total_fdv': 0,
                            'total_target_lp': 0,
                            'total_current_lp': 0,
                            'coverage_ratio': 0
                        }
                    
                    chain_data = lp_coverage_by_chain[chain_key]
                    chain_data['tokens'].append({
                        'symbol': token_symbol,
                        'fdv': fdv,
                        'target_lp': target_calculated,
                        'current_lp': current_lp,
                        'coverage': (current_lp / target_calculated * 100) if target_calculated > 0 else 0
                    })
                    chain_data['total_fdv'] += fdv
                    chain_data['total_target_lp'] += target_calculated
                    chain_data['total_current_lp'] += current_lp
                
                # Рассчитываем coverage по чейнам
                for chain_key in lp_coverage_by_chain:
                    chain_data = lp_coverage_by_chain[chain_key]
                    chain_data['coverage_ratio'] = (
                        chain_data['total_current_lp'] / chain_data['total_target_lp'] * 100
                    ) if chain_data['total_target_lp'] > 0 else 0
                
                # Используем улучшенные расчеты
                total_gap = total_target_calculated - total_current
                
                data["market_metrics"]["total_target_lp"] = total_target_calculated
                data["market_metrics"]["total_current_lp"] = total_current  
                data["market_metrics"]["total_lp_gap"] = total_gap
                data["market_metrics"]["lp_coverage_ratio"] = (total_current / total_target_calculated * 100) if total_target_calculated > 0 else 0
                data["market_metrics"]["lp_coverage_by_chain"] = lp_coverage_by_chain
                data["market_metrics"]["target_lp_logic"] = "1% от FDV токена на чейн"
                
                print(f"     📊 Target LP (1% FDV): ${total_target_calculated:,.0f}")
                print(f"     💰 Current LP: ${total_current:,.0f}")
                print(f"     📈 Coverage: {(total_current / total_target_calculated * 100) if total_target_calculated > 0 else 0:.1f}%")
            
            # 3. Pool Performance - последние снапшоты всех пулов
            print("   🏊 Получаю актуальные Pool snapshots...")
            pools = self.supabase.client.table('lp_pool_snapshots').select('*').order(
                'created_at', desc=True
            ).execute()
            
            if pools.data:
                # Берем только последний снапшот для каждого пула
                latest_pools = {}
                for pool in pools.data:
                    key = f"{pool['pool_address']}_{pool['network']}"
                    if key not in latest_pools:
                        latest_pools[key] = pool
                
                # УЛУЧШЕННАЯ ФИЛЬТРАЦИЯ: включаем пулы с TVL > 0 даже если volume = 0
                # (после исправлений TVL многие пулы получили корректные значения)
                active_pools = []
                inactive_pools = []
                
                for pool in latest_pools.values():
                    volume = pool.get('volume_24h_usd', 0) or 0
                    tvl = pool.get('tvl_usd', 0) or 0
                    
                    # Активный пул: есть объем ИЛИ есть значительная ликвидность
                    if volume > 0 or tvl > 1000:  # TVL > $1k считаем значимым
                        active_pools.append(pool)
                    else:
                        inactive_pools.append(pool)
                
                data["pool_performance"] = active_pools
                print(f"     ✅ {len(active_pools)} активных пулов (volume > $0 OR TVL > $1k)")
                print(f"     ⚠️ {len(inactive_pools)} неактивных пулов исключены")
                
                # Статистика по критериям
                volume_pools = len([p for p in active_pools if p.get('volume_24h_usd', 0) > 0])
                tvl_only_pools = len([p for p in active_pools if p.get('volume_24h_usd', 0) == 0 and p.get('tvl_usd', 0) > 1000])
                print(f"     📊 Из них: {volume_pools} с объемом, {tvl_only_pools} только с TVL")
            
            # 4. Position Details - наши текущие позиции
            print("   📍 Получаю актуальные Position snapshots...")
            positions = self.supabase.client.table('lp_position_snapshots').select('*').gt(
                'position_value_usd', 0
            ).order('created_at', desc=True).execute()
            
            if positions.data:
                # Берем только последний снапшот для каждой позиции
                latest_positions = {}
                for pos in positions.data:
                    key = pos['position_mint']
                    if key not in latest_positions:
                        latest_positions[key] = pos
                
                data["position_details"] = list(latest_positions.values())
                print(f"     ✅ {len(latest_positions)} активных позиций")
                
                # Считаем метрики позиций
                total_pos_value = sum(float(pos.get('position_value_usd', 0)) for pos in latest_positions.values())
                in_range_count = sum(1 for pos in latest_positions.values() if pos.get('in_range'))
                total_fees = sum(float(pos.get('fees_usd', 0) or 0) for pos in latest_positions.values())
                
                data["market_metrics"]["total_position_value"] = total_pos_value
                data["market_metrics"]["in_range_positions"] = in_range_count
                data["market_metrics"]["total_positions"] = len(latest_positions)
                data["market_metrics"]["total_accumulated_fees"] = total_fees
                data["market_metrics"]["in_range_ratio"] = (in_range_count / len(latest_positions) * 100) if latest_positions else 0
            
            print(f"✅ Комплексные данные собраны:")
            print(f"   📈 {len(data['dao_tokens_overview'])} токенов")
            print(f"   🧬 {len(data['bio_lp_support'])} BIO LP записей") 
            print(f"   🏊 {len(data['pool_performance'])} пулов")
            print(f"   📍 {len(data['position_details'])} позиций")
            
            return data
            
        except Exception as e:
            print(f"❌ Ошибка сбора данных: {e}")
            raise
    
    def _format_lp_intelligence_prompt(self, data: Dict[str, Any]) -> str:
        """Создает специализированный промпт для LP Management анализа"""
        
        prompt = f"""LP MANAGEMENT & MARKET MAKING INTELLIGENCE REPORT
Analysis Time: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
Data Source: Real-time Supabase snapshots

=== EXECUTIVE SUMMARY ===
Total Tokens Monitored: {len(data['dao_tokens_overview'])}
Active LP Positions: {data['market_metrics'].get('total_positions', 0)}
In-Range Ratio: {data['market_metrics'].get('in_range_ratio', 0):.1f}%
Current LP Value: ${data['market_metrics'].get('total_position_value', 0):,.2f}
Total Accumulated Fees: ${data['market_metrics'].get('total_accumulated_fees', 0):,.2f}

=== BIO TOKEN MARKET STATE ===
"""
        
        # BIO метрики
        bio_price = data['market_metrics'].get('bio_price')
        bio_fdv = data['market_metrics'].get('bio_fdv')
        bio_24h = data['market_metrics'].get('bio_24h_change')
        bio_7d = data['market_metrics'].get('bio_7d_change')
        
        if bio_price:
            prompt += f"Current Price: ${bio_price}\n"
            prompt += f"FDV: ${bio_fdv:,.0f}\n" if bio_fdv else "FDV: N/A\n"
            prompt += f"24h Change: {bio_24h}%\n" if bio_24h else ""
            prompt += f"7d Change: {bio_7d}%\n" if bio_7d else ""
        
        # LP Coverage анализ
        target_lp = data['market_metrics'].get('total_target_lp', 0)
        current_lp = data['market_metrics'].get('total_current_lp', 0)
        lp_gap = data['market_metrics'].get('total_lp_gap', 0)
        coverage = data['market_metrics'].get('lp_coverage_ratio', 0)
        coverage_by_chain = data['market_metrics'].get('lp_coverage_by_chain', {})
        
        prompt += f"\n=== LP COVERAGE ANALYSIS ===\n"
        prompt += f"TARGET LIQUIDITY LOGIC: {data['market_metrics'].get('target_lp_logic', 'Not specified')}\n"
        prompt += f"• Target LP Value: ${target_lp:,.2f} (1% от общего FDV токенов)\n"
        prompt += f"• Current LP Value: ${current_lp:,.2f}\n"
        prompt += f"• LP Gap: ${lp_gap:,.2f}\n"
        prompt += f"• Overall Coverage: {coverage:.1f}%\n\n"
        
        # Детальная разбивка по чейнам
        prompt += "COVERAGE BY BLOCKCHAIN:\n"
        for chain, chain_data in coverage_by_chain.items():
            prompt += f"\n{chain.upper()}:\n"
            prompt += f"  Total FDV: ${chain_data['total_fdv']:,.0f}\n"
            prompt += f"  Target LP (1%): ${chain_data['total_target_lp']:,.0f}\n"
            prompt += f"  Current LP: ${chain_data['total_current_lp']:,.0f}\n"
            prompt += f"  Coverage: {chain_data['coverage_ratio']:.1f}%\n"
            
            # Топ-3 токена по coverage
            tokens_by_coverage = sorted(chain_data['tokens'], key=lambda x: x['coverage'], reverse=True)
            prompt += f"  Top tokens by coverage:\n"
            for i, token in enumerate(tokens_by_coverage[:3]):
                prompt += f"    {i+1}. {token['symbol']}: {token['coverage']:.1f}% (${token['current_lp']:,.0f}/${token['target_lp']:,.0f})\n"
        
        # Топ токены по FDV и изменениям
        # Рыночный контекст
        market_ctx = data.get('market_context', {})
        if any(market_ctx.values()):
            prompt += f"\n=== MARKET CONTEXT ===\n"
            if market_ctx.get('sol_price'):
                prompt += f"SOL: ${market_ctx['sol_price']:.2f} ({market_ctx.get('sol_24h_change', 0):+.2f}% 24h)\n"
            if market_ctx.get('eth_price'):
                prompt += f"ETH: ${market_ctx['eth_price']:.2f} ({market_ctx.get('eth_24h_change', 0):+.2f}% 24h)\n"
            if market_ctx.get('btc_price'):
                prompt += f"BTC: ${market_ctx['btc_price']:.2f} ({market_ctx.get('btc_24h_change', 0):+.2f}% 24h)\n"
        
        # Внешняя валидация
        ext_validation = data.get('external_validation', {})
        if ext_validation:
            prompt += f"\n=== EXTERNAL VALIDATION (DexScreener) ===\n"
            summary = ext_validation.get('validation_summary', {})
            prompt += f"Ecosystem Health Score: {summary.get('health_score', 0)}/100\n"
            
            missing = ext_validation.get('missing_listings', [])
            if missing:
                prompt += f"\u26a0\ufe0f Missing Listings ({len(missing)}): "
                prompt += ", ".join([m['token'] for m in missing]) + "\n"
            
            price_diffs = ext_validation.get('price_differences', [])
            if price_diffs:
                prompt += f"\u26a0\ufe0f Price Discrepancies ({len(price_diffs)}): "
                for diff in price_diffs:
                    prompt += f"{diff['token']} ({diff['difference_pct']:.1f}% diff), "
                prompt = prompt.rstrip(', ') + "\n"
        
        prompt += f"\n=== TOKEN PERFORMANCE MATRIX ===\n"
        sorted_tokens = sorted(data['dao_tokens_overview'], 
                             key=lambda x: float(x.get('FDV', 0) or 0), reverse=True)
        
        for token in sorted_tokens[:10]:  # Топ 10
            symbol = token.get('Token', 'Unknown')
            fdv = float(token.get('FDV', 0) or 0)
            change_24h = token.get('24h Δ', 'N/A')
            tvl = float(token.get('TVL (all pools)', 0) or 0)
            fdv_tvl_ratio = float(token.get('FDV/TVL', 0) or 0)
            
            prompt += f"{symbol}: FDV ${fdv:,.0f}, 24h {change_24h}%, TVL ${tvl:,.0f}, FDV/TVL {fdv_tvl_ratio:.1f}x\n"
        
        # Детализация BIO LP поддержки по сетям
        prompt += f"\n=== BIO LP SUPPORT BY NETWORK ===\n"
        networks = {}
        for item in data['bio_lp_support']:
            network = item.get('network_display', 'Unknown')
            if network not in networks:
                networks[network] = []
            networks[network].append(item)
        
        for network, items in networks.items():
            prompt += f"\n{network}:\n"
            for item in items:
                symbol = item.get('token_symbol', 'Unknown')
                target = float(item.get('target_lp_value_usd', 0) or 0)
                current = float(item.get('our_position_value_usd', 0) or 0)
                gap = float(item.get('lp_gap_usd', 0) or 0)
                tvl = float(item.get('tvl_usd', 0) or 0)
                
                coverage_pct = (current / target * 100) if target > 0 else 0
                prompt += f"  {symbol}: Target ${target:,.0f}, Current ${current:,.0f}, Gap ${gap:,.0f} ({coverage_pct:.1f}% coverage), Pool TVL ${tvl:,.0f}\n"
        
        # Pool Performance детали
        prompt += f"\n=== POOL PERFORMANCE ANALYSIS ===\n"
        bio_pools = [p for p in data['pool_performance'] if 'BIO' in p.get('pool_name', '')]
        
        for pool in bio_pools:
            name = pool.get('pool_name', 'Unknown')
            network = pool.get('network', 'Unknown')
            tvl = float(pool.get('tvl_usd', 0) or 0)
            volume_24h = float(pool.get('volume_24h_usd', 0) or 0)
            price_change = pool.get('price_change_24h_percent', 'N/A')
            tvl_change = pool.get('tvl_change_percent', 'N/A')
            in_range_pos = pool.get('in_range_positions', 0)
            total_pos = pool.get('total_positions', 0)
            
            prompt += f"{name} ({network}):\n"
            prompt += f"  TVL: ${tvl:,.0f} (24h change: {tvl_change}%)\n"
            prompt += f"  Volume 24h: ${volume_24h:,.0f}\n"
            prompt += f"  Price change 24h: {price_change}%\n"
            prompt += f"  Positions: {in_range_pos}/{total_pos} in-range\n"
        
        # Наши позиции по эффективности
        prompt += f"\n=== OUR POSITION EFFICIENCY ANALYSIS ===\n"
        bio_positions = [p for p in data['position_details'] if 'BIO' in p.get('pool_name', '')]
        
        # Сортируем по стоимости
        bio_positions.sort(key=lambda x: float(x.get('position_value_usd', 0)), reverse=True)
        
        for pos in bio_positions[:15]:  # Топ 15 позиций
            pool = pos.get('pool_name', 'Unknown')
            network = pos.get('network', 'Unknown')
            value = float(pos.get('position_value_usd', 0))
            fees = float(pos.get('fees_usd', 0) or 0)
            in_range = pos.get('in_range', False)
            age = pos.get('position_age_days', 0)
            health_score = pos.get('position_health_score', 'N/A')
            il_pct = pos.get('impermanent_loss_pct', 'N/A')
            
            status = "🟢 IN-RANGE" if in_range else "🔴 OUT-RANGE"
            prompt += f"{pool} ({network}): ${value:,.0f}, Fees ${fees:,.2f}, {status}, Age {age}d, Health {health_score}, IL {il_pct}%\n"
        
        return prompt
    
    def _create_grok_prompt(self, data: Dict[str, Any]) -> tuple:
        """Создает промпт для Grok 4 с фокусом на LP стратегию"""
        
        system_prompt = """Ты стратег экосистемы Bio Protocol. Будь КРАТКИМ и НАПРАВЛЕННЫМ НА ДЕЙСТВИЯ.

КОНТЕКСТ:
- BIO - основная пара для всех bioDAO токенов
- Доступно 830M BIO из экосистемного фонда (~$6.8M по текущим ценам)
- Цель: 1% FDV ликвидности на токен на сеть
- Задача: Предотвратить появление "мертвых" или неработающих токенов

ТВОЯ РОЛЬ:
- Определи критические пробелы LP и предложи конкретные $ суммы
- Предложи системы автоматизации/мониторинга
- Сосредоточься на немедленных действиях, а не на теории

ТРЕБОВАНИЯ К ОТВЕТУ:
- Используй списки и цифры
- Указывай конкретные $ суммы из BIO фонда
- Каждая секция максимум 200 слов
- Никаких длинных объяснений и маркетинговых речей
- Фокус на том, что делать НА ЭТОЙ НЕДЕЛЕ

Будь прямым, практичным и количественным."""

        # Форматируем данные для Grok
        formatted_data = self._format_lp_intelligence_prompt(data)
        
        user_prompt = f"""Проанализируй данные экосистемы Bio Protocol и дай КРАТКИЕ рекомендации:

=== ДАННЫЕ ===
{formatted_data}

=== ТРЕБУЕМЫЙ АНАЛИЗ (КРАТКО И КОНКРЕТНО) ===

🚨 КРИТИЧЕСКИЕ ПРОБЛЕМЫ:
- Какие токены имеют покрытие LP <50%? Список с разрывами в $.
- Какие токены отсутствуют на DexScreener/основных DEX?
- Позиции с высоким риском IL или вне диапазона?

💰 НЕМЕДЛЕННЫЕ ДЕЙСТВИЯ (эта неделя):
- Конкретные $ суммы для выделения из фонда 830M BIO
- Какие пулы нуждаются в срочном добавлении ликвидности?
- Приоритеты: 1-3 самых критичных действия

🤖 ВОЗМОЖНОСТИ АВТОМАТИЗАЦИИ:
- Простые скрипты для мониторинга/ребалансировки
- Пороги алертов (цена, объем, покрытие)
- Обнаружение арбитража между сетями

📊 МЕТРИКИ УСПЕХА:
- Целевое покрытие % по сетям
- Соотношения объем/ликвидность для достижения
- График следующего обзора

ФОРМАТ: Используй списки, цифры и таблицы. НИКАКИХ длинных объяснений.
ФОКУС: Практические действия с $ суммами и дедлайнами.
ДЛИНА: Максимум 300 слов на секцию."""

        return system_prompt, user_prompt
    
    async def get_grok_lp_analysis(self, data: Dict[str, Any]) -> Optional[str]:
        """Получает специализированный LP анализ от Grok 4"""
        
        # Форматируем данные для анализа
        data_prompt = self._format_lp_intelligence_prompt(data)
        
        # Создаем промпты
        system_prompt, user_prompt = self._create_grok_prompt(data)
        
        headers = {
            "Authorization": f"Bearer {GROK_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "grok-4-0709",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "max_tokens": 3000,
            "temperature": 0.1
        }
        
        try:
            print("🚀 Отправляю данные в Grok 4 для LP анализа...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    GROK_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=150
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        analysis = data["choices"][0]["message"]["content"]
                        print(f"✅ Grok 4 LP анализ получен ({len(analysis)} символов)")
                        return analysis
                    
                print(f"❌ Grok ошибка: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка Grok запроса: {e}")
            return None
    
    async def get_gpt_o3_analysis(self, data: Dict[str, Any]) -> Optional[str]:
        """Получает дополнительный анализ от GPT o3"""
        
        if not OPENAI_API_KEY:
            return None
            
        data_prompt = self._format_lp_intelligence_prompt(data)
        
        headers = {
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        system_prompt = """You are an elite quantitative DeFi analyst with advanced reasoning capabilities specializing in Bio Protocol ecosystem analysis.

ANALYTICAL FRAMEWORK:
- Target Liquidity Model: 1% of token FDV per blockchain provides optimal institutional trading depth
- Coverage Ratios: <50% urgent gaps, 50-100% healthy, >150% potential over-allocation
- LP Efficiency Metrics: Focus on fees/capital ratio, impermanent loss minimization, volume/liquidity ratio

Use step-by-step reasoning to provide quantitative insights on:
1. LP capital allocation efficiency across chains (Solana, Ethereum, Base)
2. Mathematical optimization of position ranges and sizes
3. Risk-adjusted return calculations for each LP pair
4. Cross-chain arbitrage opportunities and optimal execution

Provide mathematical models, specific dollar recommendations, and quantified risk assessments."""
        
        payload = {
            "model": "o3",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this LP portfolio data and provide quantitative insights:\n\n{data_prompt}"}
            ],
            "max_completion_tokens": 2000
        }
        
        try:
            print("🤖 Отправляю данные в GPT o3 для количественного анализа...")
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    OPENAI_API_URL,
                    headers=headers,
                    json=payload,
                    timeout=120
                )
                
                if response.status_code == 200:
                    data = response.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        analysis = data["choices"][0]["message"]["content"]
                        print(f"✅ GPT o3 анализ получен ({len(analysis)} символов)")
                        return analysis
                    
                print(f"❌ GPT o3 ошибка: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка GPT o3 запроса: {e}")
            return None
    
    async def send_fallback_report(self, raw_data: Dict) -> bool:
        """Отправляет базовый отчет с данными если AI анализ недоступен"""
        
        try:
            telegram = TelegramSender()
            
            # Базовый отчет с ключевыми метриками
            fallback_report = f"""🧬 <b>ОТЧЕТ BIO PROTOCOL LP</b>
📅 {self.analysis_time.strftime('%d.%m.%Y %H:%M UTC')}
⚠️ <i>AI анализ недоступен, показываю базовые данные</i>

💰 <b>ПОРТФЕЛЬ</b>
• Общая стоимость: <b>${raw_data['market_metrics'].get('total_position_value', 0):,.0f}</b>
• Активных позиций: <b>{raw_data['market_metrics'].get('total_positions', 0)}</b>
• В диапазоне: <b>{raw_data['market_metrics'].get('in_range_ratio', 0):.1f}%</b>
• Накопленные комиссии: <b>${raw_data['market_metrics'].get('total_accumulated_fees', 0):,.2f}</b>

🎯 <b>ПОКРЫТИЕ LP</b>
• Целевой LP: <b>${raw_data['market_metrics'].get('total_target_lp', 0):,.0f}</b>
• Текущий LP: <b>${raw_data['market_metrics'].get('total_current_lp', 0):,.0f}</b>
• Покрытие: <b>{raw_data['market_metrics'].get('lp_coverage_ratio', 0):.1f}%</b>
• Разрыв: <b>${raw_data['market_metrics'].get('total_lp_gap', 0):,.0f}</b>

📊 <b>ТОКЕН BIO</b>
• Цена: <b>${raw_data['market_metrics'].get('bio_price', 0):.6f}</b>
• Изменение 24ч: <b>{raw_data['market_metrics'].get('bio_24h_change', 0):+.2f}%</b>
• FDV: <b>${raw_data['market_metrics'].get('bio_fdv', 0):,.0f}</b>

📈 <b>АКТИВНЫЕ ПУЛЫ</b>
• Всего: <b>{len(raw_data['pool_performance'])}</b> пулов
• Сети: Solana, Ethereum, Base

<i>Для полного AI анализа обратитесь к администратору</i>"""
            
            await telegram.send_message(fallback_report)
            print("✅ Fallback отчет отправлен в Telegram")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка отправки fallback отчета: {e}")
            return False
    
    async def send_telegram_report(self, grok_analysis: str, gpt_analysis: str, raw_data: Dict) -> bool:
        """Отправляет анализ в Telegram"""
        
        try:
            telegram = TelegramSender()
            
            # Формируем заголовок отчета
            header = f"""🧬 <b>BIO PROTOCOL LP INTELLIGENCE</b>
📅 {self.analysis_time.strftime('%d.%m.%Y %H:%M UTC')}
💰 Portfolio: <b>${raw_data['market_metrics'].get('total_position_value', 0):,.0f}</b>
📍 Positions: <b>{raw_data['market_metrics'].get('total_positions', 0)}</b> (In-range: <b>{raw_data['market_metrics'].get('in_range_ratio', 0):.1f}%</b>)
🎯 LP Coverage: <b>{raw_data['market_metrics'].get('lp_coverage_ratio', 0):.1f}%</b>
💸 LP Gap: <b>${raw_data['market_metrics'].get('total_lp_gap', 0):,.0f}</b>

═══════════════════════════"""
            
            # Отправляем заголовок
            await telegram.send_message(header)
            await asyncio.sleep(1)
            
            # Отправляем анализ Grok
            if grok_analysis:
                grok_header = "🚀 <b>GROK 4 LP STRATEGY ANALYSIS</b>"
                await telegram.send_message(grok_header)
                await asyncio.sleep(1)
                
                # Разбиваем длинный анализ на части и отправляем БЕЗ HTML разметки
                analysis_parts = self._split_analysis_text(grok_analysis, 3000)
                for i, part in enumerate(analysis_parts):
                    await telegram.send_message(part, parse_mode=None)  # Без HTML
                    if i < len(analysis_parts) - 1:
                        await asyncio.sleep(2)
            
            # Отправляем анализ GPT
            if gpt_analysis:
                await asyncio.sleep(2)
                gpt_header = "🤖 <b>GPT O3 QUANTITATIVE ANALYSIS</b>"
                await telegram.send_message(gpt_header)
                await asyncio.sleep(1)
                
                # Разбиваем длинный анализ на части и отправляем БЕЗ HTML разметки
                gpt_parts = self._split_analysis_text(gpt_analysis, 3000)
                for i, part in enumerate(gpt_parts):
                    await telegram.send_message(part, parse_mode=None)  # Без HTML
                    if i < len(gpt_parts) - 1:
                        await asyncio.sleep(2)
            
            # Отправляем ключевые метрики
            await asyncio.sleep(2)
            metrics_text = f"""📊 <b>KEY METRICS SUMMARY</b>
• BIO Price: <b>${raw_data['market_metrics'].get('bio_price', 0):.6f}</b> ({raw_data['market_metrics'].get('bio_24h_change', 0):+.2f}% 24h)
• BIO FDV: <b>${raw_data['market_metrics'].get('bio_fdv', 0):,.0f}</b>
• Total Target LP: <b>${raw_data['market_metrics'].get('total_target_lp', 0):,.0f}</b>
• Current LP: <b>${raw_data['market_metrics'].get('total_current_lp', 0):,.0f}</b>
• Fees Accumulated: <b>${raw_data['market_metrics'].get('total_accumulated_fees', 0):,.2f}</b>"""
            
            await telegram.send_message(metrics_text)
            
            print("✅ LP Intelligence отчет отправлен в Telegram")
            return True
            
        except Exception as e:
            print(f"❌ Ошибка отправки в Telegram: {e}")
            return False
    
    def _escape_html_chars(self, text: str) -> str:
        """Экранирует HTML символы для Telegram"""
        if not text:
            return text
        # Заменяем только проблемные символы, сохраняя базовую разметку
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        # Убираем проблемные символы процентов если они не в тегах
        import re
        text = re.sub(r'(?<!<[^>]*)\%(?![^<]*>)', ' percent', text)
        return text
    
    def _split_analysis_text(self, text: str, max_length: int) -> List[str]:
        """Разбивает длинный текст анализа на части для Telegram"""
        if len(text) <= max_length:
            return [text]
        
        parts = []
        current_part = ""
        
        # Разбиваем по абзацам
        paragraphs = text.split('\n\n')
        
        for paragraph in paragraphs:
            # Если абзац слишком длинный, разбиваем по предложениям
            if len(paragraph) > max_length:
                sentences = paragraph.split('. ')
                for sentence in sentences:
                    if len(current_part + sentence) > max_length:
                        if current_part:
                            parts.append(current_part.strip())
                            current_part = sentence + '. '
                        else:
                            # Предложение слишком длинное, разбиваем принудительно
                            parts.append(sentence[:max_length-3] + "...")
                    else:
                        current_part += sentence + '. '
            else:
                if len(current_part + paragraph) > max_length:
                    if current_part:
                        parts.append(current_part.strip())
                        current_part = paragraph + '\n\n'
                    else:
                        parts.append(paragraph)
                else:
                    current_part += paragraph + '\n\n'
        
        if current_part.strip():
            parts.append(current_part.strip())
        
        return parts

async def main():
    """Основная функция LP анализатора"""
    
    print("🧬 BIO PROTOCOL LP INTELLIGENCE ANALYZER")
    print("=" * 60)
    print(f"⏰ Запуск: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}")
    print("🎯 Фокус: LP Management & Market Making Optimization")
    
    analyzer = BioLPAnalyzer()
    
    try:
        # 1. Собираем комплексные данные
        portfolio_data = await analyzer.collect_comprehensive_data()
        
        if not any([portfolio_data['dao_tokens_overview'], portfolio_data['bio_lp_support'], 
                   portfolio_data['position_details']]):
            print("❌ Недостаточно данных для анализа")
            return
        
        print(f"\n🚀 Запускаю AI анализ портфеля...")
        
        # 2. Получаем анализ только от Grok (GPT o3 временно исключен)
        print("📊 Анализ проводится только через Grok 4...")
        grok_analysis = await analyzer.get_grok_lp_analysis(portfolio_data)
        
        # 3. Отправляем результаты
        if grok_analysis:
            await analyzer.send_telegram_report(grok_analysis, None, portfolio_data)
            print("✅ Анализ завершен и отправлен в Telegram")
        else:
            print("❌ Не удалось получить анализ от Grok")
            # Отправляем базовый отчет с данными
            await analyzer.send_fallback_report(portfolio_data)
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 