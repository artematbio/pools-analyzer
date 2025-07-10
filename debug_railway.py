#!/usr/bin/env python3
"""
Debug script to identify Railway startup issues
"""
import os
import sys
import logging

# Setup logging immediately
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def debug_imports():
    """Debug imports step by step"""
    try:
        logger.info("🔍 Starting Railway debug...")
        
        # Check Python version
        logger.info(f"Python version: {sys.version}")
        
        # Check environment variables
        logger.info("🌍 Environment variables:")
        railway_env = os.getenv('RAILWAY_ENVIRONMENT_NAME')
        logger.info(f"  RAILWAY_ENVIRONMENT_NAME: {railway_env}")
        logger.info(f"  PORT: {os.getenv('PORT', 'Not set')}")
        logger.info(f"  TELEGRAM_BOT_TOKEN: {'Set' if os.getenv('TELEGRAM_BOT_TOKEN') else 'Not set'}")
        logger.info(f"  TELEGRAM_CHAT_ID: {'Set' if os.getenv('TELEGRAM_CHAT_ID') else 'Not set'}")
        
        # Test basic imports
        logger.info("📦 Testing basic imports...")
        import asyncio
        logger.info("✅ asyncio imported")
        
        import json
        logger.info("✅ json imported")
        
        from datetime import datetime, timezone, timedelta
        logger.info("✅ datetime imported")
        
        from dotenv import load_dotenv
        logger.info("✅ dotenv imported")
        
        load_dotenv()
        logger.info("✅ .env loaded")
        
        # Test problematic imports
        logger.info("🧪 Testing potentially problematic imports...")
        
        try:
            from aiohttp import web
            logger.info("✅ aiohttp imported")
        except ImportError as e:
            logger.error(f"❌ aiohttp failed: {e}")
            
        try:
            from telegram_sender import TelegramSender
            logger.info("✅ telegram_sender imported")
        except ImportError as e:
            logger.error(f"❌ telegram_sender failed: {e}")
        
        try:
            from report_formatter import ReportFormatter
            logger.info("✅ report_formatter imported")
        except ImportError as e:
            logger.error(f"❌ report_formatter failed: {e}")
        
        try:
            from bot_commands import BotCommandHandler
            logger.info("✅ bot_commands imported")
        except ImportError as e:
            logger.error(f"❌ bot_commands failed: {e}")
        
        try:
            from alerting import alerting_system, AlertLevel
            logger.info("✅ alerting system imported")
        except ImportError as e:
            logger.error(f"❌ alerting system failed: {e}")
        
        logger.info("🎯 All imports successful!")
        
        # Test TelegramSender initialization
        logger.info("🤖 Testing TelegramSender initialization...")
        try:
            telegram = TelegramSender()
            logger.info("✅ TelegramSender created successfully")
        except Exception as e:
            logger.error(f"❌ TelegramSender failed: {e}")
        
        # Test scheduler initialization
        logger.info("⏰ Testing scheduler initialization...")
        try:
            from scheduler import RaydiumScheduler
            logger.info("✅ RaydiumScheduler imported")
            
            scheduler = RaydiumScheduler()
            logger.info("✅ RaydiumScheduler created successfully")
            
            logger.info("🚀 All tests passed! The issue is likely elsewhere.")
            
        except Exception as e:
            logger.error(f"❌ Scheduler initialization failed: {e}")
            import traceback
            logger.error(f"Full traceback:\n{traceback.format_exc()}")
            
    except Exception as e:
        logger.error(f"❌ Critical error in debug: {e}")
        import traceback
        logger.error(f"Full traceback:\n{traceback.format_exc()}")

if __name__ == "__main__":
    debug_imports() 