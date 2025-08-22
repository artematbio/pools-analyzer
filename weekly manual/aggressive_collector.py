#!/usr/bin/env python3
"""
АГРЕССИВНЫЙ сборщик транзакций - ДОЛБИТ API пока не получит данные
"""

import json
import requests
import csv
import time
import datetime
import os
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass
class Transaction:
    chain: str
    pool_address: str
    pool_name: str
    tx_hash: str
    sender_address: str
    amount_usd: float
    timestamp: int
    block_number: int

class AggressiveTransactionsCollector:
    def __init__(self):
        load_dotenv()
        
        with open('tokens_pools_config.json', 'r') as f:
            self.config = json.load(f)
        
        # ТОЧНЫЕ даты: 7-8 августа 2025
        self.start_timestamp = int(datetime.datetime(2025, 8, 7, 0, 0, 0).timestamp())
        self.end_timestamp = int(datetime.datetime(2025, 8, 9, 0, 0, 0).timestamp())
        
        print(f"🔥 АГРЕССИВНЫЙ СБОР ЗА: 7-8 августа 2025")
        print(f"   Start: {self.start_timestamp}")
        print(f"   End: {self.end_timestamp}")
        
        # API ключи
        self.helius_key = os.getenv('HELIUS_API_KEY', 'd4af7b72-f199-4d77-91a9-11d8512c5e42')
        
        # Цены токенов
        self.token_prices = {
            'So11111111111111111111111111111111111111112': 200,  # SOL
            'bioJ9JTqW62MLz7UKHU69gtKhPpGi1BQhccj2kmSvUJ': 0.02,  # BIO
            'spinezMPKxkBpf4Q9xET2587fehM3LuKe4xoAoXtSjR': 0.008,  # SPINE
            '9qU3LmwKJKT2DJeGPihyTP2jc6pC7ij3hPFeyJVzuksN': 0.004,  # CURES
            'qbioCGDnUBGX5qcK1Fc4zg19GaQEPmxHFMPMZQm4LZ8': 0.0036,  # QBIO
            'GJtJuWD9qYcCkrwMBmtY1tpapV1sKfB2zUv9Q4aqpump': 0.0026,  # RIF
            'FvgqHMfL9yn39V79huDPy3YUNDoYJpuLWng2JfmQpump': 0.0021,  # URO
            'EzYEwn4R5tNkNGw4K2a5a58MJFQESdf1r4UJrV7cpUF3': 0.0016,  # MYCO
            'growFDf9teg9gwVTTY3DgpPXU31qBrnbSQCqtY2vkR8': 0.015,  # GROW
            'neuRodi6Saw2cwDpud7FyAcjzqPBJDtr3fDTXE2Fu4j': 0.0151,  # NEURON
        }

    def aggressive_api_call(self, url: str, params: dict, max_retries: int = 5) -> Optional[dict]:
        """АГРЕССИВНО долбит API пока не получит данные"""
        for attempt in range(max_retries):
            try:
                print(f"      🔄 Попытка {attempt + 1}/{max_retries}")
                
                response = requests.get(url, params=params, timeout=45)
                
                if response.status_code == 200:
                    data = response.json()
                    
                    if isinstance(data, dict) and 'error' in data:
                        print(f"      ❌ API ошибка: {data['error']}")
                        if 'rate' in data['error'].lower():
                            print(f"      ⏰ Rate limit, жду 10 сек...")
                            time.sleep(10)
                            continue
                        else:
                            return None
                    
                    print(f"      ✅ Данные получены! ({len(data)} записей)")
                    return data
                
                elif response.status_code == 429:
                    print(f"      ⏰ Rate limit (429), жду 15 сек...")
                    time.sleep(15)
                    continue
                    
                elif response.status_code == 502 or response.status_code == 503:
                    print(f"      🔧 Сервер недоступен ({response.status_code}), жду 5 сек...")
                    time.sleep(5)
                    continue
                    
                else:
                    print(f"      ❌ HTTP {response.status_code}")
                    time.sleep(3)
                    continue
                    
            except requests.exceptions.Timeout:
                print(f"      ⏰ Timeout, жду 5 сек...")
                time.sleep(5)
                continue
                
            except requests.exceptions.ConnectionError:
                print(f"      🔌 Connection error, жду 3 сек...")
                time.sleep(3)
                continue
                
            except Exception as e:
                print(f"      ❌ Ошибка: {e}")
                time.sleep(2)
                continue
        
        print(f"      💀 НЕ СМОГ ПОЛУЧИТЬ ДАННЫЕ ПОСЛЕ {max_retries} ПОПЫТОК!")
        return None

    def collect_solana_transactions_aggressive(self) -> List[Transaction]:
        """АГРЕССИВНО собирает Solana транзакции"""
        print(f"\n🟣 SOLANA: АГРЕССИВНАЯ ОБРАБОТКА {len(self.config['pools']['solana'])} ПУЛОВ")
        
        transactions = []
        
        for i, pool in enumerate(self.config['pools']['solana'], 1):
            print(f"\n[{i}/{len(self.config['pools']['solana'])}] 🎯 ДОЛБИМ: {pool['name']}")
            print(f"    Адрес: {pool['address']}")
            
            url = f"https://api.helius.xyz/v0/addresses/{pool['address']}/transactions"
            params = {'api-key': self.helius_key}
            
            # АГРЕССИВНО долбим API
            data = self.aggressive_api_call(url, params)
            
            if not data:
                print(f"    💀 ПРОПУСКАЕМ ПУЛ {pool['name']} - НЕТ ДАННЫХ")
                continue
            
            # Анализируем полученные данные
            total_swaps = 0
            period_swaps = 0
            period_transactions = []
            
            for tx in data:
                if tx.get('type') != 'SWAP':
                    continue
                    
                total_swaps += 1
                
                timestamp = tx.get('timestamp')
                if not timestamp:
                    continue
                    
                if self.start_timestamp <= timestamp <= self.end_timestamp:
                    period_swaps += 1
                    
                    parsed_tx = self.parse_solana_transaction(tx, pool['address'], pool['name'])
                    if parsed_tx:
                        period_transactions.append(parsed_tx)
                        transactions.append(parsed_tx)
            
            print(f"    📊 РЕЗУЛЬТАТ: {total_swaps} всего swaps, {period_swaps} за 7-8 авг, {len(period_transactions)} обработано")
            
            if period_transactions:
                # Показываем примеры транзакций
                for j, tx in enumerate(period_transactions[:3], 1):
                    print(f"      {j}. ${tx.amount_usd:.2f} - {tx.tx_hash[:16]}...")
            
            # Пауза между пулами
            print(f"    ⏱️  Пауза 2 сек...")
            time.sleep(2)
        
        return transactions

    def parse_solana_transaction(self, tx_data: dict, pool_address: str, pool_name: str) -> Optional[Transaction]:
        """Парсит Solana транзакцию"""
        try:
            signature = tx_data.get('signature', '')
            timestamp = tx_data.get('timestamp', 0)
            
            token_transfers = tx_data.get('tokenTransfers', [])
            amount_usd = 0
            
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                amount = transfer.get('tokenAmount', 0)
                if mint in self.token_prices:
                    usd_value = amount * self.token_prices[mint]
                    amount_usd = max(amount_usd, usd_value)
            
            return Transaction(
                chain='solana',
                pool_address=pool_address,
                pool_name=pool_name,
                tx_hash=signature,
                sender_address=tx_data.get('feePayer', ''),
                amount_usd=round(amount_usd, 2),
                timestamp=timestamp,
                block_number=tx_data.get('slot', 0)
            )
            
        except Exception as e:
            print(f"        ❌ Ошибка парсинга: {e}")
            return None

    def export_to_csv(self, transactions: List[Transaction], filename: str = "dao_pool_transactions_demo.csv"):
        """Экспортирует транзакции в CSV"""
        print(f"\n💾 СОХРАНЯЮ {len(transactions)} ТРАНЗАКЦИЙ В {filename}")
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'chain', 'pool_address', 'pool_name', 'tx_hash', 
                'sender_address', 'amount_usd', 'timestamp', 'block_number'
            ]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            
            writer.writeheader()
            for tx in transactions:
                writer.writerow({
                    'chain': tx.chain,
                    'pool_address': tx.pool_address,
                    'pool_name': tx.pool_name,
                    'tx_hash': tx.tx_hash,
                    'sender_address': tx.sender_address,
                    'amount_usd': tx.amount_usd,
                    'timestamp': tx.timestamp,
                    'block_number': tx.block_number,
                })
        
        return filename

