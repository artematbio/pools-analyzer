#!/usr/bin/env python3
"""
Solana Pool Transactions Collector - фокусированно на Solana
Собирает ВСЕ swap транзакции за 7-8 августа 2025 из Solana пулов
"""

import json
import requests
import csv
import time
import datetime
import os
from typing import List, Dict, Any
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

class SolanaTransactionsCollector:
    def __init__(self):
        load_dotenv()
        
        # Загружаем конфигурацию пулов
        with open('tokens_pools_config.json', 'r') as f:
            self.config = json.load(f)
        
        # Даты для анализа: 7-8 августа 2025
        self.start_timestamp = int(datetime.datetime(2025, 8, 7, 0, 0, 0).timestamp())
        self.end_timestamp = int(datetime.datetime(2025, 8, 9, 0, 0, 0).timestamp())
        
        print(f"📅 Период: 7-8 августа 2025")
        print(f"   Start timestamp: {self.start_timestamp}")
        print(f"   End timestamp: {self.end_timestamp}")
        
        # Helius API
        self.helius_key = os.getenv('HELIUS_API_KEY', 'd4af7b72-f199-4d77-91a9-11d8512c5e42')
        self.helius_url = f'https://mainnet.helius-rpc.com/?api-key={self.helius_key}'
        
        # Цены токенов для USD расчетов (примерные)
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
        
        self.collected_transactions = []

    def get_solana_pool_transactions(self, pool_address: str, pool_name: str) -> List[Transaction]:
        """Получает транзакции пула через Helius API"""
        print(f"🔍 Обрабатываю: {pool_name} ({pool_address})")
        
        transactions = []
        
        try:
            # Helius Enhanced Transaction API
            url = f"https://api.helius.xyz/v0/addresses/{pool_address}/transactions"
            
            params = {
                'api-key': self.helius_key
            }
            
            response = requests.get(url, params=params, timeout=30)
            data = response.json()
            
            if isinstance(data, dict) and 'error' in data:
                print(f"❌ Helius API ошибка: {data['error']}")
                return transactions
            
            swap_count = 0
            period_swaps = 0
            
            for tx in data:
                # Фильтруем только SWAP транзакции
                if tx.get('type') != 'SWAP':
                    continue
                    
                swap_count += 1
                
                # Фильтруем по времени
                timestamp = tx.get('timestamp')
                if not timestamp:
                    continue
                    
                if self.start_timestamp <= timestamp <= self.end_timestamp:
                    period_swaps += 1
                    
                    # Парсим swap данные
                    parsed_tx = self.parse_helius_transaction(tx, pool_address, pool_name)
                    if parsed_tx:
                        transactions.append(parsed_tx)
            
            print(f"   📊 Всего swaps: {swap_count}, за 7-8 авг: {period_swaps}, обработано: {len(transactions)}")
            
        except Exception as e:
            print(f"❌ Ошибка: {e}")
            
        return transactions
    
    def parse_helius_transaction(self, tx_data: dict, pool_address: str, pool_name: str) -> Transaction:
        """Парсит транзакцию из Helius API"""
        try:
            signature = tx_data.get('signature', '')
            timestamp = tx_data.get('timestamp', 0)
            
            # Token transfers для расчета стоимости
            token_transfers = tx_data.get('tokenTransfers', [])
            if not token_transfers:
                return None
            
            # Расчет USD стоимости
            amount_usd = self.calculate_swap_usd_value(token_transfers)
            
            # Адрес отправителя
            sender = tx_data.get('feePayer', '')
            
            return Transaction(
                chain='solana',
                pool_address=pool_address,
                pool_name=pool_name,
                tx_hash=signature,
                sender_address=sender,
                amount_usd=amount_usd,
                timestamp=timestamp,
                block_number=tx_data.get('slot', 0)
            )
            
        except Exception as e:
            print(f"❌ Ошибка парсинга: {e}")
            return None
    
    def calculate_swap_usd_value(self, token_transfers: List[dict]) -> float:
        """Вычисляет USD стоимость swap'а"""
        try:
            max_usd_value = 0
            
            for transfer in token_transfers:
                mint = transfer.get('mint', '')
                amount = transfer.get('tokenAmount', 0)
                
                if mint in self.token_prices:
                    usd_value = amount * self.token_prices[mint]
                    max_usd_value = max(max_usd_value, usd_value)
            
            return round(max_usd_value, 2)
            
        except Exception as e:
            return 0

    def collect_all_solana_transactions(self) -> List[Transaction]:
        """Собирает транзакции со всех Solana пулов"""
        all_transactions = []
        
        solana_pools = self.config['pools']['solana']
        print(f"📋 Обрабатываю {len(solana_pools)} Solana пулов")
        
        for i, pool in enumerate(solana_pools, 1):
            print(f"\n[{i}/{len(solana_pools)}]", end=" ")
            
            pool_transactions = self.get_solana_pool_transactions(
                pool['address'], 
                pool['name']
            )
            
            all_transactions.extend(pool_transactions)
            
            # Пауза между запросами
            time.sleep(1)
        
        return all_transactions

    def export_to_csv(self, transactions: List[Transaction], filename: str = "dao_pool_transactions_demo.csv"):
        """Экспортирует транзакции в CSV файл"""
        print(f"\n💾 Экспортирую {len(transactions)} транзакций в {filename}")
        
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
        
        print(f"✅ CSV файл сохранен: {filename}")
        return filename

