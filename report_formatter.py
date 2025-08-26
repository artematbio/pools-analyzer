import re
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from decimal import Decimal

def _format_tvl_with_change(pool_tvl: float, pool_address: str, network: str) -> str:
    """Форматирует TVL с индикатором изменения если оно больше 5%"""
    # Безопасное преобразование pool_tvl в число
    try:
        if isinstance(pool_tvl, str):
            # Удаляем символы валют и форматирования
            clean_tvl = pool_tvl.replace('$', '').replace(',', '').replace('N/A', '0')
            pool_tvl_num = float(clean_tvl)
        else:
            pool_tvl_num = float(pool_tvl) if pool_tvl is not None else 0
    except (ValueError, TypeError):
        pool_tvl_num = 0
    
    if pool_tvl_num <= 0:
        return "  📊 Pool TVL: N/A"
    
    try:
        from database_handler import supabase_handler
        tvl_change = supabase_handler.calculate_tvl_change_indicator(pool_tvl, pool_address, network)
        return f"  📊 Pool TVL: ${pool_tvl_num:,.2f}{tvl_change}"
    except Exception as e:
        return f"  📊 Pool TVL: ${pool_tvl_num:,.2f}"

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
            total_val_match = re.search(r'Total Portfolio Value:\s*\$([0-9,]+\.?\d*)', content)
            if not total_val_match:
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
            
            # Цены токенов
            if pool.get('token_prices'):
                report.append("TOKEN PRICES:")
                for token_symbol, token_price in pool['token_prices'].items():
                    report.append(f"  {token_symbol}: ${token_price:,.6f}")
                report.append("")
            
            # Basic metrics - сокращаем название
            report.append("TVL & VOLUMES:")
            report.append(f"  TVL: ${pool['tvl']:,.2f}")
            
            # TVL изменение
            if pool.get('tvl_change_percent') is not None:
                change_symbol = "+" if pool['tvl_change_percent'] > 0 else ""
                report.append(f"  TVL change %: {change_symbol}{pool['tvl_change_percent']:.2f}%")
            else:
                report.append(f"  TVL change %: N/A")
            
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
        """Format error alert for Telegram"""
        alert_text = f"""
❌ <b>ERROR: {error_type}</b>

{error_message}

<i>Context: {context}</i>
<i>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>
"""
        return alert_text.strip()

    def format_portfolio_change_alert(self, previous_value: float, current_value: float, change_percent: float) -> str:
        """Format portfolio change alert for Telegram"""
        change_amount = current_value - previous_value
        change_symbol = "📈" if change_amount > 0 else "📉"
        change_sign = "+" if change_amount > 0 else ""
        
        alert_text = f"""
{change_symbol} <b>PORTFOLIO VALUE CHANGE</b>

Previous: ${previous_value:,.2f}
Current: ${current_value:,.2f}
Change: {change_sign}${change_amount:,.2f} ({change_percent:+.1f}%)

<i>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>
"""
        return alert_text.strip()

    def format_out_of_range_alert(self, out_of_range_positions: list) -> str:
        """Format out of range positions alert for Telegram"""
        if not out_of_range_positions:
            return ""
        
        alert_text = f"""
⚠️ <b>OUT OF RANGE POSITIONS ALERT</b>

{len(out_of_range_positions)} position(s) are currently out of range:

"""
        
        for pos in out_of_range_positions:
            pool_name = pos.get('pool_name', 'Unknown Pool')
            
            # Safe conversion to float for formatting
            try:
                position_value = float(pos.get('position_value_usd', 0))
            except (ValueError, TypeError):
                position_value = 0.0
            
            try:
                fees_usd = float(pos.get('fees_usd', 0))
            except (ValueError, TypeError):
                fees_usd = 0.0
            
            position_mint = pos.get('position_mint', 'N/A')[:8] + "..."
            
            alert_text += f"📍 <b>{pool_name}</b>\n"
            alert_text += f"   NFT: {position_mint}\n"
            alert_text += f"   Value: ${position_value:,.2f}\n"
            alert_text += f"   Fees: ${fees_usd:,.2f}\n"
            
            # Add range information if available
            if 'tick_lower' in pos and 'tick_upper' in pos and 'current_price' in pos:
                try:
                    # Get price range information
                    tick_lower = pos.get('tick_lower')
                    tick_upper = pos.get('tick_upper')
                    current_price = float(pos.get('current_price', 0))
                    
                    # For Solana positions, we need to calculate actual price range
                    # Using the calculate_price_range function from positions module
                    from positions import get_price_from_tick
                    from decimal import Decimal
                    
                    # Get decimals from position data, fallback to standard Solana decimals (9,9)
                    decimals0 = pos.get('decimals0', 9)
                    decimals1 = pos.get('decimals1', 9)
                    
                    price_lower = float(get_price_from_tick(tick_lower, decimals0, decimals1))
                    price_upper = float(get_price_from_tick(tick_upper, decimals0, decimals1))
                    
                    # Format range with proper thousands separators
                    range_info = format_price_range(price_lower, price_upper, current_price, precision=6)
                    alert_text += f"   {range_info}\n"
                    
                except Exception as e:
                    # Fallback to tick range if price calculation fails
                    alert_text += f"   Range: {tick_lower} to {tick_upper} ticks\n"
            
            alert_text += "\n"
        
        alert_text += f"<i>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
        
        return alert_text.strip()
    
    def format_range_proximity_alert(self, approaching_positions: list) -> str:
        """Format range proximity alert for Telegram"""
        if not approaching_positions:
            return ""
        
        alert_text = f"""🔄 <b>RANGE PROXIMITY WARNING</b>

{len(approaching_positions)} position(s) are approaching range boundaries (within 5%):

"""
        
        for pos in approaching_positions:
            pool_name = pos.get('pool_name', 'Unknown Pool')
            
            # Safe conversion to float for formatting
            try:
                position_value = float(pos.get('position_value_usd', 0))
            except (ValueError, TypeError):
                position_value = 0.0
            
            try:
                fees_usd = float(pos.get('fees_usd', 0))
            except (ValueError, TypeError):
                fees_usd = 0.0
            
            position_mint = pos.get('position_mint', 'N/A')[:8] + "..."
            proximity_info = pos.get('proximity_info', {})
            
            alert_text += f"📍 <b>{pool_name}</b>\n"
            alert_text += f"   NFT: {position_mint}\n"
            alert_text += f"   Value: ${position_value:,.2f}\n"
            alert_text += f"   Fees: ${fees_usd:,.2f}\n"
            
            # Add proximity information
            proximity_status = proximity_info.get('proximity_status', 'unknown')
            distance_lower = proximity_info.get('distance_to_lower_percent')
            distance_upper = proximity_info.get('distance_to_upper_percent')
            
            if proximity_status == 'approaching_lower_bound' and distance_lower is not None:
                alert_text += f"   ⚠️ <b>Approaching LOWER bound</b>: {distance_lower:.1f}% from edge\n"
            elif proximity_status == 'approaching_upper_bound' and distance_upper is not None:
                alert_text += f"   ⚠️ <b>Approaching UPPER bound</b>: {distance_upper:.1f}% from edge\n"
            elif proximity_status == 'narrow_range_warning':
                alert_text += f"   ⚠️ <b>Very narrow range</b>: {distance_lower:.1f}% | {distance_upper:.1f}%\n"
            else:
                alert_text += f"   ⚠️ Range proximity warning\n"
            
            # Add range information if available
            if 'tick_lower' in pos and 'tick_upper' in pos and 'current_price' in pos:
                try:
                    # Get price range information
                    tick_lower = pos.get('tick_lower')
                    tick_upper = pos.get('tick_upper')
                    current_price = float(pos.get('current_price', 0))
                    
                    # For Solana positions, we need to calculate actual price range
                    # Using the calculate_price_range function from positions module
                    from positions import get_price_from_tick
                    from decimal import Decimal
                    
                    # Get decimals from position data, fallback to standard decimals
                    decimals0 = pos.get('decimals0', 9)
                    decimals1 = pos.get('decimals1', 9)
                    
                    price_lower = float(get_price_from_tick(tick_lower, decimals0, decimals1))
                    price_upper = float(get_price_from_tick(tick_upper, decimals0, decimals1))
                    
                    # Format range with proper thousands separators
                    range_info = format_price_range(price_lower, price_upper, current_price, precision=6)
                    alert_text += f"   {range_info}\n"
                    
                except Exception as e:
                    # Fallback to tick range if price calculation fails
                    alert_text += f"   Range: {tick_lower} to {tick_upper} ticks\n"
            
            alert_text += "\n"
        
        alert_text += f"💡 <b>Recommendation:</b> Monitor these positions closely and consider adjusting ranges if needed.\n\n"
        alert_text += f"<i>Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"
        
        return alert_text.strip()
    
    def _extract_total_value(self, report_content: str) -> float:
        """Extract total portfolio value from report"""
        try:
            match = re.search(r'Total Portfolio Value:\s*\$([0-9,]+\.?\d*)', report_content)
            if not match:
                match = re.search(r'Общая стоимость всех позиций:\s*\$([0-9,]+\.?\d*)', report_content)
            if match:
                return float(match.group(1).replace(',', ''))
            return 0.0
        except Exception:
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
            
            # Extract positions details from English format - updated to capture Status
            pos_pattern = r'(\d+)\.\s*NFT:\s*([A-Za-z0-9]+).*?Value:\s*\$([0-9,]+\.?\d*).*?Fees:\s*\$([0-9,]+\.?\d*).*?Status:\s*([✅❌])\s*(.*?)(?=\n|$)'
            pos_matches = re.findall(pos_pattern, content, re.DOTALL)
            
            for pos_num, nft_id, value, yield_amount, status_emoji, status_text in pos_matches:
                yield_val = float(yield_amount.replace(',', ''))
                
                # Определяем in_range статус из emoji
                in_range = status_emoji == "✅"
                
                pool_data['positions'].append({
                    'number': int(pos_num),
                    'nft_id': nft_id,
                    'value': float(value.replace(',', '')),
                    'yield': yield_val,
                    'in_range': in_range,
                    'status_emoji': status_emoji,
                    'status_text': status_text.strip()
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

    def format_multichain_report(self, multichain_data: Dict[str, Any]) -> List[str]:
        """
        Форматирует мульти-чейн отчет для Telegram
        Включает данные Solana, Ethereum и Base
        
        Args:
            multichain_data: {
                'solana': solana_report_content,
                'ethereum': ethereum_positions_list, 
                'base': base_positions_list,
                'summary': total_stats
            }
        """
        try:
            report_parts = []
            
            # Заголовок
            current_time = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            header = [
                "🌐 MULTI-CHAIN PORTFOLIO REPORT",
                "=" * 40,
                "",
                f"📅 Generated: {current_time}",
                f"🔗 Networks: Solana • Ethereum • Base",
                ""
            ]
            
            # Общая статистика
            summary = multichain_data.get('summary', {})
            total_value = summary.get('total_value_usd', 0)
            total_positions = summary.get('total_positions', 0)
            networks_count = summary.get('networks_active', 0)
            
            summary_section = [
                "📊 PORTFOLIO SUMMARY:",
                f"💰 Total Value: ${total_value:,.2f}",
                f"📍 Total Positions: {total_positions}",
                f"🌐 Active Networks: {networks_count}",
                "",
                "-" * 40,
                ""
            ]
            
            # Объединяем заголовок и статистику
            main_report = header + summary_section
            
            # === SOLANA SECTION ===
            solana_data = multichain_data.get('solana')
            if solana_data:
                main_report.extend([
                    "🟣 SOLANA POOLS (Raydium)",
                    "=" * 30,
                    ""
                ])
                
                # Форматируем Solana отчет (используем существующий метод)
                if isinstance(solana_data, str):
                    # Если это текстовый отчет, парсим его
                    solana_parsed = self._parse_report_content(solana_data)
                    if solana_parsed:
                        solana_formatted = self._format_solana_section(solana_parsed)
                        main_report.extend(solana_formatted)
                elif isinstance(solana_data, dict):
                    # Если уже структурированные данные
                    solana_formatted = self._format_solana_section(solana_data)
                    main_report.extend(solana_formatted)
                
                main_report.extend(["", "-" * 30, ""])
            
            # === ETHEREUM SECTION ===
            ethereum_positions = multichain_data.get('ethereum', [])
            if ethereum_positions:
                ethereum_section = self._format_ethereum_section(ethereum_positions)
                main_report.extend(ethereum_section)
                main_report.extend(["", "-" * 30, ""])
            
            # === BASE SECTION ===
            base_positions = multichain_data.get('base', [])
            if base_positions:
                base_section = self._format_base_section(base_positions)
                main_report.extend(base_section)
                main_report.extend(["", "-" * 30, ""])
            
            # === FOOTER ===
            footer = [
                "⏰ Next automated update in 12h"
            ]
            
            main_report.extend(footer)
            
            # Объединяем в строку и разбиваем на части
            full_report = "\n".join(main_report)
            report_parts = self._split_message(full_report)
            
            return report_parts
            
        except Exception as e:
            return [f"❌ Error formatting multi-chain report: {str(e)}"]
    
    def _format_solana_section(self, solana_data: Dict) -> List[str]:
        """Форматирует секцию Solana для мульти-чейн отчета"""
        section = []
        
        try:
            # ✅ ИСПРАВЛЕНИЕ: Проверяем разные названия ключей
            pools = solana_data.get('pools_data', solana_data.get('pools', []))
            
            if not pools:
                return ["No Solana positions found", ""]
            
            # Суммарная статистика Solana
            total_solana_value = sum(pool.get('positions_value', 0) for pool in pools)
            total_solana_positions = sum(pool.get('positions_count', 0) for pool in pools)
            total_solana_yield = sum(pool.get('pending_yield', 0) for pool in pools)
            
            section.extend([
                f"💰 Solana Positions: ${total_solana_value:,.2f}",
                f"📍 Positions: {total_solana_positions}",
                f"🎁 Pending Yield: ${total_solana_yield:,.2f}",
                ""
            ])
            
            # Все пулы Solana с деталями позиций
            sorted_pools = sorted(pools, key=lambda x: x.get('positions_value', 0), reverse=True)
            
            section.append("🏊 POOLS:")
            for pool in sorted_pools:
                pool_name = pool.get('name', 'Unknown')
                pool_value = pool.get('positions_value', 0)
                pool_count = pool.get('positions_count', 0)
                pool_tvl = pool.get('tvl', 0)
                pool_yield = pool.get('pending_yield', 0)
                
                # Заголовок пула с TVL
                section.append(f"• {pool_name}")
                # Для Solana пулов используем ID пула как адрес
                pool_address = pool.get('id', '')
                section.append(_format_tvl_with_change(pool_tvl, pool_address, "solana"))
                section.append(f"  💰 Our positions: ${pool_value:,.2f} ({pool_count} pos)")
                section.append(f"  🎁 Yield: ${pool_yield:,.2f}")
                
                # Детали позиций
                positions = pool.get('positions', [])
                if positions:
                    section.append("  📍 Positions:")
                    for pos in positions:
                        # ✅ ИСПРАВЛЕНИЕ: Используем правильные поля из positions.py
                        pos_value_str = pos.get('position_value_usd_str', pos.get('position_value_usd', pos.get('position_value', '0')))
                        try:
                            pos_value = float(pos_value_str)
                        except (ValueError, TypeError):
                            pos_value = 0.0
                            
                        # Для fees используем разные источники
                        pos_yield_str = pos.get('total_pending_yield_usd_str', pos.get('unclaimed_fees_total_usd_str', pos.get('fees_usd', '0')))
                        try:
                            pos_yield = float(pos_yield_str)
                        except (ValueError, TypeError):
                            pos_yield = 0.0
                        nft_id = pos.get('position_mint', pos.get('nft_id', 'Unknown'))
                        
                        # Определяем статус in_range из данных позиции
                        in_range_status = "in range"  # Default для Solana позиций
                        range_emoji = "✅"
                        
                        # Если есть поле in_range в данных позиции
                        if 'in_range' in pos:
                            in_range = pos.get('in_range', True)
                            if in_range:
                                range_emoji = "✅"
                                in_range_status = "in range"
                            else:
                                range_emoji = "❌"
                                in_range_status = "out of range"
                        
                        # Показываем короткий ID позиции
                        short_id = nft_id[:8] + "..." if len(nft_id) > 8 else nft_id
                        section.append(f"    • ${pos_value:,.2f} • ${pos_yield:,.2f} fees • {range_emoji} {in_range_status} • {short_id}")
                
                section.append("")
            
        except Exception as e:
            section.append(f"Error formatting Solana: {e}")
        
        return section
    
    def _format_ethereum_section(self, ethereum_positions: List[Dict]) -> List[str]:
        """Форматирует секцию Ethereum для мульти-чейн отчета"""
        section = [
            "⚡ ETHEREUM POOLS (Uniswap v3)",
            "=" * 30,
            ""
        ]
        
        try:
            if not ethereum_positions:
                section.extend(["No Ethereum positions found", ""])
                return section
            
            # Группируем позиции по пулам
            pools_data = {}
            total_eth_value = 0
            # total_eth_fees = 0  # УБРАНО - не показываем fees
            in_range_count = 0
            
            for position in ethereum_positions:
                pool_name = position.get('pool_name', 'Unknown Pool')
                value_usd = float(position.get('total_value_usd', 0))
                # fees_usd = float(position.get('unclaimed_fees_usd', 0))  # УБРАНО
                in_range = position.get('in_range', False)
                
                total_eth_value += value_usd
                # total_eth_fees += fees_usd  # УБРАНО
                if in_range:
                    in_range_count += 1
                
                if pool_name not in pools_data:
                    pools_data[pool_name] = {
                        'positions': [],
                        'total_value': 0,
                        # 'total_fees': 0,  # УБРАНО
                        'in_range': 0,
                        'out_range': 0
                    }
                
                pools_data[pool_name]['positions'].append(position)
                pools_data[pool_name]['total_value'] += value_usd
                # pools_data[pool_name]['total_fees'] += fees_usd  # УБРАНО
                
                if in_range:
                    pools_data[pool_name]['in_range'] += 1
                else:
                    pools_data[pool_name]['out_range'] += 1
            
            # Статистика Ethereum
            section.extend([
                f"💰 Ethereum Positions: ${total_eth_value:,.2f}",
                f"📍 Positions: {len(ethereum_positions)}",
                # f"🎁 Unclaimed Fees: ${total_eth_fees:,.2f}",  # УБРАНО - не показываем fees
                f"✅ In Range: {in_range_count}/{len(ethereum_positions)}",
                ""
            ])
            
            # Пулы Ethereum
            sorted_pools = sorted(pools_data.items(), key=lambda x: x[1]['total_value'], reverse=True)
            
            section.append("🏊 POOLS:")
            for pool_name, pool_data in sorted_pools:
                pool_value = pool_data['total_value']
                pool_count = len(pool_data['positions'])
                # pool_fees = pool_data['total_fees']  # УБРАНО
                in_range = pool_data['in_range']
                out_range = pool_data['out_range']
                
                section.append(f"• {pool_name}")
                
                # Попытка извлечь TVL из первой позиции пула
                pool_tvl = 0
                pool_address = ""
                if pool_data['positions']:
                    first_pos = pool_data['positions'][0]
                    pool_tvl = first_pos.get('pool_tvl_usd', 0)
                    pool_address = first_pos.get("pool_address", "")
                
                section.append(_format_tvl_with_change(pool_tvl, pool_address, "ethereum"))                
                section.append(f"  💰 Our positions: ${pool_value:,.2f} ({pool_count} pos)")
                # section.append(f"  🎁 Fees: ${pool_fees:,.2f}")  # УБРАНО - не показываем fees
                
                # Детали позиций
                section.append("  📍 Positions:")
                for position in pool_data['positions']:
                    pos_value = position.get('total_value_usd', 0)
                    # pos_fees = position.get('unclaimed_fees_usd', 0)  # УБРАНО
                    pos_id = position.get('token_id', position.get('position_id', 'Unknown'))
                    in_range_status = position.get('in_range', False)
                    range_emoji = "✅" if in_range_status else "❌"
                    range_text = "in range" if in_range_status else "out of range"
                    
                    # Убираем fees из строки позиции
                    section.append(f"    • ${pos_value:,.2f} • {range_emoji} {range_text} • #{pos_id}")
                
                section.append("")
            
        except Exception as e:
            section.append(f"Error formatting Ethereum: {e}")
        
        return section
    
    def _format_base_section(self, base_positions: List[Dict]) -> List[str]:
        """Форматирует секцию Base для мульти-чейн отчета"""
        section = [
            "🔵 BASE POOLS (Uniswap v3)",
            "=" * 30,
            ""
        ]
        
        try:
            if not base_positions:
                section.extend(["No Base positions found", ""])
                return section
            
            # Группируем позиции по пулам
            pools_data = {}
            total_base_value = 0
            # total_base_fees = 0  # УБРАНО - не показываем fees
            in_range_count = 0
            
            for position in base_positions:
                pool_name = position.get('pool_name', 'Unknown Pool')
                value_usd = float(position.get('total_value_usd', 0))
                # fees_usd = float(position.get('unclaimed_fees_usd', 0))  # УБРАНО
                in_range = position.get('in_range', False)
                
                total_base_value += value_usd
                # total_base_fees += fees_usd  # УБРАНО
                if in_range:
                    in_range_count += 1
                
                if pool_name not in pools_data:
                    pools_data[pool_name] = {
                        'positions': [],
                        'total_value': 0,
                        # 'total_fees': 0,  # УБРАНО
                        'in_range': 0,
                        'out_range': 0
                    }
                
                pools_data[pool_name]['positions'].append(position)
                pools_data[pool_name]['total_value'] += value_usd
                # pools_data[pool_name]['total_fees'] += fees_usd  # УБРАНО
                
                if in_range:
                    pools_data[pool_name]['in_range'] += 1
                else:
                    pools_data[pool_name]['out_range'] += 1
            
            # Статистика Base
            section.extend([
                f"💰 Base Positions: ${total_base_value:,.2f}",
                f"📍 Positions: {len(base_positions)}",
                # f"🎁 Unclaimed Fees: ${total_base_fees:,.2f}",  # УБРАНО - не показываем fees
                f"✅ In Range: {in_range_count}/{len(base_positions)}",
                ""
            ])
            
            # Пулы Base
            sorted_pools = sorted(pools_data.items(), key=lambda x: x[1]['total_value'], reverse=True)
            
            section.append("🏊 POOLS:")
            for pool_name, pool_data in sorted_pools:
                pool_value = pool_data['total_value']
                pool_count = len(pool_data['positions'])
                # pool_fees = pool_data['total_fees']  # УБРАНО
                in_range = pool_data['in_range']
                out_range = pool_data['out_range']
                
                section.append(f"• {pool_name}")
                
                # Попытка извлечь TVL из первой позиции пула
                pool_tvl = 0
                pool_address = ""
                if pool_data['positions']:
                    first_pos = pool_data['positions'][0]
                    pool_tvl = first_pos.get('pool_tvl_usd', 0)
                    pool_address = first_pos.get("pool_address", "")
                
                section.append(_format_tvl_with_change(pool_tvl, pool_address, "base"))                
                section.append(f"  💰 Our positions: ${pool_value:,.2f} ({pool_count} pos)")
                # section.append(f"  🎁 Fees: ${pool_fees:,.2f}") # УБРАНО - не показываем fees
                
                # Детали позиций
                section.append("  📍 Positions:")
                for position in pool_data['positions']:
                    pos_value = position.get('total_value_usd', 0)
                    # pos_fees = position.get('unclaimed_fees_usd', 0) # УБРАНО
                    pos_id = position.get('token_id', position.get('position_id', 'Unknown'))
                    in_range_status = position.get('in_range', False)
                    range_emoji = "✅" if in_range_status else "❌"
                    range_text = "in range" if in_range_status else "out of range"
                    
                    section.append(f"    • ${pos_value:,.2f} • {range_emoji} {range_text} • #{pos_id}")
                
                section.append("")
            
        except Exception as e:
            section.append(f"Error formatting Base: {e}")
        
        return section

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

def format_price_range(price_lower: float, price_upper: float, current_price: float = None, precision: int = 6) -> str:
    """Format price range with proper thousands separators and optional current price info"""
    # Убираем trailing zeros для более читаемого вида
    price_lower_str = f"{price_lower:,.{precision}f}".rstrip('0').rstrip('.')
    price_upper_str = f"{price_upper:,.{precision}f}".rstrip('0').rstrip('.')
    
    range_str = f"Range: {price_lower_str} - {price_upper_str}"
    
    if current_price is not None:
        current_str = f"{current_price:,.{precision}f}".rstrip('0').rstrip('.')
        
        # Calculate percentage above/below range
        if current_price > price_upper:
            percent_above = ((current_price - price_upper) / price_upper) * 100
            percent_str = f"{percent_above:,.1f}"
            range_str += f" (current: {current_str}, {percent_str}% above range)"
        elif current_price < price_lower:
            percent_below = ((price_lower - current_price) / price_lower) * 100
            percent_str = f"{percent_below:,.1f}"
            range_str += f" (current: {current_str}, {percent_str}% below range)"
        else:
            range_str += f" (current: {current_str}, in range)"
    
    return range_str

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