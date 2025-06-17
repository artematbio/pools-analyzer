import asyncio
import logging
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv

try:
    from telegram import Update, Bot
    from telegram.ext import Application, CommandHandler, ContextTypes
    from telegram.error import TelegramError
except ImportError:
    print("Warning: python-telegram-bot not installed")
    Update = None
    CommandHandler = None
    ContextTypes = None

from telegram_sender import TelegramSender
from report_formatter import ReportFormatter

load_dotenv()

class BotCommandHandler:
    """
    Handles Telegram bot commands for the Raydium Pool Analyzer
    """
    
    def __init__(self, scheduler_instance=None):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.authorized_chat_id = os.getenv('TELEGRAM_CHAT_ID')
        self.scheduler = scheduler_instance
        self.telegram = TelegramSender()
        self.formatter = ReportFormatter()
        
        # System status tracking
        self.system_status = {
            'overall_status': 'healthy',
            'services': {
                'pool_analyzer': 'running',
                'phi_analyzer': 'running',
                'scheduler': 'running',
                'telegram_bot': 'running'
            },
            'last_successful_analysis': None,
            'last_error': None,
            'uptime_start': datetime.now(timezone.utc)
        }
    
    async def setup_bot_commands(self) -> Optional[Application]:
        """
        Setup Telegram bot with command handlers
        
        Returns:
            Application instance or None if setup fails
        """
        if not self.bot_token:
            logging.error("TELEGRAM_BOT_TOKEN not found")
            return None
        
        try:
            # Create application with proper configuration
            application = (
                Application.builder()
                .token(self.bot_token)
                .build()
            )
            
            # Add command handlers
            application.add_handler(CommandHandler("start", self.start_command))
            application.add_handler(CommandHandler("help", self.help_command))
            application.add_handler(CommandHandler("status", self.status_command))
            application.add_handler(CommandHandler("run_analysis", self.run_analysis_command))
            application.add_handler(CommandHandler("schedule", self.schedule_command))
            application.add_handler(CommandHandler("test", self.test_command))
            
            logging.info("Bot commands setup completed")
            
            # Set bot commands in Telegram UI
            try:
                from telegram import BotCommand
                commands = [
                    BotCommand("start", "🚀 Welcome and overview"),
                    BotCommand("help", "🆘 Show help message"),
                    BotCommand("status", "📊 System status"),
                    BotCommand("run_analysis", "🔄 Manual pool analysis"),
                    BotCommand("schedule", "📅 View scheduled tasks"),
                    BotCommand("test", "🧪 Test bot functionality")
                ]
                
                # Initialize to set commands
                await application.initialize()
                await application.bot.set_my_commands(commands)
                logging.info("✅ Bot commands registered in Telegram UI")
                
            except Exception as cmd_error:
                logging.warning(f"Could not set bot commands in UI: {cmd_error}")
            
            return application
            
        except Exception as e:
            logging.error(f"Failed to setup bot commands: {e}")
            return None
    
    def _is_authorized(self, chat_id: str) -> bool:
        """Check if user is authorized to use commands"""
        return str(chat_id) == str(self.authorized_chat_id)
    
    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /start command"""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        welcome_message = """🚀 <b>RAYDIUM POOL ANALYZER BOT</b>

Welcome to your automated DeFi portfolio monitoring system!

<b>Available Commands:</b>
/help - Show this help message
/status - System status and health check
/run_analysis - Manually trigger pool analysis
/schedule - View scheduled tasks
/test - Test bot functionality

<b>Automated Schedule:</b>
• 📊 Pool Analysis: Daily at 09:00 & 18:00 UTC
• 🔮 PHI Analysis: Weekly on Sunday at 18:30 UTC

