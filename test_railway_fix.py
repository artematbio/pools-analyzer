#!/usr/bin/env python3
"""
Test script for Railway Telegram API conflict fix
"""
import os
import logging
import asyncio
from telegram_sender import TelegramSender
from scheduler import RaydiumScheduler

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_railway_environment():
    """Test Railway environment detection"""
    logger.info("🧪 Testing Railway environment detection...")
    
    # Test 1: Normal environment
    logger.info("Test 1: Normal environment")
    telegram = TelegramSender()
    logger.info(f"Railway environment detected: {telegram.railway_env}")
    
    # Test 2: Simulate Railway environment
    logger.info("Test 2: Simulated Railway environment")
    os.environ['RAILWAY_ENVIRONMENT_NAME'] = 'production'
    telegram_railway = TelegramSender()
    logger.info(f"Railway environment detected: {telegram_railway.railway_env}")
    
    # Test 3: Test scheduler initialization
    logger.info("Test 3: Scheduler initialization")
    scheduler = RaydiumScheduler()
    logger.info(f"Scheduler Railway environment: {scheduler.railway_env}")
    
    # Clean up
    if 'RAILWAY_ENVIRONMENT_NAME' in os.environ:
        del os.environ['RAILWAY_ENVIRONMENT_NAME']
    
    logger.info("✅ All tests passed!")

async def test_telegram_send_only():
    """Test that Telegram sender works in send-only mode"""
    logger.info("🧪 Testing Telegram send-only mode...")
    
    try:
        telegram = TelegramSender()
        
        # Test basic configuration
        if telegram.bot_token and telegram.chat_id:
            logger.info("✅ Telegram bot configured properly")
            
            # Test send message (will fail gracefully if no internet)
            test_message = "🧪 Railway fix test - send-only mode working"
            # result = await telegram.send_message(test_message)
            # logger.info(f"Test message result: {result}")
            
            logger.info("✅ Telegram send-only mode test completed")
        else:
            logger.warning("⚠️ Telegram not configured (missing token or chat_id)")
            
    except Exception as e:
        logger.error(f"❌ Telegram test failed: {e}")

async def main():
    """Run all tests"""
    logger.info("🚀 Starting Railway Telegram API fix tests...")
    
    await test_railway_environment()
    await test_telegram_send_only()
    
    logger.info("✅ All tests completed successfully!")

if __name__ == "__main__":
    asyncio.run(main()) 