def main():
    print("🚀 Solana DAO Pools Transaction Collector")
    print("📅 Период: 7-8 августа 2025")
    print("🎯 Цель: ВСЕ swap транзакции из Solana пулов")
    print()
    
    collector = SolanaTransactionsCollector()
    
    # Тестируем подключение
    try:
        test_payload = {"jsonrpc": "2.0", "id": 1, "method": "getHealth"}
        response = requests.post(collector.helius_url, json=test_payload, timeout=5)
        if response.status_code == 200:
            print("✅ Helius RPC: подключение OK")
        else:
            print(f"❌ Helius RPC: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ Helius RPC: {e}")
    
    print("\n" + "="*60)
    
    # Собираем транзакции
    transactions = collector.collect_all_solana_transactions()
    
    print(f"\n📊 ИТОГОВАЯ СТАТИСТИКА:")
    print(f"   🎯 Всего транзакций за 7-8 августа 2025: {len(transactions)}")
    
    if transactions:
        # Сохраняем в CSV
        csv_file = collector.export_to_csv(transactions)
        
        # Дополнительная статистика
        large_transactions = [tx for tx in transactions if tx.amount_usd >= 1000]
        medium_transactions = [tx for tx in transactions if 100 <= tx.amount_usd < 1000]
        small_transactions = [tx for tx in transactions if tx.amount_usd < 100]
        
        print(f"\n📈 По размерам транзакций:")
        print(f"   💰 > $1000: {len(large_transactions)} транзакций")
        print(f"   💵 $100-1000: {len(medium_transactions)} транзакций")
        print(f"   💴 < $100: {len(small_transactions)} транзакций")
        
        # Топ-5 самых крупных транзакций
        if large_transactions:
            top_transactions = sorted(large_transactions, key=lambda x: x.amount_usd, reverse=True)[:5]
            print(f"\n🏆 ТОП-5 самых крупных транзакций:")
            for i, tx in enumerate(top_transactions, 1):
                print(f"   {i}. ${tx.amount_usd:,.2f} - {tx.pool_name} - {tx.tx_hash[:16]}...")
        
        print(f"\n✅ ГОТОВО! Результаты сохранены в {csv_file}")
        
    else:
        print("\n⚠️  Транзакций за указанный период не найдено")

if __name__ == "__main__":
    main()