The bot will automatically send analysis reports to this chat."""
        
        await update.message.reply_text(welcome_message, parse_mode='HTML')
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /help command"""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        help_message = """🆘 <b>BOT COMMANDS HELP</b>

<b>📊 Analysis Commands:</b>
/run_analysis - Manually trigger pool analysis
/schedule - View next scheduled tasks

<b>🔧 System Commands:</b>
/status - System health and status
/test - Test bot connectivity

<b>ℹ️ Information Commands:</b>
/help - Show this help message
/start - Welcome message and overview

<b>🤖 Automated Features:</b>
• Daily pool analysis reports
• Weekly PHI AI analysis
• Error alerts and notifications
• Portfolio change alerts (>5%)

<b>📞 Support:</b>
If you encounter issues, check /status first.
The bot runs on Railway with automatic restarts."""
        
        await update.message.reply_text(help_message, parse_mode='HTML')
    
    async def status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /status command"""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            # Update system status
            await self._update_system_status()
            
            # Get next scheduled tasks
            next_tasks = self._get_next_scheduled_tasks()
            self.system_status['next_scheduled_tasks'] = next_tasks
            
            # Format and send status
            status_message = self.formatter.format_status_report(self.system_status)
            await update.message.reply_text(status_message, parse_mode='HTML')
            
        except Exception as e:
            error_msg = f"❌ Error getting system status: {str(e)}"
            await update.message.reply_text(error_msg)
    
    async def run_analysis_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /run_analysis command"""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        # Send immediate response
        await update.message.reply_text("🔄 Starting manual pool analysis...\nThis may take 1-2 minutes.")
        
        try:
            # Trigger analysis through scheduler if available
            if self.scheduler:
                await self.scheduler.run_pool_analysis()
                success_msg = "✅ Manual pool analysis completed successfully!\nReport has been sent to the chat."
            else:
                # Fallback: try to run analysis directly
                from pool_analyzer import main as run_pool_analyzer
                await run_pool_analyzer()
                success_msg = "✅ Pool analysis completed!\nNote: Report may be in text format (scheduler not available)."
            
            await update.message.reply_text(success_msg)
            
        except Exception as e:
            error_msg = f"❌ Failed to run analysis: {str(e)}"
            await update.message.reply_text(error_msg)
            logging.error(f"Manual analysis failed: {e}")
    
    async def schedule_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /schedule command"""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        try:
            next_tasks = self._get_next_scheduled_tasks()
            
            schedule_message = f"""📅 <b>SCHEDULED TASKS</b>

<b>⏰ Next Upcoming Tasks:</b>"""
            
            for task in next_tasks[:5]:  # Show next 5 tasks
                schedule_message += f"\n• {task['name']}: <b>{task['time']}</b>"
            
            schedule_message += f"""

<b>🔄 Regular Schedule:</b>
• Pool Analysis: Daily at 09:00 & 18:00 UTC
• PHI Analysis: Every Sunday at 18:30 UTC

<b>⚙️ System Info:</b>
• Timezone: UTC
• Auto-restart: Enabled
• Health checks: Every 5 minutes

