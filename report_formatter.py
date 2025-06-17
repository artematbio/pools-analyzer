import re
import json
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from decimal import Decimal

class ReportFormatter:
    """
    Formats analysis reports for Telegram delivery
    with emoji integration and HTML formatting
    """
    
    def __init__(self):
        # Token emoji mapping
        self.emoji_map = {
            'BIO': '🧬',
            'SOL': '☀️', 
            'SPINE': '🦴',
            'MYCO': '🍄',
            'CURES': '💊',
            'QBIO': '🔬',
            'GROW': '🌱',
            'USDC': '💵',
            'USDT': '💵',
            'RAY': '⚡',
            'BONK': '🐕'
        }
        
        # Status emoji
        self.status_emoji = {
            'in_range': '🎯',
            'out_of_range': '🔴',
            'unknown': '❓',
            'up': '📈',
            'down': '📉',
            'stable': '➡️'
        }
    
    def format_pool_report(self, report_content: str) -> str:
        """
        Format pool analysis report for Telegram
        
        Args:
            report_content: Raw report text content
            
        Returns:
            Formatted HTML message for Telegram
        """
        try:
            # Extract main metrics
            total_value = self._extract_total_value(report_content)
            total_positions = self._extract_total_positions(report_content)
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            
            # Build header
            header = f"""🏦 <b>RAYDIUM POOLS REPORT</b>
📅 {timestamp}
💰 Total Value: <b>${total_value:,.2f}</b>
📊 Active Positions: <b>{total_positions}</b>

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            
            # Extract and format pool data
            pools_data = self._extract_pools_data(report_content)
            pools_summary = self._format_pools_summary(pools_data)
            
            # Build footer
            footer = f"""━━━━━━━━━━━━━━━━━━━━━━━━━━━━
⏰ Next update: {self._get_next_update_time()}
🔄 Automated by Railway"""
            
            return f"{header}\n\n{pools_summary}\n\n{footer}"
            
        except Exception as e:
            return f"❌ Error formatting pool report: {str(e)}"
    
    def format_phi_analysis(self, analysis_content: str) -> str:
        """
        Format PHI analysis for Telegram
        
        Args:
            analysis_content: Raw PHI analysis content
            
        Returns:
            Formatted HTML message for Telegram
        """
        try:
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            
            header = f"""🔮 <b>PHI WEEKLY ANALYSIS</b>
📅 {timestamp}
🤖 AI-Powered Market Intelligence

━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
            
            # Clean and truncate analysis
            cleaned_analysis = self._clean_analysis_content(analysis_content)
            
            # Truncate if too long (keeping buffer for header/footer)
            max_content_length = 3500
            if len(cleaned_analysis) > max_content_length:
                cleaned_analysis = cleaned_analysis[:max_content_length] + "...\n\n📄 <i>Analysis truncated for Telegram</i>"
            
            footer = """━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔄 Weekly analysis • Every Sunday 18:30 UTC"""
            
            return f"{header}\n\n{cleaned_analysis}\n\n{footer}"
            
        except Exception as e:
            return f"❌ Error formatting PHI analysis: {str(e)}"
    
    def format_error_alert(self, error_type: str, error_message: str, context: str = "") -> str:
        """
        Format error alert for Telegram
        
        Args:
            error_type: Type of error (e.g., "Pool Analysis", "PHI Analysis")
            error_message: Error description
            context: Additional context
            
        Returns:
            Formatted error message
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        
        message = f"""🚨 <b>SYSTEM ALERT</b>

❌ <b>Error in {error_type}</b>
📅 {timestamp}

