import os
import json
import httpx
import asyncio
from datetime import datetime, timedelta
import re
from typing import List, Dict, Optional
from openai import OpenAI

# Constants
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"
MODEL_NAME = "gpt-4.1"  # или "gpt-4" если нужна именно базовая модель

# Load environment variables
# Replace with your actual OpenAI API key or set as environment variable
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY', 'your_openai_api_key_here'))

def get_report_files_current_week() -> List[Dict[str, str]]:
    """Get text report files from Monday of current week to today (inclusive)."""
    # Look for files matching the pattern raydium_pool_report_*.txt
    all_report_files = [f for f in os.listdir() if f.startswith("raydium_pool_report_") and f.endswith(".txt")]
    
    if not all_report_files:
        return []
    
    # Parse dates from filenames and sort by date
    dated_files = []
    for filename in all_report_files:
        # Extract timestamp from filename: raydium_pool_report_YYYYMMDD_HHMMSS.txt
        match = re.search(r'raydium_pool_report_(\d{8})_(\d{6})\.txt', filename)
        if match:
            date_str = match.group(1)  # YYYYMMDD
            time_str = match.group(2)  # HHMMSS
            try:
                file_date = datetime.strptime(f"{date_str}_{time_str}", "%Y%m%d_%H%M%S")
                dated_files.append({
                    "filename": filename,
                    "date": file_date,
                    "date_str": file_date.strftime("%Y-%m-%d"),
                    "time_str": file_date.strftime("%H:%M:%S"),
                    "weekday": file_date.weekday(),  # 0=Monday, 6=Sunday
                    "weekday_name": file_date.strftime("%A")
                })
            except ValueError:
                continue
    
    # Sort by date (newest first)
    dated_files.sort(key=lambda x: x["date"], reverse=True)
    
    # Calculate start of current week (Monday)
    today = datetime.now().date()
    today_weekday = today.weekday()  # 0=Monday, 6=Sunday
    
    # Calculate how many days to go back to reach Monday
    days_since_monday = today_weekday
    monday_date = today - timedelta(days=days_since_monday)
    
    # Generate all dates from Monday to today
    target_dates = []
    current_date = monday_date
    while current_date <= today:
        target_dates.append(current_date)
        current_date += timedelta(days=1)
    
    # Find latest file for each day of the week
    result_files = []
    for target_date in target_dates:
        target_date_str = target_date.strftime("%Y-%m-%d")
        # Find the latest file for this date
        for file_info in dated_files:
            if file_info["date_str"] == target_date_str:
                result_files.append(file_info)
                break
    
    # Return in chronological order (Monday first, today last)
    result_files.reverse()
    
    return result_files

def read_report_content(filename: str) -> Optional[str]:
    """Read and return content of a report file."""
    try:
        with open(filename, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"Error reading {filename}: {e}")
        return None

