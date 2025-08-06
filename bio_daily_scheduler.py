#!/usr/bin/env python3
"""
Bio Daily Scheduler - Ежедневный запуск LP анализа в 9:00 UTC
"""

import asyncio
import schedule
import time
from datetime import datetime, timezone
import logging
from bio_daily_analyzer import main as run_bio_analysis

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def daily_bio_analysis():
    """Запуск ежедневного анализа BIO LP"""
    try:
        print(f"🧬 Запуск ежедневного BIO LP анализа: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        await run_bio_analysis()
        print("✅ Ежедневный анализ завершен")
    except Exception as e:
        print(f"❌ Ошибка ежедневного анализа: {e}")
        logging.error(f"Daily bio analysis failed: {e}")

def schedule_daily_analysis():
    """Настройка расписания ежедневного анализа"""
    # Запуск каждый день в 9:00 UTC
    schedule.every().day.at("09:00").do(lambda: asyncio.run(daily_bio_analysis()))
    
    print("⏰ Планировщик BIO LP анализа запущен")
    print("📅 Расписание: каждый день в 9:00 UTC")
    print(f"🕘 Текущее время UTC: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')}")
    
    # Показываем время до следующего запуска
    next_run = schedule.next_run()
    if next_run:
        print(f"⏭️ Следующий запуск: {next_run.strftime('%Y-%m-%d %H:%M UTC')}")

def run_scheduler():
    """Основной цикл планировщика"""
    schedule_daily_analysis()
    
    try:
        while True:
            schedule.run_pending()
            time.sleep(60)  # Проверяем каждую минуту
    except KeyboardInterrupt:
        print("\n🛑 Планировщик остановлен")
    except Exception as e:
        print(f"❌ Ошибка планировщика: {e}")
        logging.error(f"Scheduler error: {e}")

if __name__ == "__main__":
    # Опция для немедленного тестового запуска
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        print("🧪 Тестовый запуск анализа...")
        asyncio.run(daily_bio_analysis())
    else:
        run_scheduler() 