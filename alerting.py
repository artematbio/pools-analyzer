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
        
        # Out-of-range positions intelligent tracking
        self.last_out_of_range_positions: Optional[List[Dict[str, Any]]] = None
        self.last_out_of_range_alert_time: Optional[datetime] = None
        self.daily_alert_interval = timedelta(hours=24)  # Send daily alert if no changes
        
        # Rate limiting configuration
        self.rate_limits = {
            'error_cooldown': timedelta(minutes=15),  # Don't spam same error
            'portfolio_cooldown': timedelta(hours=1),  # Portfolio change alerts
            'health_check_interval': timedelta(minutes=5)
            # Note: position_cooldown removed - using intelligent alerting instead
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
    
    def _compare_out_of_range_positions(self, current_positions: List[Dict[str, Any]], 
                                      previous_positions: Optional[List[Dict[str, Any]]]) -> bool:
        """
        Compare current and previous out-of-range positions to detect changes
        
        Args:
            current_positions: Current list of out-of-range positions
            previous_positions: Previous list of out-of-range positions
            
        Returns:
            bool: True if positions have changed, False otherwise
        """
        if previous_positions is None:
            # First time checking - consider as change if there are positions
            return len(current_positions) > 0
        
        # Compare position counts
        if len(current_positions) != len(previous_positions):
            return True
        
        # Compare individual positions by mint address
        current_mints = set(pos.get('position_mint', '') for pos in current_positions)
        previous_mints = set(pos.get('position_mint', '') for pos in previous_positions)
        
        # If the sets are different, there's a change
        if current_mints != previous_mints:
            return True
        
        # Check if position values changed significantly (>1% change)
        for current_pos in current_positions:
            mint = current_pos.get('position_mint', '')
            current_value = float(current_pos.get('position_value_usd', 0))
            
            # Find corresponding previous position
            previous_pos = next((pos for pos in previous_positions 
                               if pos.get('position_mint', '') == mint), None)
            
            if previous_pos:
                previous_value = float(previous_pos.get('position_value_usd', 0))
                
                # Check for significant value change (>1%)
                if previous_value > 0:
                    change_percent = abs((current_value - previous_value) / previous_value) * 100
                    if change_percent > 1.0:
                        return True
        
        return False
    
    async def check_out_of_range_positions(self) -> bool:
        """
        Intelligent check for out of range positions with smart alerting:
        - Check every 30 minutes (unchanged)
        - Send alert immediately if positions changed
        - Send daily alert if no changes but positions still out of range
        - No spam if no out of range positions
        
        Returns:
            bool: True if alert was sent
        """
        try:
            # Import here to avoid circular import
            from pool_analyzer import TARGET_WALLET_ADDRESSES, get_positions_from_multiple_wallets
            import httpx
            import os
            
            # Get current positions
            helius_rpc_url = os.getenv('HELIUS_RPC_URL')
            helius_api_key = os.getenv('HELIUS_API_KEY')
            
            if not helius_rpc_url or not helius_api_key:
                logging.warning("Helius credentials not configured for position checks")
                return False
            
            # Get all positions from all wallets
            async with httpx.AsyncClient(timeout=60.0) as client:
                all_positions = await get_positions_from_multiple_wallets(
                    TARGET_WALLET_ADDRESSES, 
                    helius_rpc_url, 
                    helius_api_key
                )
            
            # Filter out of range positions
            current_out_of_range_positions = []
            for pos in all_positions:
                if pos.get('in_range') is False:
                    current_out_of_range_positions.append(pos)
            
            now = datetime.now(timezone.utc)
            
            # If no out of range positions, clear state and exit
            if len(current_out_of_range_positions) == 0:
                if self.last_out_of_range_positions and len(self.last_out_of_range_positions) > 0:
                    # All positions are now in range - send recovery alert
                    recovery_message = f"""✅ <b>POSITIONS BACK IN RANGE</b>

🎉 All positions are now back in range!

<i>Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"""
                    
                    success = await self.telegram.send_message(recovery_message)
                    
                    if success:
                        alert = Alert(
                            level=AlertLevel.INFO,
                            title="Positions Back In Range",
                            message="All positions are now in range",
                            context="Recovery from out-of-range state"
                        )
                        self._record_alert(alert)
                        logging.info("✅ Recovery alert sent - all positions back in range")
                        
                        # Clear state
                        self.last_out_of_range_positions = []
                        self.last_out_of_range_alert_time = now
                        return True
                
                # Clear state
                self.last_out_of_range_positions = []
                logging.debug("✅ All positions are in range")
                return False
            
            # Check if positions changed compared to last check
            positions_changed = self._compare_out_of_range_positions(
                current_out_of_range_positions, 
                self.last_out_of_range_positions
            )
            
            should_send_alert = False
            alert_reason = ""
            
            if positions_changed:
                # Positions changed - send alert immediately
                should_send_alert = True
                alert_reason = "positions_changed"
                logging.info(f"📊 Out-of-range positions changed: {len(current_out_of_range_positions)} positions")
            else:
                # No changes - check if we should send daily alert
                if self.last_out_of_range_alert_time is None:
                    # First time - send alert
                    should_send_alert = True
                    alert_reason = "first_time"
                    logging.info(f"📊 First out-of-range check: {len(current_out_of_range_positions)} positions")
                else:
                    # Check if 24 hours passed since last alert
                    time_since_last_alert = now - self.last_out_of_range_alert_time
                    if time_since_last_alert >= self.daily_alert_interval:
                        should_send_alert = True
                        alert_reason = "daily_reminder"
                        logging.info(f"📊 Daily out-of-range reminder: {len(current_out_of_range_positions)} positions")
                    else:
                        # No need to send alert yet
                        hours_remaining = (self.daily_alert_interval - time_since_last_alert).total_seconds() / 3600
                        logging.debug(f"📊 Out-of-range positions unchanged, next alert in {hours_remaining:.1f} hours")
            
            # Send alert if needed
            if should_send_alert:
                # Format alert message with reason
                alert_message = self.formatter.format_out_of_range_alert(current_out_of_range_positions)
                
                # Add reason context to message
                if alert_reason == "positions_changed":
                    alert_message += f"\n\n🔄 <b>Reason:</b> Position changes detected"
                elif alert_reason == "daily_reminder":
                    alert_message += f"\n\n🕒 <b>Reason:</b> Daily reminder (no changes in 24h)"
                elif alert_reason == "first_time":
                    alert_message += f"\n\n🆕 <b>Reason:</b> Initial detection"
                
                success = await self.telegram.send_message(alert_message)
                
                if success:
                    # Record alert
                    alert = Alert(
                        level=AlertLevel.WARNING,
                        title="Out of Range Positions",
                        message=f"{len(current_out_of_range_positions)} positions are out of range ({alert_reason})",
                        context=f"Positions: {[pos.get('position_mint', 'N/A')[:8] for pos in current_out_of_range_positions]}"
                    )
                    self._record_alert(alert)
                    
                    # Update tracking state
                    self.last_out_of_range_positions = current_out_of_range_positions.copy()
                    self.last_out_of_range_alert_time = now
                    
                    logging.info(f"✅ Out-of-range positions alert sent: {len(current_out_of_range_positions)} positions ({alert_reason})")
                    return True
                else:
                    logging.error("❌ Failed to send out-of-range positions alert")
            else:
                # Update tracking state without sending alert
                self.last_out_of_range_positions = current_out_of_range_positions.copy()
            
            return False
            
        except Exception as e:
            logging.error(f"❌ Error checking out of range positions: {e}")
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