def extract_detailed_pool_data(content: str, date_str: str, time_str: str) -> Dict:
    """Extract detailed pool data with better understanding of time context."""
    data = {
        "report_date": date_str,
        "report_time": time_str,
        "is_early_morning": time_str < "06:00:00",  # Report created early morning
        "pools": {}
    }
    
    # Extract total portfolio stats
    pos_match = re.search(r'Всего CLMM позиций:\s*(\d+)', content)
    value_match = re.search(r'Общая стоимость всех позиций:\s*\$([0-9,]+\.?\d*)', content)
    
    if pos_match:
        data["total_positions"] = int(pos_match.group(1))
    if value_match:
        data["total_value_usd"] = float(value_match.group(1).replace(',', ''))
    
    # Find all pool sections
    pool_pattern = r'--- АНАЛИЗ ПУЛА: ([^(]+)\s*\([^)]+\) ---(.*?)(?=--- АНАЛИЗ ПУЛА:|ДРУГИЕ ПУЛЫ|$)'
    pool_matches = re.findall(pool_pattern, content, re.DOTALL)
    
    for pool_name, pool_content in pool_matches:
        pool_name = pool_name.strip()
        pool_data = {"name": pool_name}
        
        # Extract basic metrics
        tvl_match = re.search(r'Общая ликвидность пула \(TVL\):\s*\$([0-9,]+\.?\d*)', pool_content)
        vol_24h_match = re.search(r'Объем торгов за 24 часа:\s*\$([0-9,]+\.?\d*)', pool_content)
        vol_7d_match = re.search(r'Объем торгов за 7 дней:\s*\$([0-9,]+\.?\d*)', pool_content)
        
        if tvl_match:
            pool_data["tvl_usd"] = float(tvl_match.group(1).replace(',', ''))
        if vol_24h_match:
            pool_data["volume_24h_usd"] = float(vol_24h_match.group(1).replace(',', ''))
        if vol_7d_match:
            pool_data["volume_7d_usd"] = float(vol_7d_match.group(1).replace(',', ''))
        
        # Extract position data
        pos_count_match = re.search(r'Активные позиции:\s*(\d+)', pool_content)
        pos_value_match = re.search(r'Общая стоимость позиций:\s*~?\$([0-9,]+\.?\d*)', pool_content)
        pending_yield_match = re.search(r'Общий Pending Yield:\s*~?\$([0-9,]+\.?\d*)', pool_content)
        
        if pos_count_match:
            pool_data["positions_count"] = int(pos_count_match.group(1))
        if pos_value_match:
            pool_data["positions_value_usd"] = float(pos_value_match.group(1).replace(',', ''))
        if pending_yield_match:
            pool_data["pending_yield_usd"] = float(pending_yield_match.group(1).replace(',', ''))
        
        # Extract daily volumes (skip today if report is early morning)
        daily_volumes = []
        daily_volume_pattern = r'- (\d{4}-\d{2}-\d{2}):\s*\$([0-9,]+\.?\d*)'
        daily_matches = re.findall(daily_volume_pattern, pool_content)
        
        for vol_date, volume in daily_matches:
            volume_float = float(volume.replace(',', ''))
            # Skip today's volume if it's 0 and report is early morning
            if vol_date == date_str and volume_float == 0.0 and data["is_early_morning"]:
                continue
            daily_volumes.append({
                "date": vol_date,
                "volume_usd": volume_float
            })
        
        pool_data["daily_volumes"] = daily_volumes
        
        # Extract BitQuery data quality indicators
        bitquery_records = re.search(r'Всего записей \(агрегированных\):\s*(\d+)', pool_content)
        bitquery_trades = re.search(r'Общее кол-во сделок:\s*(\d+)', pool_content)
        
        if bitquery_records:
            pool_data["bitquery_records"] = int(bitquery_records.group(1))
        if bitquery_trades:
            pool_data["bitquery_trades"] = int(bitquery_trades.group(1))
        
        # Data quality assessment
        pool_data["data_quality"] = "good"
        if pool_data.get("bitquery_records", 0) == 0:
            pool_data["data_quality"] = "no_historical_data"
        elif pool_data.get("volume_7d_usd", 0) == 0 and pool_data.get("volume_24h_usd", 0) > 0:
            pool_data["data_quality"] = "partial_data"
        
        data["pools"][pool_name] = pool_data
    
    return data

