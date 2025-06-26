import asyncio
import logging
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from enum import Enum
from dotenv import load_dotenv

from telegram_sender import TelegramSender
from report_formatter import ReportFormatter

# Supabase integration
try:
    from database_handler import supabase_handler
    SUPABASE_ENABLED = True
    logging.info("✅ Supabase handler loaded for alerts")
except ImportError as e:
    logging.warning(f"⚠️ Supabase handler not available: {e}")
    supabase_handler = None
    SUPABASE_ENABLED = False

load_dotenv()

class AlertLevel(Enum):
    """Alert severity levels"""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

@dataclass
class Alert:
    """Alert data structure"""
    level: AlertLevel
    title: str
    message: str
    context: str = ""
    timestamp: datetime = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

class AlertingSystem:
    """
    Comprehensive alerting system for the Raydium Pool Analyzer
    Handles error notifications, portfolio changes, and system health monitoring
    """
    
    def __init__(self):
        self.telegram = TelegramSender()
        self.formatter = ReportFormatter()
        
        # Configuration from environment
        self.portfolio_change_threshold = float(os.getenv('PORTFOLIO_CHANGE_THRESHOLD', '5.0'))
        self.error_notification_enabled = os.getenv('ERROR_NOTIFICATION_ENABLED', 'true').lower() == 'true'
        
        # Alert history and state tracking
        self.alert_history: List[Alert] = []
        self.last_portfolio_value: Optional[float] = None
        self.last_portfolio_check: Optional[datetime] = None
        self.error_counts: Dict[str, int] = {}
        self.last_error_times: Dict[str, datetime] = {}
        
        # Rate limiting configuration
        self.rate_limits = {
            'error_cooldown': timedelta(minutes=15),  # Don't spam same error
            'portfolio_cooldown': timedelta(hours=1),  # Portfolio change alerts
            'health_check_interval': timedelta(minutes=5)
        }
        
        logging.info("Alerting system initialized")
    
    async def send_error_alert(self, error_type: str, error_message: str, context: str = "", 
                             level: AlertLevel = AlertLevel.ERROR) -> bool:
        """
        Send error alert with rate limiting
        
        Args:
            error_type: Type of error (e.g., "Pool Analysis", "API Connection")
            error_message: Detailed error message
            context: Additional context information
            level: Alert severity level
            
        Returns:
            bool: True if alert was sent, False if rate limited or disabled
        """
        if not self.error_notification_enabled:
            logging.info(f"Error notifications disabled, skipping: {error_type}")
            return False
        
        # Check rate limiting
        error_key = f"{error_type}:{error_message[:50]}"  # Use first 50 chars as key
        
        if self._is_rate_limited(error_key, 'error_cooldown'):
            logging.info(f"Error alert rate limited: {error_type}")
            return False
        
        try:
            # Create alert
            alert = Alert(
                level=level,
                title=f"Error in {error_type}",
                message=error_message,
                context=context
            )
            
            # Format message
            formatted_message = self.formatter.format_error_alert(error_type, error_message, context)
            
            # Send to Telegram
            success = await self.telegram.send_alert(
                title=f"{level.value}: {error_type}",
                message=error_message + (f"\n\nContext: {context}" if context else ""),
                alert_type=level.value
            )
            
            if success:
                self._record_alert(alert)
                self._update_error_tracking(error_key)
                logging.info(f"Error alert sent: {error_type}")
            else:
                logging.error(f"Failed to send error alert: {error_type}")
            
            return success
            
        except Exception as e:
            logging.error(f"Exception in send_error_alert: {e}")
            return False
    
    async def check_portfolio_changes(self, current_value: float, detailed_data: Dict = None) -> bool:
        """
        Check for significant portfolio value changes and send alerts
        
        Args:
            current_value: Current portfolio value in USD
            detailed_data: Optional detailed portfolio data
            
        Returns:
            bool: True if alert was sent
        """
        try:
            now = datetime.now(timezone.utc)
            
            # Skip if no previous value to compare
            if self.last_portfolio_value is None:
                self.last_portfolio_value = current_value
                self.last_portfolio_check = now
                logging.info(f"Initial portfolio value recorded: ${current_value:,.2f}")
                return False
            
            # Calculate change
            change_amount = current_value - self.last_portfolio_value
            change_percent = (change_amount / self.last_portfolio_value) * 100
            
            # Check if change exceeds threshold
            if abs(change_percent) >= self.portfolio_change_threshold:
                
                # Check rate limiting
                if self._is_rate_limited('portfolio_change', 'portfolio_cooldown'):
                    logging.info("Portfolio change alert rate limited")
                    return False
                
                # Format and send alert
                alert_message = self.formatter.format_portfolio_change_alert(
                    self.last_portfolio_value, 
                    current_value, 
                    change_percent
                )
                
                success = await self.telegram.send_message(alert_message)
                
                if success:
                    # Record alert
                    alert = Alert(
                        level=AlertLevel.WARNING if abs(change_percent) < 10 else AlertLevel.ERROR,
                        title="Portfolio Value Change",
                        message=f"Portfolio changed by {change_percent:.1f}%",
                        context=f"Previous: ${self.last_portfolio_value:,.2f}, Current: ${current_value:,.2f}"
                    )
                    self._record_alert(alert)
                    
                    # Update tracking
                    self.last_portfolio_value = current_value
                    self.last_portfolio_check = now
                    self._update_error_tracking('portfolio_change')
                    
                    logging.info(f"Portfolio change alert sent: {change_percent:.1f}%")
                    return True
                else:
                    logging.error("Failed to send portfolio change alert")
            
            else:
                # Update values even if no alert sent
                self.last_portfolio_value = current_value
                self.last_portfolio_check = now
                logging.debug(f"Portfolio change within threshold: {change_percent:.1f}%")
            
            return False
            
        except Exception as e:
            logging.error(f"Error checking portfolio changes: {e}")
            await self.send_error_alert("Portfolio Monitoring", str(e), level=AlertLevel.WARNING)
            return False
    
    async def send_system_health_alert(self, system_status: Dict[str, Any]) -> bool:
        """
        Send system health status alert
        
        Args:
            system_status: System status dictionary
            
        Returns:
            bool: True if alert was sent
        """
        try:
            overall_status = system_status.get('overall_status', 'unknown')
            
            # Only send alerts for problematic statuses
            if overall_status in ['healthy', 'unknown']:
                return False
            
            # Check rate limiting
            if self._is_rate_limited('system_health', 'error_cooldown'):
                return False
            
            # Determine alert level
            level = AlertLevel.WARNING if overall_status == 'warning' else AlertLevel.ERROR
            
            # Format status message
            status_message = self.formatter.format_status_report(system_status)
            
            success = await self.telegram.send_alert(
                title=f"System Health: {overall_status.title()}",
                message=status_message,
                alert_type=level.value
            )
            
            if success:
                alert = Alert(
                    level=level,
                    title="System Health Alert",
                    message=f"System status: {overall_status}",
                    context=json.dumps(system_status, indent=2)
                )
                self._record_alert(alert)
                self._update_error_tracking('system_health')
                
                logging.info(f"System health alert sent: {overall_status}")
            
            return success
            
        except Exception as e:
            logging.error(f"Error sending system health alert: {e}")
            return False
    
    async def send_startup_notification(self) -> bool:
        """Send notification when system starts up"""
        try:
            startup_message = f"""🚀 <b>SYSTEM STARTUP</b>

✅ Raydium Pool Analyzer is now online
📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

<b>Services Started:</b>
• Pool Analyzer
• PHI Analyzer  
• Telegram Bot
• Scheduler
• Alerting System

<b>Schedule:</b>
• Pool Analysis: 09:00 & 18:00 UTC daily
• PHI Analysis: Sunday 18:30 UTC

🔄 System ready for automated monitoring"""
            
            success = await self.telegram.send_message(startup_message)
            
            if success:
                alert = Alert(
                    level=AlertLevel.INFO,
                    title="System Startup",
                    message="System started successfully"
                )
                self._record_alert(alert)
                logging.info("Startup notification sent")
            
            return success
            
        except Exception as e:
            logging.error(f"Error sending startup notification: {e}")
            return False
    
    async def send_analysis_completion_summary(self, analysis_type: str, 
                                             execution_time: float, 
                                             success: bool = True,
                                             summary_data: Dict = None) -> bool:
        """
        Send analysis completion notification
        
        Args:
            analysis_type: "pool" or "phi"
            execution_time: Time taken in seconds
            success: Whether analysis completed successfully
            summary_data: Optional summary data
            
        Returns:
            bool: True if notification sent
        """
        try:
            if success:
                emoji = "✅"
                status = "completed successfully"
                level = AlertLevel.INFO
            else:
                emoji = "❌"
                status = "failed"
                level = AlertLevel.ERROR
            
            message = f"""{emoji} <b>{analysis_type.upper()} ANALYSIS {status.upper()}</b>
📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
⏱️ Execution time: {execution_time:.1f} seconds"""
            
            if summary_data:
                if analysis_type == "pool":
                    total_value = summary_data.get('total_value', 0)
                    positions = summary_data.get('positions', 0)
                    message += f"\n\n💰 Total Value: ${total_value:,.2f}\n📊 Positions: {positions}"
                
                elif analysis_type == "phi":
                    insights = summary_data.get('insights_count', 0)
                    message += f"\n\n🔮 AI Insights Generated: {insights}"
            
            # Only send completion notifications for successful runs or critical failures
            if success or level == AlertLevel.ERROR:
                success = await self.telegram.send_message(message)
                
                if success:
                    alert = Alert(
                        level=level,
                        title=f"{analysis_type.title()} Analysis Complete",
                        message=f"Analysis {status} in {execution_time:.1f}s"
                    )
                    self._record_alert(alert)
            
            return success
            
        except Exception as e:
            logging.error(f"Error sending analysis completion summary: {e}")
            return False
    
    def _is_rate_limited(self, key: str, cooldown_type: str) -> bool:
        """Check if alert is rate limited"""
        if key not in self.last_error_times:
            return False
        
        cooldown_period = self.rate_limits.get(cooldown_type, timedelta(minutes=15))
        time_since_last = datetime.now(timezone.utc) - self.last_error_times[key]
        
        return time_since_last < cooldown_period
    
    def _record_alert(self, alert: Alert) -> None:
        """Record alert in history and duplicate to Supabase"""
        self.alert_history.append(alert)
        
        # Keep only last 100 alerts to prevent memory issues
        if len(self.alert_history) > 100:
            self.alert_history = self.alert_history[-100:]
        
        # Duplicate to Supabase
        if SUPABASE_ENABLED and supabase_handler and supabase_handler.is_connected():
            try:
                alert_data = {
                    'level': alert.level.value,
                    'title': alert.title,
                    'message': alert.message,
                    'context': alert.context or '',
                    'timestamp': alert.timestamp.isoformat(),
                    'source': 'pool_analyzer'
                }
                
                # Save to Supabase asynchronously (non-blocking)
                import asyncio
                try:
                    # Try to get current event loop
                    loop = asyncio.get_running_loop()
                    # Schedule the coroutine to run
                    loop.create_task(self._save_alert_to_supabase(alert_data))
                except RuntimeError:
                    # No event loop running, save synchronously
                    result = supabase_handler.save_alert(alert_data)
                    if result:
                        logging.debug(f"✅ Alert duplicated to Supabase: {alert.title}")
                    else:
                        logging.warning(f"⚠️ Failed to duplicate alert to Supabase: {alert.title}")
                        
            except Exception as e:
                logging.error(f"❌ Error duplicating alert to Supabase: {e}")
    
    async def _save_alert_to_supabase(self, alert_data: Dict[str, Any]) -> None:
        """Asynchronously save alert to Supabase"""
        try:
            result = supabase_handler.save_alert(alert_data)
            if result:
                logging.debug(f"✅ Alert duplicated to Supabase: {alert_data['title']}")
            else:
                logging.warning(f"⚠️ Failed to duplicate alert to Supabase: {alert_data['title']}")
        except Exception as e:
            logging.error(f"❌ Error saving alert to Supabase: {e}")
    
    def _update_error_tracking(self, error_key: str) -> None:
        """Update error tracking counters and timestamps"""
        self.error_counts[error_key] = self.error_counts.get(error_key, 0) + 1
        self.last_error_times[error_key] = datetime.now(timezone.utc)
    
    def get_alert_summary(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get summary of alerts from the last N hours
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Dictionary with alert statistics
        """
        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        recent_alerts = [alert for alert in self.alert_history if alert.timestamp > cutoff_time]
        
        summary = {
            'total_alerts': len(recent_alerts),
            'by_level': {},
            'by_hour': {},
            'most_common_errors': {}
        }
        
        # Count by level
        for alert in recent_alerts:
            level = alert.level.value
            summary['by_level'][level] = summary['by_level'].get(level, 0) + 1
        
        # Count by hour
        for alert in recent_alerts:
            hour = alert.timestamp.strftime('%H:00')
            summary['by_hour'][hour] = summary['by_hour'].get(hour, 0) + 1
        
        # Most common error types
        error_types = [alert.title for alert in recent_alerts if alert.level in [AlertLevel.ERROR, AlertLevel.CRITICAL]]
        for error_type in error_types:
            summary['most_common_errors'][error_type] = summary['most_common_errors'].get(error_type, 0) + 1
        
        return summary
    
    async def send_daily_alert_summary(self) -> bool:
        """Send daily summary of alerts (if any significant ones occurred)"""
        try:
            summary = self.get_alert_summary(24)
            
            if summary['total_alerts'] == 0:
                return False  # No alerts to report
            
            # Only send summary if there were errors or warnings
            significant_alerts = summary['by_level'].get('ERROR', 0) + summary['by_level'].get('WARNING', 0)
            
            if significant_alerts == 0:
                return False
            
            message = f"""📊 <b>DAILY ALERT SUMMARY</b>
📅 Last 24 hours

<b>Total Alerts:</b> {summary['total_alerts']}"""
            
            for level, count in summary['by_level'].items():
                if count > 0:
                    emoji = {'INFO': 'ℹ️', 'WARNING': '⚠️', 'ERROR': '❌', 'CRITICAL': '🚨'}.get(level, '📢')
                    message += f"\n{emoji} {level}: {count}"
            
            if summary['most_common_errors']:
                message += "\n\n<b>Most Common Issues:</b>"
                for error, count in list(summary['most_common_errors'].items())[:3]:
                    message += f"\n• {error}: {count}x"
            
            success = await self.telegram.send_message(message)
            return success
            
        except Exception as e:
            logging.error(f"Error sending daily alert summary: {e}")
            return False

# Global alerting instance
alerting_system = AlertingSystem()

# Convenience functions for easy access
async def send_error_alert(error_type: str, error_message: str, context: str = "", 
                          level: AlertLevel = AlertLevel.ERROR) -> bool:
    """Quick function to send error alert"""
    return await alerting_system.send_error_alert(error_type, error_message, context, level)

async def check_portfolio_changes(current_value: float, detailed_data: Dict = None) -> bool:
    """Quick function to check portfolio changes"""
    return await alerting_system.check_portfolio_changes(current_value, detailed_data)

async def send_startup_notification() -> bool:
    """Quick function to send startup notification"""
    return await alerting_system.send_startup_notification()

# Example usage and testing
if __name__ == "__main__":
    async def test_alerting():
        # Test error alert
        await send_error_alert("Test System", "This is a test error message", "Testing context")
        
        # Test portfolio change
        await check_portfolio_changes(100000.0)  # Initial value
        await asyncio.sleep(1)
        await check_portfolio_changes(110000.0)  # 10% increase should trigger alert
        
        # Test startup notification
        await send_startup_notification()
        
        print("✅ Alerting system tests completed")
    
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_alerting()) 