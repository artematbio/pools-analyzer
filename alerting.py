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
            
            # Filter out of range positions AND exclude closed positions
            current_out_of_range_positions = []
            for pos in all_positions:
                # ✅ ИСПРАВЛЕНИЕ: Проверяем что позиция активна (не закрыта)
                liquidity_raw = pos.get('liquidity', '0')
                try:
                    liquidity_value = float(str(liquidity_raw))
                except Exception:
                    liquidity_value = 0.0
                
                # Проверяем стоимость позиции
                try:
                    position_value = float(pos.get('position_value_usd', 0) or 0)
                except Exception:
                    position_value = 0.0
                
                # Позиция должна быть out of range, иметь ликвидность и минимальную стоимость
                if (pos.get('in_range') is False and 
                    liquidity_value > 0 and 
                    position_value >= 100):
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
    
    async def check_range_proximity_positions(self) -> bool:
        """
        Проверяет позиции, приближающиеся к границам диапазона (5% порог)
        
        Returns:
            bool: True if alert was sent
        """
        try:
            # Import здесь чтобы избежать circular import
            from range_proximity_calculator import filter_positions_approaching_bounds
            from database_handler import supabase_handler
            import httpx
            import os
            
            # Получаем позиции из всех сетей через Supabase (более быстро и надежно)
            if not supabase_handler or not supabase_handler.is_connected():
                logging.warning("Supabase не подключен для proximity checks")
                return False
            
            # Получаем все позиции из Supabase (свежие данные за последние 3 дня)
            from datetime import datetime, timezone, timedelta
            cutoff_date = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
            
            positions_result = supabase_handler.client.table('lp_position_snapshots').select(
                'position_mint, pool_name, pool_id, network, position_value_usd, tick_lower, tick_upper, created_at, liquidity'
            ).gte('created_at', cutoff_date).order('created_at', desc=True).execute()
            
            if not positions_result.data:
                logging.info("Нет позиций для proximity проверки")
                return False
            
            # Убираем дублирование - берем только последнюю запись для каждой position_mint
            unique_positions = {}
            
            for pos in positions_result.data:
                pos_mint = pos['position_mint']
                if pos_mint not in unique_positions:
                    unique_positions[pos_mint] = pos

            # Фильтруем позиции без ликвидности (закрытые/обнуленные) и минимальной стоимости
            filtered_unique_positions = {}
            for mint, pos in unique_positions.items():
                liquidity_raw = pos.get('liquidity', '0')
                try:
                    liquidity_value = float(str(liquidity_raw))
                except Exception:
                    liquidity_value = 0.0
                
                # Проверяем стоимость позиции
                try:
                    position_value = float(pos.get('position_value_usd', 0) or 0)
                except Exception:
                    position_value = 0.0
                
                # Позиция должна иметь и ликвидность, и минимальную стоимость $100
                if liquidity_value > 0 and position_value >= 100:
                    filtered_unique_positions[mint] = pos
            unique_positions = filtered_unique_positions

            # Дополнительно: отсекаем устаревшие снапшоты (по умолчанию старше 24 часов)
            try:
                from datetime import datetime, timezone, timedelta
                max_age_hours = int(os.getenv('PROXIMITY_MAX_SNAPSHOT_AGE_HOURS', '24'))
                fresh_positions = {}
                now_ts = datetime.now(timezone.utc)
                for mint, pos in unique_positions.items():
                    try:
                        created_at = datetime.fromisoformat(pos['created_at'].replace('Z', '+00:00'))
                        age_hours = (now_ts - created_at).total_seconds() / 3600.0
                        if age_hours <= max_age_hours:
                            fresh_positions[mint] = pos
                    except Exception:
                        # Если дата некорректная, безопасно пропускаем позицию
                        continue
                unique_positions = fresh_positions
            except Exception:
                # В случае любых ошибок оставляем текущий набор позиций
                pass

            # Пересобираем список пулов, для которых нужны current_tick
            pool_ids_needed = set()
            for pos in unique_positions.values():
                pool_ids_needed.add((pos['pool_id'], pos['network']))
            
            # 🔧 ИСПРАВЛЕНИЕ: Получаем текущие тики пулов (гибридный подход)
            pool_ticks = {}
            for pool_id, network in pool_ids_needed:
                if network in ['ethereum', 'base']:
                    # Ethereum/Base: используем tick_current из lp_pool_snapshots
                    pool_result = supabase_handler.client.table('lp_pool_snapshots').select(
                        'tick_current'
                    ).eq('pool_address', pool_id).eq('network', network).order(
                        'created_at', desc=True
                    ).limit(1).execute()
                    
                    if pool_result.data and pool_result.data[0]['tick_current'] is not None:
                        pool_ticks[(pool_id, network)] = pool_result.data[0]['tick_current']
                        
                elif network == 'solana':
                    # Solana: аппроксимируем current_tick из позиций (tick_current всегда None)
                    solana_positions = supabase_handler.client.table('lp_position_snapshots').select(
                        'tick_lower, tick_upper, in_range, current_price, created_at'
                    ).eq('pool_id', pool_id).eq('network', network).order(
                        'created_at', desc=True
                    ).limit(5).execute()
                    
                    if solana_positions.data:
                        # Используем самую свежую позицию для аппроксимации
                        latest_pos = solana_positions.data[0]
                        tick_lower = latest_pos.get('tick_lower')
                        tick_upper = latest_pos.get('tick_upper') 
                        in_range = latest_pos.get('in_range')
                        
                        if tick_lower is not None and tick_upper is not None:
                            if in_range:
                                # Позиция в диапазоне - аппроксимируем середину
                                estimated_tick = (tick_lower + tick_upper) // 2
                            else:
                                # Позиция вне диапазона - ищем другие позиции для уточнения
                                out_of_range_positions = [p for p in solana_positions.data if not p.get('in_range', True)]
                                if out_of_range_positions:
                                    # Если несколько позиций вне диапазона, берем тик ниже самого нижнего
                                    min_tick_lower = min(p.get('tick_lower', 999999) for p in out_of_range_positions if p.get('tick_lower'))
                                    estimated_tick = min_tick_lower - 100  # Значительно ниже диапазона
                                else:
                                    # Единственная позиция вне диапазона - предполагаем ниже
                                    estimated_tick = tick_lower - 50
                            
                            pool_ticks[(pool_id, network)] = estimated_tick
                            logging.info(f"🔧 Solana {pool_id[:8]}... estimated tick: {estimated_tick} (in_range: {in_range})")
            
            # Адаптируем данные для range_proximity_calculator
            all_positions = []
            for pos in unique_positions.values():
                pool_key = (pos['pool_id'], pos['network'])
                current_tick = pool_ticks.get(pool_key)
                
                # Только позиции с полными данными для proximity расчетов
                if all(x is not None for x in [pos['tick_lower'], pos['tick_upper'], current_tick]):
                    adapted_pos = {
                        'position_mint': pos['position_mint'],
                        'pool_name': pos['pool_name'],
                        'network': pos['network'],
                        'position_value_usd': pos['position_value_usd'],
                        'tick_lower': pos['tick_lower'],
                        'tick_upper': pos['tick_upper'],
                        'current_tick': current_tick,
                        'fees_usd': 0  # Для совместимости с formatter
                    }
                    all_positions.append(adapted_pos)
            
            logging.info(f"📊 Range proximity check: {len(all_positions)} позиций из {len(unique_positions)} (Solana: {len([p for p in all_positions if p['network'] == 'solana'])}, Ethereum: {len([p for p in all_positions if p['network'] == 'ethereum'])}, Base: {len([p for p in all_positions if p['network'] == 'base'])})")
            
            # Фильтруем позиции, приближающиеся к границам (5% порог)
            approaching_positions = filter_positions_approaching_bounds(all_positions, threshold_percent=5.0)
            
            now = datetime.now(timezone.utc)
            
            # Если нет приближающихся позиций, очищаем состояние
            if len(approaching_positions) == 0:
                if hasattr(self, 'last_proximity_positions') and self.last_proximity_positions:
                    # Все позиции больше не приближаются к границам
                    recovery_message = f"""✅ <b>RANGE PROXIMITY RECOVERY</b>

🎉 No positions are approaching range boundaries!

All positions are now safely within their ranges.

<i>Time: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}</i>"""
                    
                    success = await self.telegram.send_message(recovery_message)
                    
                    if success:
                        alert = Alert(
                            level=AlertLevel.INFO,
                            title="Range Proximity Recovery",
                            message="No positions approaching boundaries",
                            context="Recovery from proximity warnings"
                        )
                        self._record_alert(alert)
                        logging.info("✅ Proximity recovery alert sent")
                        
                        # Очищаем состояние
                        self.last_proximity_positions = []
                        self.last_proximity_alert_time = now
                        return True
                
                # Очищаем состояние
                self.last_proximity_positions = []
                logging.debug("✅ No positions approaching range boundaries")
                return False
            
            # Проверяем изменения в приближающихся позициях
            if not hasattr(self, 'last_proximity_positions'):
                self.last_proximity_positions = []
                self.last_proximity_alert_time = None
            
            # Сравниваем с предыдущими результатами
            positions_changed = self._compare_proximity_positions(
                approaching_positions, 
                self.last_proximity_positions
            )
            
            should_send_alert = False
            alert_reason = ""
            
            if positions_changed:
                # Позиции изменились - отправляем алерт немедленно
                should_send_alert = True
                alert_reason = "proximity_changes"
                logging.info(f"📊 Range proximity changes detected: {len(approaching_positions)} positions")
            else:
                # Нет изменений - проверяем ежедневный интервал
                if self.last_proximity_alert_time is None:
                    should_send_alert = True
                    alert_reason = "first_proximity_detection"
                    logging.info(f"📊 First proximity detection: {len(approaching_positions)} positions")
                else:
                    time_since_last_alert = now - self.last_proximity_alert_time
                    if time_since_last_alert >= self.daily_alert_interval:
                        should_send_alert = True
                        alert_reason = "daily_proximity_reminder"
                        logging.info(f"📊 Daily proximity reminder: {len(approaching_positions)} positions")
                    else:
                        hours_remaining = (self.daily_alert_interval - time_since_last_alert).total_seconds() / 3600
                        logging.debug(f"📊 Proximity positions unchanged, next alert in {hours_remaining:.1f} hours")
            
            # Отправляем алерт если нужно
            if should_send_alert:
                alert_message = self.formatter.format_range_proximity_alert(approaching_positions)
                
                # Добавляем контекст причины
                if alert_reason == "proximity_changes":
                    alert_message += f"\n\n🔄 <b>Reason:</b> Position proximity changes detected"
                elif alert_reason == "daily_proximity_reminder":
                    alert_message += f"\n\n🕒 <b>Reason:</b> Daily reminder (proximity unchanged)"
                elif alert_reason == "first_proximity_detection":
                    alert_message += f"\n\n🆕 <b>Reason:</b> Initial proximity detection"
                
                success = await self.telegram.send_message(alert_message)
                
                if success:
                    alert = Alert(
                        level=AlertLevel.WARNING,
                        title="Range Proximity Warning",
                        message=f"{len(approaching_positions)} positions approaching boundaries ({alert_reason})",
                        context=f"Positions: {[pos.get('position_mint', 'N/A')[:8] for pos in approaching_positions]}"
                    )
                    self._record_alert(alert)
                    
                    # Обновляем состояние отслеживания
                    self.last_proximity_positions = approaching_positions.copy()
                    self.last_proximity_alert_time = now
                    
                    logging.info(f"✅ Range proximity alert sent: {len(approaching_positions)} positions ({alert_reason})")
                    return True
                else:
                    logging.error("❌ Failed to send range proximity alert")
            else:
                # Обновляем состояние без отправки алерта
                self.last_proximity_positions = approaching_positions.copy()
            
            return False
            
        except Exception as e:
            logging.error(f"Error checking range proximity: {e}")
            await self.send_error_alert("Range Proximity Check", str(e), level=AlertLevel.WARNING)
            return False
    
    def _compare_proximity_positions(self, current_positions: List[Dict[str, Any]], 
                                   previous_positions: Optional[List[Dict[str, Any]]]) -> bool:
        """
        Сравнивает текущие и предыдущие позиции, приближающиеся к границам
        
        Args:
            current_positions: Текущий список приближающихся позиций
            previous_positions: Предыдущий список приближающихся позиций
            
        Returns:
            bool: True если позиции изменились
        """
        if previous_positions is None:
            return len(current_positions) > 0
        
        # Сравниваем количество
        if len(current_positions) != len(previous_positions):
            return True
        
        # Сравниваем позиции по mint address
        current_mints = set(pos.get('position_mint', '') for pos in current_positions)
        previous_mints = set(pos.get('position_mint', '') for pos in previous_positions)
        
        if current_mints != previous_mints:
            return True
        
        # Проверяем изменения в proximity статусе
        for current_pos in current_positions:
            mint = current_pos.get('position_mint', '')
            previous_pos = next((p for p in previous_positions if p.get('position_mint', '') == mint), None)
            
            if previous_pos:
                current_proximity = current_pos.get('proximity_info', {})
                previous_proximity = previous_pos.get('proximity_info', {})
                
                # Проверяем изменения в статусе приближения
                current_status = current_proximity.get('proximity_status', '')
                previous_status = previous_proximity.get('proximity_status', '')
                
                if current_status != previous_status:
                    return True
                
                # Проверяем значительные изменения в процентах (>1%)
                current_lower = current_proximity.get('distance_to_lower_percent', 0)
                current_upper = current_proximity.get('distance_to_upper_percent', 0)
                previous_lower = previous_proximity.get('distance_to_lower_percent', 0)
                previous_upper = previous_proximity.get('distance_to_upper_percent', 0)
                
                if (abs(current_lower - previous_lower) > 1.0 or 
                    abs(current_upper - previous_upper) > 1.0):
                    return True
        
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
            startup_message = f"""🚀 <b>MULTICHAIN SYSTEM STARTUP</b>

✅ Multi-Chain Pool Analyzer is now online
📅 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

<b>Services Started:</b>
• Multi-Chain Pool Analyzer (Solana + Ethereum + Base)
• DAO Pools Snapshot Generator
• Ethereum/Base Positions Analyzer
• Telegram Bot
• Scheduler
• Alerting System

<b>Active Networks:</b>
🟣 Solana (Raydium CLMM)
🔵 Ethereum (Uniswap V3) 
🔵 Base (Uniswap V3)

<b>Schedule:</b>
• Solana Positions: Every 4 hours (00:00, 04:00, 08:00, 12:00, 16:00, 20:00)
• Ethereum Positions: Every 4 hours (+20min offset)
• Base Positions: Every 4 hours (+40min offset)
• DAO Pools Snapshots: Every 4 hours after positions (+70min)
• Multi-Chain Reports: 2x daily (13:30 & 21:30 UTC)
• PHI Analysis: Sunday 18:30 UTC

🔄 Multi-chain system ready for automated monitoring"""
            
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