def create_smart_anomaly_prompt(reports_data: List[Dict]) -> tuple:
    """Create intelligent prompt that understands data context and quality."""
    
    system_prompt = """Ты — эксперт DeFi-аналитик с глубоким пониманием данных CLMM пулов.

КРИТИЧЕСКИ ВАЖНО для корректной интерпретации данных:

📊 ОСОБЕННОСТИ ДАННЫХ BitQuery:
- Исторические данные обновляются с задержкой (обычно 6-12 часов)
- Данные за текущий день могут быть НЕПОЛНЫМИ даже во второй половине дня
- Данные за предыдущие дни содержат ПОЛНЫЕ 24-часовые периоды
- Поэтому сравнение "сегодня < вчера" часто НЕ означает снижение, а просто неполные данные

🚫 НЕ СЧИТАЙ СНИЖЕНИЕМ:
- Если данные за текущий день меньше предыдущего дня - это может быть просто неполные данные
- Если объем сегодня = 0 и отчет создан рано утром - это нормально
- Если 7-дневный объем = 0 но есть ежедневные данные - это проблема API, не рынка

✅ АНАЛИЗИРУЙ КАК РЕАЛЬНЫЕ ИЗМЕНЕНИЯ:
- Сравнения между полными историческими днями (вчера vs позавчера vs 3 дня назад)
- Недельные тренды по полным дням
- Изменения в TVL и стоимости позиций (эти данные актуальные)
- Изменения в количестве позиций и yield (эти данные актуальные)

🎯 ФОКУС АНАЛИЗА:
1. Реальные изменения между ПОЛНЫМИ историческими периодами
2. Недельные паттерны активности (какие дни недели активнее)
3. Структурные изменения в позициях и TVL
4. Проблемы с качеством данных BitQuery
5. Долгосрочные тренды (сравнение недель между собой)

⚠️ ОСОБЫЕ УКАЗАНИЯ:
- Всегда упоминай о неполности данных за текущий день
- Если видишь "снижение" в последний день - поясни, что это может быть артефакт данных
- Концентрируйся на трендах между полными днями
- При анализе объемов используй фразы типа "на основе полных данных за предыдущие дни"

ОТВЕЧАЙ ТОЛЬКО на русском, конкретно и по делу."""
    
    # Build intelligent data summary
    data_summary = "ДАННЫЕ ЗА ТЕКУЩУЮ НЕДЕЛЮ:\n\n"
    
    # Calculate week info
    if reports_data:
        monday_date = reports_data[0].get('date_str', 'неизвестно')
        today_date = reports_data[-1].get('date_str', 'неизвестно')
        today_time = reports_data[-1].get('time_str', 'неизвестно')
        data_summary += f"📅 Анализируемый период: {monday_date} (понедельник) → {today_date}\n"
        data_summary += f"📊 Дней в анализе: {len(reports_data)}\n"
        data_summary += f"⚠️ ВАЖНО: Данные за {today_date} (последний отчет в {today_time}) могут быть НЕПОЛНЫМИ из-за задержки обновления BitQuery\n\n"
    
    for i, report_info in enumerate(reports_data):
        weekday_name = report_info.get('weekday_name', 'Неизвестно')
        report_date = report_info.get('date_str', 'неизвестно')
        report_time = report_info.get('time_str', 'неизвестно')
        is_early = report_info.get('is_early_morning', False)
        
        data_summary += f"=== {weekday_name.upper()} ({report_date} в {report_time}) ===\n"
        if is_early:
            data_summary += "⚠️ ОТЧЕТ СОЗДАН РАНО УТРОМ - объемы за текущий день могут быть неполными\n"
        
        if 'metrics' in report_info:
            metrics = report_info['metrics']
            data_summary += f"Портфель: {metrics.get('total_positions', 'н/д')} позиций, ${metrics.get('total_value_usd', 0):,.2f}\n\n"
            
            for pool_name, pool in metrics.get('pools', {}).items():
                data_summary += f"🏊 {pool_name}:\n"
                data_summary += f"   TVL: ${pool.get('tvl_usd', 0):,.2f}\n"
                data_summary += f"   Объем 24ч: ${pool.get('volume_24h_usd', 0):,.2f}\n"
                data_summary += f"   Объем 7д: ${pool.get('volume_7d_usd', 0):,.2f}\n"
                data_summary += f"   Позиции: {pool.get('positions_count', 0)} (${pool.get('positions_value_usd', 0):,.2f})\n"
                
                # Data quality indicator
                quality = pool.get('data_quality', 'unknown')
                if quality == 'no_historical_data':
                    data_summary += f"   ⚠️ Нет исторических данных BitQuery\n"
                elif quality == 'partial_data':
                    data_summary += f"   ⚠️ Частичные исторические данные\n"
                
                # Yield info
                if pool.get('pending_yield_usd'):
                    data_summary += f"   Yield: ${pool.get('pending_yield_usd', 0):,.2f}\n"
                
                # Daily volumes (only meaningful data)
                daily_vols = pool.get('daily_volumes', [])
                if daily_vols:
                    data_summary += f"   Дневные объемы: "
                    recent_vols = daily_vols[-7:]  # Last 7 meaningful days
                    vol_str = ", ".join([f"{dv['date'][-5:]}: ${dv['volume_usd']:,.0f}" for dv in recent_vols])
                    data_summary += vol_str + "\n"
                
                data_summary += "\n"
        
        data_summary += "\n"
    
    user_prompt = f"""{data_summary}

ЗАДАЧА: Найди РЕАЛЬНЫЕ аномалии и недельные тренды (НЕ артефакты данных):

🗓️ **НЕДЕЛЬНЫЙ АНАЛИЗ ОБЪЕМОВ**
⚠️ КРИТИЧЕСКИ ВАЖНО: Данные за последний день могут быть НЕПОЛНЫМИ!
- Сравнивай объемы только между ПОЛНЫМИ историческими днями (не включая последний день)
- Если видишь "снижение" в последний день - это вероятно неполные данные, а НЕ реальное снижение
- Ищи резкие изменения (>50%) только между полными днями
- Анализируй недельные тренды по историческим дням
- Выяви паттерны активности по дням недели (на основе полных данных)

💰 **НЕДЕЛЬНЫЙ АНАЛИЗ ПОЗИЦИЙ**
✅ Эти данные АКТУАЛЬНЫЕ и надежные:
- Изменения в стоимости позиций в течение недели
- Изменения в количестве позиций  
- Динамика Pending Yield за неделю
- Эффективность позиций по дням

🏗️ **СТРУКТУРНЫЕ ИЗМЕНЕНИЯ**
✅ Эти данные АКТУАЛЬНЫЕ и надежные:
- Изменения TVL пулов в течение недели
- Появление/исчезновение позиций
- Проблемы с качеством данных по дням

⚠️ **ПРОБЛЕМЫ С ДАННЫМИ**
- Дни с отсутствующими историческими данными BitQuery
- Неполные данные за текущий день (это НОРМАЛЬНО)
- Несоответствия между 24ч и 7д объемами (только по полным дням)
- Качество данных по дням недели

📈 **НЕДЕЛЬНЫЕ ТРЕНДЫ**
- Общие тенденции торговой активности (на основе ПОЛНЫХ дней)
- Лучшие и худшие дни недели для каждого пула (исключая последний неполный день)
- Сравнение начала недели с серединой (НЕ с последним неполным днем)

🚫 СТРОГО ЗАПРЕЩЕНО:
- Считать низкие объемы последнего дня "снижением" или "проблемой"
- Анализировать тренды с включением последнего неполного дня
- Делать выводы о "резком падении" на основе последнего дня

✅ ОБЯЗАТЕЛЬНО УКАЗЫВАЙ:
- "На основе полных данных за предыдущие дни..."
- "Исключая неполные данные за последний день..."
- "Данные за [последняя дата] могут быть неполными из-за задержки обновления"

ТРЕБОВАНИЯ:
- Фокусируйся на трендах между ПОЛНЫМИ историческими днями
- При упоминании последнего дня всегда оговаривай неполность данных
- Указывай КОНКРЕТНЫЕ цифры и процентные изменения между полными днями
- Приоритизируй находки по надежным данным (TVL, позиции, yield)
- Выяви недельные паттерны на основе исторических данных"""

    return system_prompt, user_prompt

