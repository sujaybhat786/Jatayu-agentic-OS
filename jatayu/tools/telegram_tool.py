"""Telegram tool — allows the Brain to proactively send Telegram messages."""

from __future__ import annotations

import logging
import os
import httpx
from typing import Any

from jatayu.tools import Tool, ToolRegistry, ToolParam

logger = logging.getLogger(__name__)

_TG_ERROR_MAP = {
    400: "❌ Telegram: Invalid chat ID or message format. Check the chat_id.",
    401: "❌ Telegram: Bot token invalid or revoked. Check TELEGRAM_BOT_TOKEN in .env.",
    403: "❌ Telegram: Bot was blocked by the user or chat is unavailable.",
    429: "❌ Telegram: Rate limited by Telegram. Wait 30 seconds and try again.",
}


def register(registry: ToolRegistry) -> None:
    tool_def = Tool(
        name="telegram_send",
        description="Send a proactive message to the user via Telegram.",
        params=[
            ToolParam(
                name="message",
                type="string",
                description="The text message to send.",
                required=True
            ),
            ToolParam(
                name="chat_id",
                type="string",
                description="Optional. The chat ID to send the message to. If not provided, it sends to the first authorized user.",
                required=False
            )
        ],
        handler=send_telegram_message,
        requires_confirmation=False
    )
    registry.register(tool_def)
    # Register alias for backwards compatibility
    alias_def = Tool(
        name="send_telegram_message",
        description="Send a proactive message to the user via Telegram.",
        params=tool_def.params,
        handler=send_telegram_message,
        requires_confirmation=False
    )
    registry.register(alias_def)



def send_telegram_message(message: str, chat_id: str | None = None) -> str:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        return "Error: TELEGRAM_BOT_TOKEN is not configured."

    if not chat_id:
        users = os.getenv("TELEGRAM_AUTHORIZED_USERS", "")
        if not users:
            return "Error: No chat_id provided and TELEGRAM_AUTHORIZED_USERS is not set."
        chat_id = users.split(",")[0].strip()

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": message
        }
        resp = httpx.post(url, json=payload, timeout=10)
        
        if not resp.is_success:
            error_msg = _TG_ERROR_MAP.get(resp.status_code, f"❌ Telegram: Unexpected error {resp.status_code}: {resp.text[:100]}")
            logger.error("Telegram send failed: %s", error_msg)
            return error_msg

        return f"✅ Successfully sent Telegram message to {chat_id}"
            
    except Exception as e:
        return f"Error sending Telegram message: {e}"

