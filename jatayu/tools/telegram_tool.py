"""Telegram tool — allows the Brain to proactively send Telegram messages."""

from __future__ import annotations

import os
import httpx
from typing import Any

from jatayu.tools import Tool, ToolRegistry, ToolParam


def register(registry: ToolRegistry) -> None:
    registry.register(Tool(
        name="send_telegram_message",
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
        requires_confirmation=True
    ))


def send_telegram_message(message: str, chat_id: str | None = None, **kwargs) -> Any:
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
        
        if resp.status_code == 200:
            return f"✅ Successfully sent Telegram message to {chat_id}"
        else:
            return f"❌ Failed to send Telegram message: {resp.status_code} {resp.text}"
            
    except Exception as e:
        return f"Error sending Telegram message: {e}"