async def get_analysis_from_openai(api_key: str, system_prompt: str, user_prompt: str) -> Optional[str]:
    """Send request to OpenAI API and get analysis from GPT-4."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "max_tokens": 2500,
        "temperature": 0.1  # Low temperature for more focused, analytical responses
    }
    
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                OPENAI_API_URL,
                headers=headers,
                json=payload,
                timeout=300  # 5-minute timeout
            )
            
            response.raise_for_status()
            data = response.json()
            
            # Extract the response text from the API response
            if data and "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            else:
                print("API response did not contain expected data: ", data)
                return None
                
    except httpx.HTTPStatusError as e:
        print(f"HTTP error occurred: {e.response.status_code} - {e.response.text}")
        return None
    except httpx.RequestError as e:
        print(f"Request error occurred: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

def save_analysis_to_file(analysis_text: str, reports_count: int) -> str:
    """Save the received analysis to a text file with timestamp."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"weekly_anomaly_analysis_{reports_count}days_{timestamp}.txt"
    
    header = f"""НЕДЕЛЬНЫЙ АНАЛИЗ АНОМАЛИЙ RAYDIUM CLMM
Дата анализа: {datetime.now().strftime('%d.%m.%Y %H:%M')}
Проанализировано дней: {reports_count}
Период: С понедельника текущей недели до сегодня
Модель: {MODEL_NAME}
Версия: Weekly Smart Analysis v2.2 - Улучшенная интерпретация неполных данных

{'='*70}

"""
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(header + analysis_text)
    
    return filename