Use /run_analysis to trigger manual analysis."""
            
            await update.message.reply_text(schedule_message, parse_mode='HTML')
            
        except Exception as e:
            error_msg = f"❌ Error getting schedule: {str(e)}"
            await update.message.reply_text(error_msg)
    
    async def test_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Handle /test command"""
        if not self._is_authorized(update.effective_chat.id):
            await update.message.reply_text("❌ Unauthorized access")
            return
        
        test_results = []
        
        # Test 1: Bot connectivity
        try:
            bot_info = await context.bot.get_me()
            test_results.append(f"✅ Bot connection: @{bot_info.username}")
        except Exception as e:
            test_results.append(f"❌ Bot connection: {str(e)}")
        
        # Test 2: Environment variables
        env_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'HELIUS_API_KEY', 'COINGECKO_API_KEY']
        missing_vars = [var for var in env_vars if not os.getenv(var)]
        
        if not missing_vars:
            test_results.append("✅ Environment variables: All set")
        else:
            test_results.append(f"❌ Missing env vars: {', '.join(missing_vars)}")
        
        # Test 3: File system access
        try:
            test_file = "test_write.tmp"
            with open(test_file, 'w') as f:
                f.write("test")
            os.remove(test_file)
            test_results.append("✅ File system: Write access OK")
        except Exception as e:
            test_results.append(f"❌ File system: {str(e)}")
        
        # Test 4: Scheduler status
        if self.scheduler:
            test_results.append("✅ Scheduler: Connected")
        else:
            test_results.append("⚠️ Scheduler: Not connected")
        
        test_message = f"""🧪 <b>SYSTEM TEST RESULTS</b>
📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

""" + "\n".join(test_results)
        
        await update.message.reply_text(test_message, parse_mode='HTML')
    
    async def _update_system_status(self) -> None:
        """Update system status information"""
        try:
            # Check if core files exist
            core_files = ['pool_analyzer.py', 'phi_analyzer.py', 'positions.py']
            missing_files = [f for f in core_files if not os.path.exists(f)]
            
            if missing_files:
                self.system_status['overall_status'] = 'error'
                self.system_status['services']['core_files'] = f'missing: {missing_files}'
            else:
                self.system_status['services']['core_files'] = 'present'
            
            # Check environment variables
            required_env = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'HELIUS_API_KEY']
            missing_env = [var for var in required_env if not os.getenv(var)]
            
            if missing_env:
                self.system_status['overall_status'] = 'error'
                self.system_status['services']['environment'] = f'missing: {missing_env}'
            else:
                self.system_status['services']['environment'] = 'configured'
            
            # Update telegram bot status
            self.system_status['services']['telegram_bot'] = 'running'
            
        except Exception as e:
            logging.error(f"Error updating system status: {e}")
            self.system_status['overall_status'] = 'error'
    
    def _get_next_scheduled_tasks(self) -> list:
        """Get list of next scheduled tasks"""
        now = datetime.now(timezone.utc)
        tasks = []
        
        # Calculate next pool analysis times (09:00 and 18:00 daily)
        for hour in [9, 18]:
            next_time = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if next_time <= now:
                next_time += timedelta(days=1)
            
            tasks.append({
                'name': 'Pool Analysis',
                'time': next_time.strftime('%Y-%m-%d %H:%M UTC'),
                'timestamp': next_time
            })
        
        # Calculate next PHI analysis (Sunday 18:30)
        days_until_sunday = (6 - now.weekday()) % 7
        if days_until_sunday == 0 and now.hour >= 18 and now.minute >= 30:
            days_until_sunday = 7
        
        next_sunday = now + timedelta(days=days_until_sunday)
        next_phi = next_sunday.replace(hour=18, minute=30, second=0, microsecond=0)
        
        tasks.append({
            'name': 'PHI Analysis',
            'time': next_phi.strftime('%Y-%m-%d %H:%M UTC'),
            'timestamp': next_phi
        })
        
        # Sort by timestamp
        tasks.sort(key=lambda x: x['timestamp'])
        
        return tasks
    
    def update_last_analysis_time(self, analysis_type: str, success: bool = True) -> None:
        """Update last analysis time and status"""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        if success:
            self.system_status['last_successful_analysis'] = {
                'type': analysis_type,
                'timestamp': timestamp
            }
            self.system_status['last_error'] = None
        else:
            self.system_status['last_error'] = {
                'type': analysis_type,
                'timestamp': timestamp
            }
    
    def set_service_status(self, service: str, status: str) -> None:
        """Update individual service status"""
        self.system_status['services'][service] = status
        
        # Update overall status based on service statuses
        if any(status == 'error' for status in self.system_status['services'].values()):
            self.system_status['overall_status'] = 'error'
        elif any('warning' in status for status in self.system_status['services'].values()):
            self.system_status['overall_status'] = 'warning'
        else:
            self.system_status['overall_status'] = 'healthy'

# Standalone function to run bot in polling mode (for testing)
async def run_bot_polling():
    """Run bot in polling mode for testing"""
    handler = BotCommandHandler()
    application = await handler.setup_bot_commands()
    
    if application:
        logging.info("Starting bot in polling mode...")
        await application.run_polling()
    else:
        logging.error("Failed to start bot")

# Example usage
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    
    asyncio.run(run_bot_polling()) 