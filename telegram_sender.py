import asyncio
import logging
from typing import Optional, List
import os
from dotenv import load_dotenv

try:
    from telegram import Bot
    from telegram.error import TelegramError, BadRequest, Forbidden, NetworkError
except ImportError:
    print("Warning: python-telegram-bot not installed. Install with: pip install python-telegram-bot")
    Bot = None
    TelegramError = Exception
    BadRequest = Exception
    Forbidden = Exception
    NetworkError = Exception

load_dotenv()

class TelegramSender:
    """
    Telegram Bot API handler for sending messages and documents
    with error handling and message length management
    
    Note: Send-only mode for Railway deployment to prevent API conflicts
    """
    
    def __init__(self):
        self.bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        # Railway-specific: Create bot only if not in polling mode
        self.railway_env = os.getenv('RAILWAY_ENVIRONMENT_NAME') is not None
        
        if self.railway_env:
            logging.info("🚂 Railway environment detected - using send-only mode")
        
        # Lazy initialization of bot to avoid conflicts
        self._bot = None
        self.max_message_length = 4096  # Telegram limit
        self.max_caption_length = 1024  # Telegram caption limit
        
        if not self.bot_token:
            logging.warning("TELEGRAM_BOT_TOKEN not found in environment variables")
        if not self.chat_id:
            logging.warning("TELEGRAM_CHAT_ID not found in environment variables")
    
    @property
    def bot(self):
        """Lazy initialization of bot to avoid conflicts"""
        if self._bot is None and self.bot_token and Bot:
            try:
                self._bot = Bot(token=self.bot_token)
                logging.info("✅ Telegram bot initialized successfully")
            except Exception as e:
                logging.error(f"❌ Failed to initialize Telegram bot: {e}")
                self._bot = None
        return self._bot
            
    async def send_message(self, text: str, parse_mode: str = 'HTML', disable_web_page_preview: bool = True) -> bool:
        """
        Send text message to Telegram chat
        
        Args:
            text: Message text
            parse_mode: 'HTML' or 'Markdown'
            disable_web_page_preview: Disable link previews
            
        Returns:
            bool: Success status
        """
        if not self._is_configured():
            logging.error("Telegram bot not properly configured")
            return False
            
        try:
            # Split message if too long
            if len(text) > self.max_message_length:
                parts = self._split_message(text, self.max_message_length - 100)  # Buffer for safety
                
                for i, part in enumerate(parts):
                    if i > 0:
                        await asyncio.sleep(1)  # Rate limiting
                    
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=part,
                        parse_mode=parse_mode,
                        disable_web_page_preview=disable_web_page_preview
                    )
                    logging.info(f"Sent message part {i+1}/{len(parts)}")
            else:
                await self.bot.send_message(
                    chat_id=self.chat_id,
                    text=text,
                    parse_mode=parse_mode,
                    disable_web_page_preview=disable_web_page_preview
                )
                logging.info("Message sent successfully")
            
            return True
            
        except Forbidden as e:
            logging.error(f"Bot was blocked or chat not found: {e}")
            return False
        except BadRequest as e:
            logging.error(f"Bad request (invalid message format?): {e}")
            return False
        except NetworkError as e:
            logging.error(f"Network error: {e}")
            return False
        except TelegramError as e:
            logging.error(f"Telegram API error: {e}")
            return False
        except Exception as e:
            logging.error(f"Unexpected error sending message: {e}")
            return False
    
    async def send_document(self, document_path: str, caption: str = "", filename: str = None) -> bool:
        """
        Send document to Telegram chat
        
        Args:
            document_path: Path to file
            caption: Document caption
            filename: Custom filename (optional)
            
        Returns:
            bool: Success status
        """
        if not self._is_configured():
            logging.error("Telegram bot not properly configured")
            return False
            
        if not os.path.exists(document_path):
            logging.error(f"Document not found: {document_path}")
            return False
            
        try:
            # Truncate caption if too long
            if len(caption) > self.max_caption_length:
                caption = caption[:self.max_caption_length - 3] + "..."
            
            with open(document_path, 'rb') as doc:
                await self.bot.send_document(
                    chat_id=self.chat_id,
                    document=doc,
                    caption=caption,
                    filename=filename or os.path.basename(document_path)
                )
            
            logging.info(f"Document sent successfully: {document_path}")
            return True
            
        except Exception as e:
            logging.error(f"Error sending document: {e}")
            return False
    
    async def send_photo(self, photo_path: str, caption: str = "") -> bool:
        """
        Send photo to Telegram chat
        
        Args:
            photo_path: Path to image file
            caption: Photo caption
            
        Returns:
            bool: Success status
        """
        if not self._is_configured():
            return False
            
        if not os.path.exists(photo_path):
            logging.error(f"Photo not found: {photo_path}")
            return False
            
        try:
            if len(caption) > self.max_caption_length:
                caption = caption[:self.max_caption_length - 3] + "..."
            
            with open(photo_path, 'rb') as photo:
                await self.bot.send_photo(
                    chat_id=self.chat_id,
                    photo=photo,
                    caption=caption
                )
            
            logging.info(f"Photo sent successfully: {photo_path}")
            return True
            
        except Exception as e:
            logging.error(f"Error sending photo: {e}")
            return False
    
    async def send_alert(self, title: str, message: str, alert_type: str = "INFO") -> bool:
        """
        Send formatted alert message
        
        Args:
            title: Alert title
            message: Alert message
            alert_type: "INFO", "WARNING", "ERROR", "SUCCESS"
            
        Returns:
            bool: Success status
        """
        emoji_map = {
            "INFO": "ℹ️",
            "WARNING": "⚠️", 
            "ERROR": "❌",
            "SUCCESS": "✅"
        }
        
        emoji = emoji_map.get(alert_type.upper(), "📢")
        
        formatted_message = f"""
{emoji} <b>{title}</b>

{message}

<i>Time: {self._get_current_time()}</i>
"""
        
        return await self.send_message(formatted_message)
    
    def _is_configured(self) -> bool:
        """Check if bot is properly configured"""
        return self.bot is not None and self.chat_id is not None
    
    def _split_message(self, text: str, max_length: int) -> List[str]:
        """
        Split long message into parts respecting word boundaries
        
        Args:
            text: Text to split
            max_length: Maximum length per part
            
        Returns:
            List of message parts
        """
        if len(text) <= max_length:
            return [text]
        
        parts = []
        current_part = ""
        
        # Split by lines first
        lines = text.split('\n')
        
        for line in lines:
            # If single line is too long, split by words
            if len(line) > max_length:
                words = line.split(' ')
                for word in words:
                    if len(current_part + word + '\n') > max_length:
                        if current_part:
                            parts.append(current_part.rstrip())
                            current_part = word + ' '
                        else:
                            # Single word too long, force split
                            parts.append(word[:max_length])
                            current_part = word[max_length:] + ' '
                    else:
                        current_part += word + ' '
            else:
                # Check if adding this line exceeds limit
                if len(current_part + line + '\n') > max_length:
                    if current_part:
                        parts.append(current_part.rstrip())
                        current_part = line + '\n'
                    else:
                        parts.append(line)
                else:
                    current_part += line + '\n'
        
        # Add remaining part
        if current_part.strip():
            parts.append(current_part.rstrip())
        
        return parts
    
    def _get_current_time(self) -> str:
        """Get current time in UTC format"""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    
    async def test_connection(self, send_test_message: bool = False) -> bool:
        """
        Test bot connection and permissions
        
        Args:
            send_test_message: Whether to send a test message (optional)
        
        Returns:
            bool: Connection status
        """
        if not self._is_configured():
            return False
            
        try:
            bot_info = await self.bot.get_me()
            logging.info(f"Bot connected successfully: @{bot_info.username}")
            
            # Only send test message if explicitly requested
            if send_test_message:
                test_message = "🔧 Bot connection test successful"
                await self.send_message(test_message)
            
            return True
            
        except Exception as e:
            logging.error(f"Bot connection test failed: {e}")
            return False

    async def test_connection_with_message(self) -> bool:
        """
        Test bot connection and send a test message
        
        Returns:
            bool: Connection status
        """
        return await self.test_connection(send_test_message=True)

# Convenience functions for quick usage
async def send_quick_message(text: str) -> bool:
    """Quick function to send a message"""
    sender = TelegramSender()
    return await sender.send_message(text)

async def send_quick_alert(title: str, message: str, alert_type: str = "INFO") -> bool:
    """Quick function to send an alert"""
    sender = TelegramSender()
    return await sender.send_alert(title, message, alert_type)

# Example usage
if __name__ == "__main__":
    async def test_telegram():
        sender = TelegramSender()
        
        # Test connection
        if await sender.test_connection_with_message():
            print("✅ Telegram bot is working!")
            
            # Test long message
            long_text = "This is a test message. " * 200
            await sender.send_message(long_text)
            
            # Test alert
            await sender.send_alert("Test Alert", "This is a test alert message", "SUCCESS")
        else:
            print("❌ Telegram bot configuration failed")
    
    asyncio.run(test_telegram()) 