import re
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from decimal import Decimal

class ReportFormatter:
    """
    Formats analysis reports for Telegram delivery
    Generates detailed reports similar to the original text format
    """
    
    def __init__(self):
        self.max_message_length = 4096  # Telegram limit
        
    def format_pool_report(self, report_content: str) -> List[str]:
        """
        Format pool analysis report for Telegram
        Converts detailed text report to Telegram-friendly format
        Returns list of message parts if report is too long
        """
        try:
            # Extract key information from the report
            report_data = self._parse_report_content(report_content)
            
            if not report_data:
                return ["Error: Could not parse pool report"]
            
            # Format the report
            formatted_report = self._build_detailed_report(report_data)
            
            # Split into messages if too long
            messages = self._split_message(formatted_report)
            
            return messages if messages else ["Error: Empty report"]
            
        except Exception as e:
            return [f"Error formatting report: {str(e)}"]
    
    def _parse_report_content(self, content: str) -> Optional[Dict]:
        """Parse the text report content and extract structured data"""
        try:
            data = {
                'wallet': '',
                'total_positions': 0,
                'total_value': 0.0,
                'pools': [],
                'generation_time': ''
            }
            
            # Extract wallet address - updated for English format
            wallet_match = re.search(r'Wallet:\s*([A-Za-z0-9]+)', content)
            if not wallet_match:
                # Fallback to Russian format
                wallet_match = re.search(r'Анализируемый кошелек:\s*([A-Za-z0-9]+)', content)
            if wallet_match:
                data['wallet'] = wallet_match.group(1)
            
            # Extract total statistics - updated for English format
            total_pos_match = re.search(r'Total Positions:\s*(\d+)', content)
            if not total_pos_match:
                # Fallback to Russian format
                total_pos_match = re.search(r'Всего CLMM позиций:\s*(\d+)', content)
            if total_pos_match:
                data['total_positions'] = int(total_pos_match.group(1))
            
            # Extract total value - try both English and Russian formats
            total_val_match = re.search(r'Total Value:\s*\$([0-9,]+\.?\d*)', content)
            if not total_val_match:
                total_val_match = re.search(r'Общая стоимость всех позиций:\s*\$([0-9,]+\.?\d*)', content)
            if total_val_match:
                data['total_value'] = float(total_val_match.group(1).replace(',', ''))
            
            # Extract generation time - updated for English format
            time_match = re.search(r'Generated:\s*([0-9-]+\s+[0-9:]+)', content)
            if not time_match:
                # Fallback to Russian format
                time_match = re.search(r'Дата формирования:\s*([0-9.]+\s+[0-9:]+)', content)
            if time_match:
                data['generation_time'] = time_match.group(1)
            
            # Extract pool data - updated for English format
            pool_pattern = r'POOL \d+:\s*([^-\n]+).*?(?=POOL \d+:|SUMMARY:|$)'
            pool_matches = re.findall(pool_pattern, content, re.DOTALL)
            
            # If no English pools found, try Russian format
            if not pool_matches:
                pool_pattern = r'--- АНАЛИЗ ПУЛА: ([^(]+)\s*\(([^)]+)\) ---(.*?)(?=--- АНАЛИЗ ПУЛА:|ДРУГИЕ ПУЛЫ|ОБЩАЯ СТАТИСТИКА|$)'
                pool_matches_ru = re.findall(pool_pattern, content, re.DOTALL)
                for pool_name, pool_id, pool_content in pool_matches_ru:
                    pool_data = self._parse_pool_section_russian(pool_name.strip(), pool_id.strip(), pool_content)
                    if pool_data:
                        data['pools'].append(pool_data)
            else:
                # Parse English format pools
                for i, pool_match in enumerate(pool_matches):
                    pool_name = pool_match.strip()
                    # Extract the pool section content
                    pool_section_pattern = f'POOL {i+1}:\\s*{re.escape(pool_name)}(.*?)(?=POOL \\d+:|SUMMARY:|$)'
                    pool_content_match = re.search(pool_section_pattern, content, re.DOTALL)
                    if pool_content_match:
                        pool_content = pool_content_match.group(1)
                        pool_data = self._parse_pool_section_english(pool_name, pool_content)
                        if pool_data:
                            data['pools'].append(pool_data)
            
            return data
            
        except Exception as e:
            print(f"Error parsing report: {e}")
            return None
    
    def _parse_pool_section(self, pool_name: str, pool_id: str, content: str) -> Optional[Dict]:
        """Parse individual pool section"""
        try:
            pool_data = {
                'name': pool_name,
                'id': pool_id,
                'tvl': 0.0,
                'volume_24h': 0.0,
                'volume_7d': 0.0,
                'positions_count': 0,
                'positions_value': 0.0,
                'pending_yield': 0.0,
                'daily_volumes': [],
                'positions': []
            }
            
            # Extract TVL
            tvl_match = re.search(r'Общая ликвидность пула \(TVL\):\s*\$([0-9,]+\.?\d*)', content)
            if tvl_match:
                pool_data['tvl'] = float(tvl_match.group(1).replace(',', ''))
            
            # Extract volumes
            vol_24h_match = re.search(r'Объем торгов за 24 часа:\s*\$([0-9,]+\.?\d*)', content)
            if vol_24h_match:
                pool_data['volume_24h'] = float(vol_24h_match.group(1).replace(',', ''))
            
            vol_7d_match = re.search(r'Объем торгов за 7 дней:\s*\$([0-9,]+\.?\d*)', content)
            if vol_7d_match:
                pool_data['volume_7d'] = float(vol_7d_match.group(1).replace(',', ''))
            
            # Extract position count and value
            pos_count_match = re.search(r'Активные позиции:\s*(\d+)', content)
            if pos_count_match:
                pool_data['positions_count'] = int(pos_count_match.group(1))
            
            pos_value_match = re.search(r'Общая стоимость позиций:\s*~?\$([0-9,]+\.?\d*)', content)
            if pos_value_match:
                pool_data['positions_value'] = float(pos_value_match.group(1).replace(',', ''))
            
            # Extract daily volumes
            daily_pattern = r'- (\d{4}-\d{2}-\d{2}):\s*\$([0-9,]+\.?\d*)'
            daily_matches = re.findall(daily_pattern, content)
            for date, volume in daily_matches:
                pool_data['daily_volumes'].append({
                    'date': date,
                    'volume': float(volume.replace(',', ''))
                })
            
            # Extract positions details
            pos_pattern = r'(\d+)\.\s*NFT:\s*([A-Za-z0-9]+)\s*\n\s*Стоимость:\s*\$([0-9,]+\.?\d*)\s*\n.*?Общий Pending Yield:\s*~?\$([0-9,]+\.?\d*)'
            pos_matches = re.findall(pos_pattern, content, re.DOTALL)
            
            total_yield = 0.0
            for pos_num, nft_id, value, yield_amount in pos_matches:
                yield_val = float(yield_amount.replace(',', ''))
                total_yield += yield_val
                
                pool_data['positions'].append({
                    'number': int(pos_num),
                    'nft_id': nft_id,
                    'value': float(value.replace(',', '')),
                    'yield': yield_val
                })
            
            pool_data['pending_yield'] = total_yield
            
            return pool_data
            
        except Exception as e:
            print(f"Error parsing pool section: {e}")
            return None
    
    def _build_detailed_report(self, data: Dict) -> str:
        """Build detailed report similar to original format"""
        report = []
        
        # Header
        report.append("RAYDIUM POOLS ANALYSIS REPORT")
        report.append("=" * 40)  # Сокращаем разделитель
        report.append("")
        
        # Summary
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        report.append(f"Generated: {current_time}")
        report.append(f"Wallet: {data['wallet']}")
        report.append(f"Total Positions: {data['total_positions']}")
        report.append(f"Total Value: ${data['total_value']:,.2f}")
        report.append("")
        report.append("-" * 40)  # Сокращаем разделитель
        report.append("")
        
        # Pool details
        for i, pool in enumerate(data['pools'], 1):
            report.append(f"POOL {i}: {pool['name']}")
            
            # Basic metrics - сокращаем название
            report.append("TVL & VOLUMES:")
            report.append(f"  TVL: ${pool['tvl']:,.2f}")
            report.append(f"  24h Vol: ${pool['volume_24h']:,.2f}")
            
            # Daily volumes (last 7 days) - сокращаем заголовок
            if pool['daily_volumes']:
                report.append("Daily volumes (7d):")
                for dv in pool['daily_volumes'][-7:]:
                    report.append(f"  {dv['date']}: ${dv['volume']:,.2f}")
            
            # Positions
            report.append("POSITIONS:")
            report.append(f"  Active: {pool['positions_count']}")  # Сокращаем
            report.append(f"  Value: ${pool['positions_value']:,.2f}")   # Сокращаем
            report.append(f"  Yield: ${pool['pending_yield']:,.2f}")     # Сокращаем
            
            # Position details
            if pool['positions']:
                report.append("Details:")  # Сокращаем заголовок
                for pos in pool['positions']:
                    # Убираем NFT из описания позиций для экономии места
                    report.append(f"  {pos['number']}. {pos['nft_id']}")
                    report.append(f"     Value: ${pos['value']:,.2f}")
                    report.append(f"     Yield: ${pos['yield']:,.2f}")
            
            report.append("-" * 25)  # Сокращаем разделитель
            report.append("")
        
        # Footer - сокращаем
        report.append("SUMMARY:")
        report.append(f"Portfolio: ${data['total_value']:,.2f}")  # Сокращаем
        report.append(f"Positions: {data['total_positions']}")    # Сокращаем
        total_yield = sum(pool['pending_yield'] for pool in data['pools'])
        report.append(f"Total yield: ${total_yield:,.2f}")        # Сокращаем
        report.append("")
        report.append("Next: Automated schedule")  # Сокращаем
        
        return "\n".join(report)
    
    def _split_message(self, message: str) -> List[str]:
        """Split long message into multiple parts"""
        if len(message) <= self.max_message_length:
            return [message]
        
        messages = []
        lines = message.split('\n')
        current_message = ""
        
        for line in lines:
            if len(current_message + line + '\n') > self.max_message_length:
                if current_message:
                    messages.append(current_message.strip())
                    current_message = line + '\n'
                else:
                    # Line too long, split it
                    messages.append(line[:self.max_message_length])
                    current_message = line[self.max_message_length:] + '\n'
            else:
                current_message += line + '\n'
        
        if current_message:
            messages.append(current_message.strip())
        
        return messages
    
    def format_phi_analysis(self, analysis_content: str) -> str:
        """Format PHI analysis for Telegram"""
        try:
            # Extract key insights from PHI analysis
            lines = analysis_content.split('\n')
            formatted_lines = []
            
            formatted_lines.append("WEEKLY PHI ANALYSIS")
            formatted_lines.append("=" * 30)
            formatted_lines.append("")
            
            # Add timestamp
            current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            formatted_lines.append(f"Generated: {current_time}")
            formatted_lines.append("")
            
            # Process content (remove excessive formatting, keep key insights)
            in_analysis = False
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # Skip header lines
                if any(skip in line for skip in ['НЕДЕЛЬНЫЙ АНАЛИЗ', 'Дата анализа:', 'Проанализировано дней:', '=']):
                    continue
                
                # Start of actual analysis
                if any(start in line for start in ['АНАЛИЗ', 'ВЫВОДЫ', 'ТРЕНДЫ', 'АНОМАЛИИ']):
                    in_analysis = True
                    formatted_lines.append(line.upper())
                    formatted_lines.append("")
                    continue
                
                if in_analysis:
                    # Clean up the line
                    clean_line = re.sub(r'[🔍📊📈📉💰⚠️✅❌🎯🚫]', '', line)
                    clean_line = clean_line.strip()
                    if clean_line and len(clean_line) > 10:
                        formatted_lines.append(clean_line)
            
            result = '\n'.join(formatted_lines)
            
            # Split if too long
            messages = self._split_message(result)
            return messages[0] if messages else "PHI analysis completed"
            
        except Exception as e:
            return f"Error formatting PHI analysis: {str(e)}"
    
    def format_status_report(self, status_data: Dict) -> str:
        """Format system status report"""
        try:
            lines = []
            lines.append("SYSTEM STATUS REPORT")
            lines.append("=" * 25)
            lines.append("")
            
            current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            lines.append(f"Timestamp: {current_time}")
            lines.append("")
            
            # Overall status
            overall = status_data.get('overall_status', 'unknown')
            lines.append(f"Overall Status: {overall.upper()}")
            lines.append("")
            
            # Services status
            services = status_data.get('services', {})
            if services:
                lines.append("SERVICES:")
                for service, status in services.items():
                    lines.append(f"  {service}: {status}")
                lines.append("")
            
            # Last analysis
            last_analysis = status_data.get('last_successful_analysis')
            if last_analysis:
                lines.append(f"Last analysis: {last_analysis.get('type', 'unknown')}")
                lines.append(f"Time: {last_analysis.get('timestamp', 'unknown')}")
                lines.append("")
            
            # Next scheduled tasks
            next_tasks = status_data.get('next_scheduled_tasks', [])
            if next_tasks:
                lines.append("NEXT SCHEDULED TASKS:")
                for task in next_tasks[:3]:
                    lines.append(f"  {task['name']}: {task['time']}")
                lines.append("")
            
            # Uptime
            uptime_start = status_data.get('uptime_start')
            if uptime_start:
                lines.append(f"System started: {uptime_start}")
            
            return '\n'.join(lines)
            
        except Exception as e:
            return f"Error formatting status: {str(e)}"
    
    def format_error_alert(self, error_type: str, error_message: str, context: str = "") -> str:
        """Format error alert message"""
        lines = []
        lines.append("ERROR ALERT")
        lines.append("=" * 15)
        lines.append("")
        
        current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
        lines.append(f"Timestamp: {current_time}")
        lines.append(f"Error Type: {error_type}")
        lines.append("")
        lines.append("Message:")
        lines.append(error_message)
        
        if context:
            lines.append("")
            lines.append("Context:")
            lines.append(context)
        
        return '\n'.join(lines)
    
    def _extract_total_value(self, report_content: str) -> float:
        """Extract total portfolio value from report"""
        try:
            match = re.search(r'Общая стоимость всех позиций:\s*\$([0-9,]+\.?\d*)', report_content)
            if match:
                return float(match.group(1).replace(',', ''))
            return 0.0
        except:
            return 0.0

    def _parse_pool_section_english(self, pool_name: str, content: str) -> Optional[Dict]:
        """Parse individual pool section in English format"""
        try:
            pool_data = {
                'name': pool_name,
                'id': '',
                'tvl': 0.0,
                'volume_24h': 0.0,
                'volume_7d': 0.0,
                'positions_count': 0,
                'positions_value': 0.0,
                'pending_yield': 0.0,
                'daily_volumes': [],
                'positions': []
            }
            
            # Extract TVL and volumes from English format
            tvl_match = re.search(r'Pool TVL:\s*\$([0-9,]+\.?\d*)', content)
            if not tvl_match:
                tvl_match = re.search(r'TVL:\s*\$([0-9,]+\.?\d*)', content)
            if tvl_match:
                pool_data['tvl'] = float(tvl_match.group(1).replace(',', ''))
            
            vol_24h_match = re.search(r'24h Volume:\s*\$([0-9,]+\.?\d*)', content)
            if not vol_24h_match:
                vol_24h_match = re.search(r'24h Vol:\s*\$([0-9,]+\.?\d*)', content)
            if vol_24h_match:
                pool_data['volume_24h'] = float(vol_24h_match.group(1).replace(',', ''))
            
            # Extract position count and value from English format
            pos_count_match = re.search(r'Active positions:\s*(\d+)', content)
            if not pos_count_match:
                pos_count_match = re.search(r'Active:\s*(\d+)', content)
            if pos_count_match:
                pool_data['positions_count'] = int(pos_count_match.group(1))
            
            pos_value_match = re.search(r'Total position value:\s*\$([0-9,]+\.?\d*)', content)
            if not pos_value_match:
                pos_value_match = re.search(r'Value:\s*\$([0-9,]+\.?\d*)', content)
            if pos_value_match:
                pool_data['positions_value'] = float(pos_value_match.group(1).replace(',', ''))
            
            # Extract pending yield from English format
            yield_match = re.search(r'Pending yield \(fees\):\s*\$([0-9,]+\.?\d*)', content)
            if not yield_match:
                yield_match = re.search(r'Yield:\s*\$([0-9,]+\.?\d*)', content)
            if yield_match:
                pool_data['pending_yield'] = float(yield_match.group(1).replace(',', ''))
            
            # Extract daily volumes
            daily_pattern = r'(\d{4}-\d{2}-\d{2}):\s*\$([0-9,]+\.?\d*)'
            daily_matches = re.findall(daily_pattern, content)
            for date, volume in daily_matches:
                pool_data['daily_volumes'].append({
                    'date': date,
                    'volume': float(volume.replace(',', ''))
                })
            
            # Extract positions details from English format
            pos_pattern = r'(\d+)\.\s*NFT:\s*([A-Za-z0-9]+).*?Value:\s*\$([0-9,]+\.?\d*).*?Fees:\s*\$([0-9,]+\.?\d*)'
            pos_matches = re.findall(pos_pattern, content, re.DOTALL)
            
            for pos_num, nft_id, value, yield_amount in pos_matches:
                yield_val = float(yield_amount.replace(',', ''))
                
                pool_data['positions'].append({
                    'number': int(pos_num),
                    'nft_id': nft_id,
                    'value': float(value.replace(',', '')),
                    'yield': yield_val
                })
            
            return pool_data
            
        except Exception as e:
            print(f"Error parsing English pool section: {e}")
            return None

    def _parse_pool_section_russian(self, pool_name: str, pool_id: str, content: str) -> Optional[Dict]:
        """Parse individual pool section in Russian format (original method)"""
        try:
            pool_data = {
                'name': pool_name,
                'id': pool_id,
                'tvl': 0.0,
                'volume_24h': 0.0,
                'volume_7d': 0.0,
                'positions_count': 0,
                'positions_value': 0.0,
                'pending_yield': 0.0,
                'daily_volumes': [],
                'positions': []
            }
            
            # Extract TVL
            tvl_match = re.search(r'Общая ликвидность пула \(TVL\):\s*\$([0-9,]+\.?\d*)', content)
            if tvl_match:
                pool_data['tvl'] = float(tvl_match.group(1).replace(',', ''))
            
            # Extract volumes
            vol_24h_match = re.search(r'Объем торгов за 24 часа:\s*\$([0-9,]+\.?\d*)', content)
            if vol_24h_match:
                pool_data['volume_24h'] = float(vol_24h_match.group(1).replace(',', ''))
            
            vol_7d_match = re.search(r'Объем торгов за 7 дней:\s*\$([0-9,]+\.?\d*)', content)
            if vol_7d_match:
                pool_data['volume_7d'] = float(vol_7d_match.group(1).replace(',', ''))
            
            # Extract position count and value
            pos_count_match = re.search(r'Активные позиции:\s*(\d+)', content)
            if pos_count_match:
                pool_data['positions_count'] = int(pos_count_match.group(1))
            
            pos_value_match = re.search(r'Общая стоимость позиций:\s*~?\$([0-9,]+\.?\d*)', content)
            if pos_value_match:
                pool_data['positions_value'] = float(pos_value_match.group(1).replace(',', ''))
            
            # Extract daily volumes
            daily_pattern = r'- (\d{4}-\d{2}-\d{2}):\s*\$([0-9,]+\.?\d*)'
            daily_matches = re.findall(daily_pattern, content)
            for date, volume in daily_matches:
                pool_data['daily_volumes'].append({
                    'date': date,
                    'volume': float(volume.replace(',', ''))
                })
            
            # Extract positions details
            pos_pattern = r'(\d+)\.\s*NFT:\s*([A-Za-z0-9]+)\s*\n\s*Стоимость:\s*\$([0-9,]+\.?\d*)\s*\n.*?Общий Pending Yield:\s*~?\$([0-9,]+\.?\d*)'
            pos_matches = re.findall(pos_pattern, content, re.DOTALL)
            
            total_yield = 0.0
            for pos_num, nft_id, value, yield_amount in pos_matches:
                yield_val = float(yield_amount.replace(',', ''))
                total_yield += yield_val
                
                pool_data['positions'].append({
                    'number': int(pos_num),
                    'nft_id': nft_id,
                    'value': float(value.replace(',', '')),
                    'yield': yield_val
                })
            
            pool_data['pending_yield'] = total_yield
            
            return pool_data
            
        except Exception as e:
            print(f"Error parsing Russian pool section: {e}")
            return None