async def main():
    try:
        print("🧠 Запуск НЕДЕЛЬНОГО анализатора аномалий для Raydium CLMM...")
        print("📅 Версия 2.2 - улучшенная интерпретация неполных данных")
        
        # Get report files for current week
        report_files = get_report_files_current_week()
        
        if not report_files:
            print("❌ Не найдено файлов отчетов за текущую неделю.")
            print("Запустите pool_analyzer.py для генерации отчетов.")
            return
        
        # Show week summary
        if report_files:
            monday_date = report_files[0]['date_str']
            today_date = report_files[-1]['date_str']
            print(f"📅 Анализируемый период: {monday_date} (понедельник) → {today_date}")
            print(f"📊 Найдено {len(report_files)} дней:")
        
        # Load and process reports with intelligent parsing
        reports_data = []
        for file_info in report_files:
            weekday_emoji = ["📅", "📊", "📈", "📉", "📋", "🎯", "🎉"][file_info['weekday']]
            print(f"  {weekday_emoji} {file_info['weekday_name']}: {file_info['filename']}")
            print(f"      Время создания: {file_info['date_str']} в {file_info['time_str']}")
            
            content = read_report_content(file_info['filename'])
            if content:
                # Extract detailed metrics with context awareness
                metrics = extract_detailed_pool_data(
                    content, 
                    file_info['date_str'], 
                    file_info['time_str']
                )
                
                reports_data.append({
                    "filename": file_info['filename'],
                    "date_str": file_info['date_str'],
                    "time_str": file_info['time_str'],
                    "weekday_name": file_info['weekday_name'],
                    "is_early_morning": metrics["is_early_morning"],
                    "content": content,
                    "metrics": metrics
                })
                
                # Show data quality summary
                pools_with_issues = sum(1 for pool in metrics["pools"].values() 
                                      if pool.get("data_quality") != "good")
                if pools_with_issues:
                    print(f"      ⚠️ {pools_with_issues} пулов с проблемами данных")
                    
            else:
                print(f"      ❌ Ошибка чтения файла")
        
        if not reports_data:
            print("❌ Не удалось загрузить данные ни из одного отчета.")
            return
        
        print(f"\n✅ Успешно загружено {len(reports_data)} отчетов за неделю")
        
        # Create intelligent prompt for analysis
        system_prompt, user_prompt = create_smart_anomaly_prompt(reports_data)
        print("🧠 Создан недельный промпт с контекстным анализом...")
        
        # Get analysis from OpenAI API
        print("🚀 Отправка запроса в OpenAI API...")
        print("⏱️  Выполняется недельный анализ...")
        
        analysis = await get_analysis_from_openai(os.getenv('OPENAI_API_KEY', 'your_openai_api_key_here'), system_prompt, user_prompt)
        
        if analysis:
            # Save analysis to file
            output_file = save_analysis_to_file(analysis, len(reports_data))
            print(f"\n✅ Недельный анализ сохранен: {output_file}")
            
            # Print summary to console
            print("\n📊 РЕЗУЛЬТАТ НЕДЕЛЬНОГО АНАЛИЗА:")
            print("=" * 60)
            # Show first meaningful lines of analysis
            lines = analysis.split('\n')
            shown_lines = 0
            for line in lines:
                if line.strip():
                    print(f"  {line}")
                    shown_lines += 1
                    if shown_lines >= 15:  # Show more lines for better overview
                        break
            
            if len([l for l in lines if l.strip()]) > 15:
                print("  ...")
                print(f"  📄 Полный недельный анализ в файле: {output_file}")
                
        else:
            print("❌ Не удалось получить анализ от OpenAI API.")
    
    except Exception as e:
        print(f"❌ Ошибка в main: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 