def main():
    print("💀 АГРЕССИВНЫЙ СБОРЩИК ТРАНЗАКЦИЙ DAO ПУЛОВ")
    print("🔥 НЕ ОСТАНОВИТСЯ ПОКА НЕ ПОЛУЧИТ ВСЕ ДАННЫЕ!")
    print("📅 7-8 августа 2025")
    print("=" * 60)
    
    collector = AggressiveTransactionsCollector()
    
    # АГРЕССИВНО собираем Solana (пока только Solana, потом добавлю остальные)
    solana_transactions = collector.collect_solana_transactions_aggressive()
    
    print(f"\n🎯 ФИНАЛЬНЫЙ РЕЗУЛЬТАТ:")
    print(f"   🟣 Solana: {len(solana_transactions)} транзакций")
    
    if solana_transactions:
        # Сохраняем в CSV
        csv_file = collector.export_to_csv(solana_transactions)
        
        # Статистика
        large_txs = [tx for tx in solana_transactions if tx.amount_usd >= 1000]
        medium_txs = [tx for tx in solana_transactions if 100 <= tx.amount_usd < 1000]
        small_txs = [tx for tx in solana_transactions if tx.amount_usd < 100]
        
        print(f"\n💰 СТАТИСТИКА ПО СУММАМ:")
        print(f"   🔥 > $1000: {len(large_txs)} транзакций")
        print(f"   💵 $100-1000: {len(medium_txs)} транзакций")
        print(f"   💴 < $100: {len(small_txs)} транзакций")
        
        # Топ транзакции
        if large_txs:
            top_txs = sorted(large_txs, key=lambda x: x.amount_usd, reverse=True)[:10]
            print(f"\n🏆 ТОП-10 КРУПНЕЙШИХ ТРАНЗАКЦИЙ:")
            for i, tx in enumerate(top_txs, 1):
                date_str = datetime.datetime.fromtimestamp(tx.timestamp).strftime('%m-%d %H:%M')
                print(f"   {i:2d}. ${tx.amount_usd:>10,.2f} - {date_str} - {tx.pool_name} - {tx.tx_hash[:20]}...")
        
        # Статистика по пулам
        pool_stats = {}
        for tx in solana_transactions:
            pool_stats[tx.pool_name] = pool_stats.get(tx.pool_name, 0) + 1
        
        print(f"\n📊 АКТИВНОСТЬ ПО ПУЛАМ:")
        for pool_name, count in sorted(pool_stats.items(), key=lambda x: x[1], reverse=True):
            print(f"   {pool_name}: {count} транзакций")
        
        print(f"\n✅ ГОТОВО! АГРЕССИВНО СОБРАНО И СОХРАНЕНО В {csv_file}")
        
    else:
        print("\n💀 НИ ОДНОЙ ТРАНЗАКЦИИ НЕ НАЙДЕНО!")

if __name__ == "__main__":
    main()