<b>Details:</b>
{error_message}"""
        
        if context:
            message += f"\n\n<b>Context:</b>\n{context}"
        
        message += "\n\n🔧 <i>Automatic retry will be attempted</i>"
        
        return message
    
    def format_portfolio_change_alert(self, old_value: float, new_value: float, change_percent: float) -> str:
        """
        Format portfolio value change alert
        
        Args:
            old_value: Previous portfolio value
            new_value: Current portfolio value
            change_percent: Percentage change
            
        Returns:
            Formatted change alert
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        
        if change_percent > 0:
            emoji = "📈"
            direction = "increased"
            color = "🟢"
        else:
            emoji = "📉"
            direction = "decreased"
            color = "🔴"
        
        message = f"""💼 <b>PORTFOLIO CHANGE ALERT</b>

{emoji} Portfolio value {direction} by <b>{abs(change_percent):.1f}%</b>

{color} <b>Previous:</b> ${old_value:,.2f}
{color} <b>Current:</b> ${new_value:,.2f}
{color} <b>Change:</b> ${new_value - old_value:+,.2f}

📅 {timestamp}"""
        
        return message
    
    def format_status_report(self, system_status: Dict[str, Any]) -> str:
        """
        Format system status report
        
        Args:
            system_status: Dictionary with system status information
            
        Returns:
            Formatted status message
        """
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        
        # Determine overall status
        overall_status = system_status.get('overall_status', 'unknown')
        status_emoji = {
            'healthy': '✅',
            'warning': '⚠️',
            'error': '❌',
            'unknown': '❓'
        }.get(overall_status, '❓')
        
        message = f"""🔧 <b>SYSTEM STATUS</b>
📅 {timestamp}

{status_emoji} <b>Overall Status:</b> {overall_status.title()}

<b>Services:</b>"""
        
        # Add service statuses
        services = system_status.get('services', {})
        for service, status in services.items():
            service_emoji = '✅' if status == 'running' else '❌'
            message += f"\n{service_emoji} {service}: {status}"
        
        # Add schedule info
        schedule = system_status.get('next_scheduled_tasks', [])
        if schedule:
            message += "\n\n<b>Next Scheduled Tasks:</b>"
            for task in schedule[:3]:  # Show max 3 upcoming tasks
                message += f"\n⏰ {task.get('name', 'Unknown')}: {task.get('time', 'Unknown')}"
        
        return message
    
    def _extract_total_value(self, content: str) -> float:
        """Extract total portfolio value from report"""
        patterns = [
            r'Общая стоимость всех позиций:\s*\$([0-9,]+\.?\d*)',
            r'Total value USD:\s*\$([0-9,]+\.?\d*)',
            r'Total Value:\s*\$([0-9,]+\.?\d*)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(',', ''))
        
        return 0.0
    
    def _extract_total_positions(self, content: str) -> int:
        """Extract total number of positions"""
        patterns = [
            r'Всего CLMM позиций:\s*(\d+)',
            r'Found (\d+) total positions',
            r'Total positions:\s*(\d+)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                return int(match.group(1))
        
        return 0
    
    def _extract_pools_data(self, content: str) -> Dict[str, Dict]:
        """Extract detailed pool data from report"""
        pools = {}
        
        # Pattern to find pool sections
        pool_pattern = r'--- АНАЛИЗ ПУЛА: ([^(]+)\s*\([^)]+\) ---(.*?)(?=--- АНАЛИЗ ПУЛА:|ДРУГИЕ ПУЛЫ|$)'
        pool_matches = re.findall(pool_pattern, content, re.DOTALL)
        
        for pool_name, pool_content in pool_matches:
            pool_name = pool_name.strip()
            
            # Extract metrics with multiple patterns
            pool_data = {
                'name': pool_name,
                'tvl': self._extract_metric(pool_content, [
                    r'Общая ликвидность пула \(TVL\):\s*\$([0-9,]+\.?\d*)',
                    r'TVL:\s*\$([0-9,]+\.?\d*)'
                ]),
                'volume_24h': self._extract_metric(pool_content, [
                    r'Объем торгов за 24 часа:\s*\$([0-9,]+\.?\d*)',
                    r'24h Volume:\s*\$([0-9,]+\.?\d*)'
                ]),
                'volume_7d': self._extract_metric(pool_content, [
                    r'Объем торгов за 7 дней:\s*\$([0-9,]+\.?\d*)',
                    r'7d Volume:\s*\$([0-9,]+\.?\d*)'
                ]),
                'positions_count': self._extract_metric(pool_content, [
                    r'Активные позиции:\s*(\d+)',
                    r'Active positions:\s*(\d+)'
                ], is_float=False),
                'positions_value': self._extract_metric(pool_content, [
                    r'Общая стоимость позиций:\s*~?\$([0-9,]+\.?\d*)',
                    r'Position value:\s*\$([0-9,]+\.?\d*)'
                ]),
                'pending_yield': self._extract_metric(pool_content, [
                    r'Общий Pending Yield:\s*~?\$([0-9,]+\.?\d*)',
                    r'Pending yield:\s*\$([0-9,]+\.?\d*)'
                ])
            }
            
            pools[pool_name] = pool_data
        
        return pools
    
    def _extract_metric(self, content: str, patterns: List[str], is_float: bool = True) -> float:
        """Extract numeric metric using multiple patterns"""
        for pattern in patterns:
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                value_str = match.group(1).replace(',', '')
                return float(value_str) if is_float else int(float(value_str))
        
        return 0.0 if is_float else 0
    
    def _format_pools_summary(self, pools_data: Dict[str, Dict]) -> str:
        """Format pools data into summary"""
        if not pools_data:
            return "📭 No pool data available"
        
        summary = ""
        
        for pool_name, data in pools_data.items():
            emoji = self._get_pool_emoji(pool_name)
            
            # Format values with appropriate precision
            tvl = data.get('tvl', 0)
            volume_24h = data.get('volume_24h', 0)
            positions_count = data.get('positions_count', 0)
            positions_value = data.get('positions_value', 0)
            pending_yield = data.get('pending_yield', 0)
            
            summary += f"""{emoji} <b>{pool_name}</b>
💎 TVL: ${tvl:,.0f}
📈 24h Vol: ${volume_24h:,.0f}
🎯 Positions: {positions_count} • ${positions_value:,.0f}
💸 Yield: ${pending_yield:,.2f}

"""
        
        return summary.rstrip()
    
    def _get_pool_emoji(self, pool_name: str) -> str:
        """Get emoji for pool based on token names"""
        pool_upper = pool_name.upper()
        
        # Check each token in our emoji map
        for token, emoji in self.emoji_map.items():
            if token in pool_upper:
                return emoji
        
        return "💎"  # Default emoji
    
    def _get_next_update_time(self) -> str:
        """Calculate next update time based on current time"""
        now = datetime.now(timezone.utc)
        current_hour = now.hour
        
        if current_hour < 9:
            return "09:00 UTC (today)"
        elif current_hour < 18:
            return "18:00 UTC (today)"
        else:
            return "09:00 UTC (tomorrow)"
    
    def _clean_analysis_content(self, content: str) -> str:
        """Clean and format analysis content for Telegram"""
        # Remove excessive whitespace
        content = re.sub(r'\n\s*\n\s*\n', '\n\n', content)
        
        # Convert markdown-style formatting to HTML
        content = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', content)
        content = re.sub(r'\*(.*?)\*', r'<i>\1</i>', content)
        
        # Add emoji to section headers
        content = re.sub(r'^(АНАЛИЗ|ANALYSIS|ВЫВОДЫ|CONCLUSIONS?|РЕКОМЕНДАЦИИ|RECOMMENDATIONS?):', 
                        r'📊 <b>\1:</b>', content, flags=re.MULTILINE | re.IGNORECASE)
        
        content = re.sub(r'^(АНОМАЛИИ|ANOMALIES|ИЗМЕНЕНИЯ|CHANGES):', 
                        r'🔍 <b>\1:</b>', content, flags=re.MULTILINE | re.IGNORECASE)
        
        content = re.sub(r'^(РИСКИ|RISKS|ПРЕДУПРЕЖДЕНИЯ|WARNINGS?):', 
                        r'⚠️ <b>\1:</b>', content, flags=re.MULTILINE | re.IGNORECASE)
        
        return content.strip()

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
    print(formatted)
    
    # Test error formatting
    error_msg = formatter.format_error_alert("Pool Analysis", "Connection timeout", "API rate limit exceeded")
    print("\n=== ERROR ALERT ===")
    print(error_msg) 