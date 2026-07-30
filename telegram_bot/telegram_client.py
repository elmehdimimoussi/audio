"""
Async Telegram Bot API client for Webhook Service.
"""

import logging
import re
from typing import Any, Dict, Optional, Tuple

import httpx

from telegram_bot.config import Settings

logger = logging.getLogger("telegram_client")


class TelegramClient:
    """Async Telegram API client for immediate webhook replies and status edits."""

    def __init__(self, settings: Settings):
        self.token = settings.TELEGRAM_BOT_TOKEN.strip()
        self.base_url = settings.TELEGRAM_API_BASE_URL.rstrip("/")

    def sanitize_error(self, message: str) -> str:
        if not message:
            return "Unknown error"
        sanitized = str(message)
        if self.token and self.token in sanitized:
            sanitized = sanitized.replace(self.token, "[REDACTED_TOKEN]")
        sanitized = re.sub(r"bot[0-9]+:[A-Za-z0-9_-]+", "bot[REDACTED_TOKEN]", sanitized)
        return sanitized

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: Optional[str] = "HTML",
        reply_to_message_id: Optional[int] = None,
    ) -> Tuple[bool, Optional[int], str]:
        """
        Send text message to Telegram chat.
        Returns (success: bool, message_id: Optional[int], error_msg: str).
        """
        if not self.token:
            return False, None, "TELEGRAM_BOT_TOKEN is missing."

        url = f"{self.base_url}/bot{self.token}/sendMessage"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    msg_id = data.get("result", {}).get("message_id")
                    return True, msg_id, "Message sent successfully."
                else:
                    desc = self.sanitize_error(data.get("description", "Telegram API error"))
                    return False, None, desc
            except Exception as e:
                safe_err = self.sanitize_error(str(e))
                logger.error(f"Failed to send Telegram message to chat_id={chat_id}: {safe_err}")
                return False, None, safe_err

    async def edit_message(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        parse_mode: Optional[str] = "HTML",
    ) -> Tuple[bool, str]:
        """
        Edit existing status message in Telegram chat.
        Returns (success: bool, error_msg: str).
        """
        if not self.token:
            return False, "TELEGRAM_BOT_TOKEN is missing."

        url = f"{self.base_url}/bot{self.token}/editMessageText"
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=10.0)) as client:
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                data = response.json()
                if data.get("ok"):
                    return True, "Message edited successfully."
                else:
                    desc = self.sanitize_error(data.get("description", "Telegram API error"))
                    return False, desc
            except Exception as e:
                safe_err = self.sanitize_error(str(e))
                if "message is not modified" in safe_err.lower():
                    return True, "Message not modified."
                logger.error(f"Failed to edit Telegram message message_id={message_id}: {safe_err}")
                return False, safe_err