# Utility functions for quick formatting
def format_number(value: float, precision: int = 2) -> str:
    """Format number with thousands separators"""
    if precision == 0:
        return f"{value:,.0f}"
    else:
        return f"{value:,.{precision}f}"

def format_percentage(value: float, precision: int = 1) -> str:
    """Format percentage with + or - sign"""
    return f"{value:+.{precision}f}%"

def format_currency(value: float, symbol: str = "$", precision: int = 2) -> str:
    """Format currency with symbol"""
    return f"{symbol}{value:,.{precision}f}"

# Example usage and testing
if __name__ == "__main__":
    formatter = ReportFormatter()
    
    # Test with sample data
    sample_report = """
    Общая стоимость всех позиций: $324,874.75
    Всего CLMM позиций: 8
    
    --- АНАЛИЗ ПУЛА: BIO/SPINE (Pool ID: 5LZawn1Pqv8Jd96nq5GPVZAz9a7jZWFD66A5JvUodRNL) ---
    Общая ликвидность пула (TVL): $1,234,567
    Объем торгов за 24 часа: $45,678
    Активные позиции: 3
    Общая стоимость позиций: $12,345
    Общий Pending Yield: $123.45
    """
    
    formatted = formatter.format_pool_report(sample_report)
    print("=== FORMATTED REPORT ===")
    for part in formatted:
        print(part)
    
    # Test error formatting
    error_msg = formatter.format_error_alert("Pool Analysis", "Connection timeout", "API rate limit exceeded")
    print("\n=== ERROR ALERT ===")
    print(error_msg) 