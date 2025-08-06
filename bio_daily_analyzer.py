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
        
    async def collect_comprehensive_data(self) -> Dict[str, Any]:
        """Собирает полный набор данных для LP анализа"""
        
        print("📊 Собираю комплексные данные для LP анализа...")
        print(f"⏰ Время анализа: {self.analysis_time.strftime('%Y-%m-%d %H:%M UTC')}")
        
        data = {
            "analysis_timestamp": self.analysis_time.isoformat(),
            "dao_tokens_overview": [],
            "bio_lp_support": [],
            "pool_performance": [],
            "position_details": [],
            "market_metrics": {}
        }
        
        try:
            # 1. DAO Tokens Dashboard - исторические данные и тренды
            print("   📈 Получаю DAO Tokens Dashboard...")
            dao_dashboard = self.supabase.client.table('dao_tokens_dashboard').select('*').execute()
            
            if dao_dashboard.data:
                data["dao_tokens_overview"] = dao_dashboard.data
                print(f"     ✅ {len(dao_dashboard.data)} токенов с историческими данными")
                
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
                
                # ИСКЛЮЧАЕМ ПУЛЫ С НУЛЕВЫМИ ОБЪЕМАМИ из анализа (проблема с Ethereum/Base)
                active_pools = [p for p in latest_pools.values() if p.get('volume_24h_usd', 0) > 0]
                inactive_pools = [p for p in latest_pools.values() if p.get('volume_24h_usd', 0) == 0]
                
                data["pool_performance"] = active_pools
                print(f"     ✅ {len(active_pools)} активных пулов (объем > $0)")
                print(f"     ⚠️ {len(inactive_pools)} неактивных пулов исключены из анализа")
            
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
        
        system_prompt = """You are an elite DeFi strategist and market maker specializing in liquidity provision optimization for biotechnology tokens.

CORE MISSION: Analyze Bio Protocol ecosystem LP positions and provide actionable recommendations for:
1. Improving LP efficiency and reducing impermanent loss
2. Optimizing token price through strategic liquidity management  
3. Identifying market making opportunities across Solana, Ethereum, and Base

TARGET LIQUIDITY FRAMEWORK:
- Target LP = 1% of token FDV per blockchain
- This provides optimal depth for institutional trading
- Coverage below 50% indicates urgent LP gaps
- Coverage above 150% may signal over-allocation

KEY STRATEGIC PRINCIPLES:
- Prioritize high-volume, low-volatility pairs for stable returns
- Focus on tokens with strong fundamentals and growth potential
- Consider cross-chain arbitrage opportunities
- Balance between deep liquidity and capital efficiency

Provide specific, actionable recommendations with dollar amounts and reasoning."""

        # Форматируем данные для Grok
        formatted_data = self._format_lp_intelligence_prompt(data)
        
        user_prompt = f"""Analyze this Bio Protocol LP portfolio and provide strategic recommendations:

{formatted_data}

SPECIFIC ANALYSIS REQUESTED:

1. LP ALLOCATION STRATEGY:
   - Which tokens/pairs need immediate liquidity increases?
   - Which pairs are over-allocated and could be reduced?
   - Optimal LP distribution across chains (Solana vs Ethereum vs Base)

2. MARKET MAKING OPPORTUNITIES:
   - High-volume pairs with low LP coverage (arbitrage potential)
   - Cross-chain imbalances to exploit
   - Timing recommendations for LP adjustments

3. RISK MANAGEMENT:
   - Pairs with high impermanent loss exposure
   - Volatile tokens requiring active management
   - Diversification recommendations

4. SPECIFIC ACTION ITEMS:
   - Dollar amounts to move between pairs
   - Priority ranking of LP adjustments
   - Expected impact on token prices and trading volume

Be specific, quantitative, and actionable. Focus on maximizing returns while supporting token price appreciation."""

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
                grok_parts = self._split_analysis_text(grok_analysis, 3000)
                for i, part in enumerate(grok_parts):
                    await telegram.send_message(part, parse_mode=None)  # Без HTML
                    if i < len(grok_parts) - 1:
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
        
        # 2. Получаем анализы параллельно
        grok_task = analyzer.get_grok_lp_analysis(portfolio_data)
        gpt_task = analyzer.get_gpt_o3_analysis(portfolio_data) if OPENAI_API_KEY else None
        
        # Ждем результаты
        results = await asyncio.gather(
            grok_task,
            gpt_task if gpt_task else asyncio.sleep(0),
            return_exceptions=True
        )
        
        grok_analysis = results[0] if not isinstance(results[0], Exception) else None
        gpt_analysis = results[1] if gpt_task and not isinstance(results[1], Exception) else None
        
        # 3. Сохраняем результаты
        if grok_analysis or gpt_analysis:
            await analyzer.send_telegram_report(grok_analysis, gpt_analysis, portfolio_data)
            
        else:
            print("❌ Не удалось получить анализ от AI моделей")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 