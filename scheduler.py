import asyncio
import logging
import os
import subprocess
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, Callable
from dataclasses import dataclass
from enum import Enum
import signal
import sys
from dotenv import load_dotenv
import glob

# Web server for health checks
try:
    from aiohttp import web, ClientSession
    import aiohttp_cors
except ImportError:
    print("Warning: aiohttp not installed. Install with: pip install aiohttp aiohttp-cors")
    web = None

from telegram_sender import TelegramSender
from report_formatter import ReportFormatter
from bot_commands import BotCommandHandler
from alerting import alerting_system, AlertLevel

load_dotenv()

class TaskStatus(Enum):
    """Task execution status"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"

@dataclass
class ScheduledTask:
    """Scheduled task definition"""
    name: str
    cron_expression: str  # Simple format: "0 9 * * *" (minute hour day month weekday)
    function: Callable
    description: str = ""
    enabled: bool = True
    last_run: Optional[datetime] = None
    last_status: TaskStatus = TaskStatus.PENDING
    last_error: Optional[str] = None
    execution_count: int = 0

class RaydiumScheduler:
    """
    Main scheduler for the Raydium Pool Analyzer system
    Handles task scheduling, health checks, and system coordination
    """
    
    def __init__(self):
        # Initialize components
        self.telegram = TelegramSender()
        self.formatter = ReportFormatter()
        self.bot_handler = BotCommandHandler(scheduler_instance=self)
        
        # Check Railway environment
        self.railway_env = os.getenv('RAILWAY_ENVIRONMENT_NAME') is not None
        if self.railway_env:
            logging.info("🚂 Railway deployment detected - Telegram polling disabled")
        
        # Server configuration
        self.port = int(os.getenv('PORT', 8080))
        self.target_wallet = os.getenv('TARGET_WALLET_ADDRESS', 'BpvSz1bQ7qHb7qAD748TREgSPBp6i6kukukNVgX49uxD')
        self.startup_time = datetime.now(timezone.utc)
        self.running = False
        
        # Task management
        self.tasks: Dict[str, ScheduledTask] = {}
        self._setup_scheduled_tasks()
        
        # Enable fast analyzer mode for scheduled tasks
        self._use_fast_analyzer = False
        
        # System health monitoring
        self.system_health = {
            'status': 'starting',
            'startup_time': self.startup_time.isoformat(),
            'uptime': 0,
            'last_health_check': None,
            'services': {
                'telegram_bot': 'checking',
                'core_files': 'checking'
            }
        }
        
        logging.info("Raydium Scheduler initialized with fast analyzer mode disabled")
    
    def _setup_scheduled_tasks(self):
        """Setup all scheduled tasks"""
        
        # Pool analysis - twice daily
        self.tasks['pool_analysis_morning'] = ScheduledTask(
            name="Pool Analysis (Morning)",
            cron_expression="0 9 * * *",  # 09:00 UTC daily
            function=self.run_pool_analysis,
            description="Daily morning portfolio analysis"
        )
        
        self.tasks['pool_analysis_evening'] = ScheduledTask(
            name="Pool Analysis (Evening)", 
            cron_expression="0 18 * * *",  # 18:00 UTC daily
            function=self.run_pool_analysis,
            description="Daily evening portfolio analysis"
        )
        
        # PHI analysis - weekly on Sunday
        self.tasks['phi_analysis_weekly'] = ScheduledTask(
            name="PHI Analysis (Weekly)",
            cron_expression="30 18 * * 0",  # 18:30 UTC on Sunday
            function=self.run_phi_analysis,
            description="Weekly AI-powered market analysis"
        )
        
        # Health check - every 5 minutes
        self.tasks['health_check'] = ScheduledTask(
            name="Health Check",
            cron_expression="*/5 * * * *",  # Every 5 minutes
            function=self.perform_health_check,
            description="System health monitoring"
        )
        
        # Out of range positions check - every 30 minutes
        self.tasks['out_of_range_check'] = ScheduledTask(
            name="Out of Range Positions Check",
            cron_expression="*/30 * * * *",  # Every 30 minutes
            function=self.check_out_of_range_positions,
            description="Check for out of range positions and send alerts"
        )
        
        # Daily alert summary - if needed
        self.tasks['daily_alert_summary'] = ScheduledTask(
            name="Daily Alert Summary",
            cron_expression="0 23 * * *",  # 23:00 UTC daily
            function=self.send_daily_summary,
            description="Daily summary of alerts and issues"
        )
    
    async def start(self):
        """Start the scheduler and all services"""
        logging.info("🚀 Starting Raydium Scheduler...")
        
        self.running = True
        
        # Disable bot commands handler to prevent Telegram API conflicts in Railway
        bot_app = None  # await self.bot_handler.setup_bot_commands()
        
        # Send startup notification
        await alerting_system.send_startup_notification()
        
        # Start web server for health checks
        if web:
            web_app = await self._setup_web_server()
            
            # Start both web server and task scheduler
            await asyncio.gather(
                self._run_web_server(web_app),
                self._run_task_scheduler(),
                self._run_bot_handler(bot_app) if bot_app else self._dummy_coroutine()
            )
        else:
            # Run without web server
            await asyncio.gather(
                self._run_task_scheduler(),
                self._run_bot_handler(bot_app) if bot_app else self._dummy_coroutine()
            )
    
    async def _dummy_coroutine(self):
        """Dummy coroutine for when bot is not available"""
        while self.running:
            await asyncio.sleep(60)
    
    async def _setup_web_server(self):
        """Setup web server for health checks"""
        app = web.Application()
        
        # Setup CORS
        cors = aiohttp_cors.setup(app, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
                allow_methods="*"
            )
        })
        
        # Add routes
        app.router.add_get('/health', self.health_endpoint)
        app.router.add_get('/status', self.status_endpoint)
        app.router.add_get('/tasks', self.tasks_endpoint)
        app.router.add_post('/trigger/{task_name}', self.trigger_task_endpoint)
        
        # Add CORS to all routes
        for route in list(app.router.routes()):
            cors.add(route)
        
        return app
    
    async def _run_web_server(self, app):
        """Run the web server"""
        runner = web.AppRunner(app)
        await runner.setup()
        
        site = web.TCPSite(runner, '0.0.0.0', self.port)
        await site.start()
        
        logging.info(f"🌐 Web server started on port {self.port}")
        
        # Keep running
        while self.running:
            await asyncio.sleep(1)
    
    async def _run_task_scheduler(self):
        """Main task scheduling loop"""
        logging.info("⏰ Task scheduler started")
        
        while self.running:
            try:
                current_time = datetime.now(timezone.utc)
                
                # Check each task
                for task_id, task in self.tasks.items():
                    if not task.enabled:
                        continue
                    
                    if self._should_run_task(task, current_time):
                        await self._execute_task(task)
                
                # Update system uptime
                self.system_health['uptime'] = int((current_time - self.startup_time).total_seconds())
                
                # Sleep for 30 seconds before next check
                await asyncio.sleep(30)
                
            except Exception as e:
                logging.error(f"Error in task scheduler: {e}")
                await alerting_system.send_error_alert("Task Scheduler", str(e))
                await asyncio.sleep(60)  # Wait longer on error
    
    async def _run_bot_handler(self, bot_app):
        """Run the Telegram bot handler (send-only mode for Railway)"""
        # Note: Disabled polling to prevent conflicts in Railway deployment
        # Only send-only functionality is used via telegram_sender.py
        logging.info("🤖 Telegram bot handler initialized (send-only mode)")
        
        try:
            # Keep the handler alive but without polling
            while self.running:
                await asyncio.sleep(10)  # Check every 10 seconds
                
        except Exception as e:
            logging.error(f"Bot handler error: {e}")
            
        logging.info("🤖 Telegram bot handler stopped")
    
    def _should_run_task(self, task: ScheduledTask, current_time: datetime) -> bool:
        """Check if task should run based on cron expression"""
        if task.last_run is None:
            # Never run before, check if it's time
            return self._matches_cron(task.cron_expression, current_time)
        
        # Check if enough time has passed and cron matches
        time_diff = current_time - task.last_run
        
        # Don't run same task within 1 minute
        if time_diff < timedelta(minutes=1):
            return False
        
        return self._matches_cron(task.cron_expression, current_time)
    
    def _matches_cron(self, cron_expr: str, dt: datetime) -> bool:
        """Simple cron expression matcher"""
        try:
            parts = cron_expr.split()
            if len(parts) != 5:
                return False
            
            minute, hour, day, month, weekday = parts
            
            # Check minute
            if minute != "*" and not self._matches_cron_field(minute, dt.minute, 0, 59):
                return False
            
            # Check hour
            if hour != "*" and not self._matches_cron_field(hour, dt.hour, 0, 23):
                return False
            
            # Check day of month
            if day != "*" and not self._matches_cron_field(day, dt.day, 1, 31):
                return False
            
            # Check month
            if month != "*" and not self._matches_cron_field(month, dt.month, 1, 12):
                return False
            
            # Check weekday (0 = Sunday)
            if weekday != "*" and not self._matches_cron_field(weekday, dt.weekday() + 1 % 7, 0, 6):
                return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error parsing cron expression '{cron_expr}': {e}")
            return False
    
    def _matches_cron_field(self, field: str, value: int, min_val: int, max_val: int) -> bool:
        """Match individual cron field"""
        if field == "*":
            return True
        
        if "," in field:
            # Multiple values: "1,3,5"
            return value in [int(x) for x in field.split(",")]
        
        if "/" in field:
            # Step values: "*/5" or "0-30/5"
            if field.startswith("*/"):
                step = int(field[2:])
                return value % step == 0
            else:
                range_part, step = field.split("/")
                if range_part == "*":
                    return value % int(step) == 0
                else:
                    start, end = map(int, range_part.split("-"))
                    return start <= value <= end and (value - start) % int(step) == 0
        
        if "-" in field:
            # Range: "9-17"
            start, end = map(int, field.split("-"))
            return start <= value <= end
        
        # Single value
        return value == int(field)
    
    async def _execute_task(self, task: ScheduledTask):
        """Execute a scheduled task"""
        task.last_run = datetime.now(timezone.utc)
        task.last_status = TaskStatus.RUNNING
        
        logging.info(f"🔄 Executing task: {task.name}")
        
        start_time = time.time()
        
        try:
            # Execute the task function
            await task.function()
            
            # Task completed successfully
            execution_time = time.time() - start_time
            task.last_status = TaskStatus.SUCCESS
            task.execution_count += 1
            task.last_error = None
            
            logging.info(f"✅ Task completed: {task.name} ({execution_time:.1f}s)")
            
            # Update bot handler status
            self.bot_handler.update_last_analysis_time(task.name, success=True)
            
        except Exception as e:
            # Task failed
            execution_time = time.time() - start_time
            task.last_status = TaskStatus.FAILED
            task.last_error = str(e)
            
            logging.error(f"❌ Task failed: {task.name} - {e}")
            
            # Send error alert
            await alerting_system.send_error_alert(
                f"Scheduled Task: {task.name}",
                str(e),
                f"Execution time: {execution_time:.1f}s",
                AlertLevel.ERROR
            )
            
            # Update bot handler status
            self.bot_handler.update_last_analysis_time(task.name, success=False)
    
    async def run_pool_analysis(self):
        """Execute pool analysis"""
        try:
            logging.info("Starting pool analysis...")
            
            # Log current directory and existing files
            current_dir = os.getcwd()
            existing_reports = glob.glob('raydium_pool_report_*.txt')
            logging.info(f"Current directory: {current_dir}")
            logging.info(f"Existing report files before analysis: {len(existing_reports)}")
            
            # Try fast analyzer first (for scheduled tasks)
            if hasattr(self, '_use_fast_analyzer') and self._use_fast_analyzer:
                logging.info("Using fast pool analyzer for scheduled task...")
                script_name = 'pool_analyzer_fast.py'
                timeout = 120  # 2 minutes for fast analyzer
            else:
                logging.info("Using optimized main pool analyzer...")
                script_name = 'pool_analyzer.py'
                timeout = 240  # 4 minutes for optimized analyzer (was 10 minutes)
            
            # Run the pool analyzer
            result = subprocess.run([
                'python3', script_name
            ], capture_output=True, text=True, timeout=timeout)
            
            if result.returncode != 0:
                logging.error(f"Pool analyzer stdout: {result.stdout}")
                logging.error(f"Pool analyzer stderr: {result.stderr}")
                
                # If fast analyzer failed, try full analyzer as fallback
                if script_name == 'pool_analyzer_fast.py':
                    logging.info("Fast analyzer failed, trying full analyzer as fallback...")
                    result = subprocess.run([
                        'python3', 'pool_analyzer.py'
                    ], capture_output=True, text=True, timeout=600)
                    
                    if result.returncode != 0:
                        raise Exception(f"Both analyzers failed. Last error: {result.stderr}")
                else:
                    raise Exception(f"Pool analyzer failed: {result.stderr}")
            
            # Find the latest report file
            report_files = glob.glob('raydium_pool_report_*.txt')
            if not report_files:
                # List all .txt files to debug
                all_txt_files = glob.glob('*.txt')
                logging.error(f"No raydium_pool_report_*.txt files found. All .txt files: {all_txt_files}")
                raise Exception("No report file generated")
            
            latest_report = max(report_files, key=os.path.getctime)
            logging.info(f"Found latest report file: {latest_report}")
            
            # Check if report is recent (generated in last 5 minutes)
            report_time = os.path.getctime(latest_report)
            current_time = time.time()
            if current_time - report_time > 300:  # 5 minutes
                logging.warning(f"Report file is old: {datetime.fromtimestamp(report_time)}")
                # Still proceed but log the warning
            
            # Read and format the report
            with open(latest_report, 'r') as f:
                report_content = f.read()
            
            if len(report_content) < 100:  # Sanity check
                raise Exception(f"Report file seems too small: {len(report_content)} characters")
            
            logging.info(f"Report content length: {len(report_content)} characters")
            
            formatted_report_parts = self.formatter.format_pool_report(report_content)
            logging.info(f"Formatted report split into {len(formatted_report_parts)} parts")
            
            # Send all parts to Telegram
            success = True
            for i, part in enumerate(formatted_report_parts):
                logging.info(f"Sending part {i+1}/{len(formatted_report_parts)}, length: {len(part)} characters")
                
                # Add small delay between messages to avoid rate limiting
                if i > 0:
                    await asyncio.sleep(1)
                
                part_success = await self.telegram.send_message(part)
                if not part_success:
                    logging.error(f"Failed to send report part {i+1}")
                    success = False
                    break
            
            if not success:
                raise Exception("Failed to send complete report to Telegram")
            
            # Extract portfolio value for change monitoring
            total_value = self.formatter._extract_total_value(report_content)
            if total_value > 0:
                await alerting_system.check_portfolio_changes(total_value)
            
            # Keep report file for PHI analyzer, but clean up old files (older than 14 days)
            await self._cleanup_old_report_files()
            
            # Log final state
            final_reports = glob.glob('raydium_pool_report_*.txt')
            logging.info(f"Final report files count: {len(final_reports)}")
            logging.info(f"Pool analysis completed successfully. Report saved: {latest_report}")
            
        except subprocess.TimeoutExpired:
            raise Exception(f"Pool analysis timed out after {timeout} seconds")
        except Exception as e:
            logging.error(f"Pool analysis failed: {e}")
            raise
    
    def set_fast_analyzer_mode(self, use_fast: bool = True):
        """Set whether to use fast analyzer for scheduled tasks"""
        self._use_fast_analyzer = use_fast
        logging.info(f"Fast analyzer mode: {'enabled' if use_fast else 'disabled'}")

    async def _cleanup_old_report_files(self):
        """Clean up report files older than 14 days to save space"""
        try:
            # Find all report files
            report_files = glob.glob('raydium_pool_report_*.txt')
            analysis_files = glob.glob('*anomaly_analysis*.txt')
            
            cutoff_time = datetime.now() - timedelta(days=14)
            
            files_removed = 0
            for file_path in report_files + analysis_files:
                try:
                    file_time = datetime.fromtimestamp(os.path.getctime(file_path))
                    if file_time < cutoff_time:
                        os.remove(file_path)
                        files_removed += 1
                        logging.debug(f"Removed old file: {file_path}")
                except Exception as e:
                    logging.warning(f"Could not remove old file {file_path}: {e}")
            
            if files_removed > 0:
                logging.info(f"Cleaned up {files_removed} old report/analysis files")
                
        except Exception as e:
            logging.warning(f"Error during file cleanup: {e}")

    async def run_phi_analysis(self):
        """Execute PHI analysis"""
        try:
            logging.info("Starting PHI analysis...")
            
            # Run the PHI analyzer
            result = subprocess.run([
                'python3', 'phi_analyzer.py'
            ], capture_output=True, text=True, timeout=600)  # 10 minute timeout
            
            if result.returncode != 0:
                raise Exception(f"PHI analyzer failed: {result.stderr}")
            
            # Find the latest analysis file
            analysis_files = glob.glob('*anomaly_analysis*.txt')
            if not analysis_files:
                raise Exception("No PHI analysis file generated")
            
            latest_analysis = max(analysis_files, key=os.path.getctime)
            
            # Read and format the analysis
            with open(latest_analysis, 'r') as f:
                analysis_content = f.read()
            
            formatted_analysis = self.formatter.format_phi_analysis(analysis_content)
            
            # Send to Telegram
            success = await self.telegram.send_message(formatted_analysis)
            
            if not success:
                raise Exception("Failed to send PHI analysis to Telegram")
            
            # Keep analysis file but clean up old files (done in _cleanup_old_report_files)
            await self._cleanup_old_report_files()
            
            logging.info(f"PHI analysis completed successfully. Analysis saved: {latest_analysis}")
            
        except subprocess.TimeoutExpired:
            raise Exception("PHI analysis timed out after 10 minutes")
        except Exception as e:
            logging.error(f"PHI analysis failed: {e}")
            raise
    
    async def perform_health_check(self):
        """Perform system health check"""
        try:
            self.system_health['last_health_check'] = datetime.now(timezone.utc).isoformat()
            
            # Check if core files exist
            core_files = ['pool_analyzer.py', 'phi_analyzer.py', 'positions.py']
            missing_files = [f for f in core_files if not os.path.exists(f)]
            
            if missing_files:
                self.system_health['status'] = 'error'
                self.system_health['services']['core_files'] = f'missing: {missing_files}'
            else:
                self.system_health['services']['core_files'] = 'present'
            
            # Check Telegram connectivity
            try:
                if await self.telegram.test_connection():
                    self.system_health['services']['telegram_bot'] = 'connected'
                else:
                    self.system_health['services']['telegram_bot'] = 'disconnected'
            except:
                self.system_health['services']['telegram_bot'] = 'error'
            
            # Update overall status
            service_statuses = list(self.system_health['services'].values())
            if any('error' in status or 'missing' in status for status in service_statuses):
                self.system_health['status'] = 'error'
            elif any('disconnected' in status for status in service_statuses):
                self.system_health['status'] = 'warning'
            else:
                self.system_health['status'] = 'healthy'
            
            # Send health alert if needed
            if self.system_health['status'] != 'healthy':
                await alerting_system.send_system_health_alert(self.system_health)
            
        except Exception as e:
            logging.error(f"Health check failed: {e}")
            self.system_health['status'] = 'error'
    
    async def check_out_of_range_positions(self):
        """Check for out of range positions and send alerts"""
        try:
            logging.info("🔍 Checking out of range positions...")
            
            # Use the alerting system to check positions
            alert_sent = await alerting_system.check_out_of_range_positions()
            
            if alert_sent:
                logging.info("✅ Out of range positions alert sent")
            else:
                logging.debug("✅ No out of range positions or alert rate limited")
                
        except Exception as e:
            logging.error(f"❌ Out of range positions check failed: {e}")
            await alerting_system.send_error_alert(
                "Out of Range Check",
                f"Failed to check out of range positions: {str(e)}",
                "Scheduled task execution"
            )
    
    async def send_daily_summary(self):
        """Send daily alert summary if needed"""
        try:
            await alerting_system.send_daily_alert_summary()
        except Exception as e:
            logging.error(f"Failed to send daily summary: {e}")
    
    # Web endpoints
    async def health_endpoint(self, request):
        """Health check endpoint for Railway"""
        return web.json_response({
            'status': 'healthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime': self.system_health['uptime'],
            'version': '1.0.0'
        })
    
    async def status_endpoint(self, request):
        """Detailed status endpoint"""
        task_statuses = {}
        for task_id, task in self.tasks.items():
            task_statuses[task_id] = {
                'name': task.name,
                'last_run': task.last_run.isoformat() if task.last_run else None,
                'last_status': task.last_status.value,
                'execution_count': task.execution_count,
                'enabled': task.enabled
            }
        
        return web.json_response({
            'system_health': self.system_health,
            'tasks': task_statuses,
            'startup_time': self.startup_time.isoformat()
        })
    
    async def tasks_endpoint(self, request):
        """Tasks overview endpoint"""
        tasks_info = []
        for task_id, task in self.tasks.items():
            tasks_info.append({
                'id': task_id,
                'name': task.name,
                'description': task.description,
                'cron_expression': task.cron_expression,
                'enabled': task.enabled,
                'last_run': task.last_run.isoformat() if task.last_run else None,
                'last_status': task.last_status.value,
                'execution_count': task.execution_count
            })
        
        return web.json_response({'tasks': tasks_info})
    
    async def trigger_task_endpoint(self, request):
        """Manually trigger a task"""
        task_name = request.match_info['task_name']
        
        if task_name not in self.tasks:
            return web.json_response({'error': 'Task not found'}, status=404)
        
        task = self.tasks[task_name]
        
        # Execute task in background
        asyncio.create_task(self._execute_task(task))
        
        return web.json_response({
            'message': f'Task {task.name} triggered',
            'task_id': task_name
        })
    
    def stop(self):
        """Stop the scheduler"""
        logging.info("🛑 Stopping Raydium Scheduler...")
        self.running = False

# Signal handlers for graceful shutdown
def signal_handler(scheduler):
    def handler(signum, frame):
        logging.info(f"Received signal {signum}")
        scheduler.stop()
        sys.exit(0)
    return handler

# Main entry point
async def main():
    """Main entry point for the scheduler"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    scheduler = RaydiumScheduler()
    
    # Setup signal handlers
    signal.signal(signal.SIGINT, signal_handler(scheduler))
    signal.signal(signal.SIGTERM, signal_handler(scheduler))
    
    try:
        await scheduler.start()
    except KeyboardInterrupt:
        logging.info("Received keyboard interrupt")
    except Exception as e:
        logging.error(f"Scheduler crashed: {e}")
        await alerting_system.send_error_alert("System Failure", str(e), level=AlertLevel.CRITICAL)
    finally:
        scheduler.stop()

if __name__ == "__main__":
    asyncio.run(main()) 