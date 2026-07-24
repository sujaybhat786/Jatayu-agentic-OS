"""Telegram Bot API adapter.

Implements the CommunicationAdapter interface using the Telegram Bot API.
All calls use httpx (already a project dependency) — no new packages.

Configuration:
  TELEGRAM_BOT_TOKEN — from @BotFather on Telegram

API reference: https://core.telegram.org/bots/api
"""

from __future__ import annotations

import logging

import httpx

from jatayu.comms.adapter import CommunicationAdapter, ProviderCapabilities

logger = logging.getLogger(__name__)

_API_BASE = "https://api.telegram.org/bot{token}"
_FILE_BASE = "https://api.telegram.org/file/bot{token}/{file_path}"

# Telegram message character limit
_MAX_MSG_LENGTH = 4096


class TelegramAdapter(CommunicationAdapter):
    """Telegram Bot API implementation of CommunicationAdapter.

    Handles sending text, media, typing indicators via the Bot API.
    Media download is a two-step process: getFile → download bytes.

    Args:
        token: Telegram Bot API token from @BotFather.
    """

    def __init__(self, token: str) -> None:
        self._token = token
        self._base = _API_BASE.format(token=token)
        logger.info("Telegram adapter initialized")

    @property
    def provider_name(self) -> str:
        return "telegram"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_text=True,
            supports_images=True,
            supports_documents=True,
            supports_audio=True,
            supports_video=True,
            supports_location=False,         # sending location not needed yet
            supports_typing_indicator=True,
            supports_read_receipts=False,    # Telegram bots can't mark as read
            supports_message_threads=True,   # reply_to_message_id
            supports_markdown=True,          # MarkdownV2 supported
            supports_html=True,
            max_message_length=_MAX_MSG_LENGTH,
            supports_groups=True,
            supports_group_mention_trigger=True,
            supports_voice_input=True,       # receives voice notes
            supports_voice_output=False,     # TTS voice reply — Phase 2
        )

    def _url(self, method: str) -> str:
        return f"{self._base}/{method}"

    # ── Sending ──

    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
    ) -> dict:
        """Send a text message via sendMessage."""
        import re
        
        # 1. Strip <think> blocks completely
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = text.strip()
        
        if not text:
            return {"status": "ignored", "reason": "empty after stripping think block"}

        # 2. Escape HTML special chars to prevent Telegram 400 Bad Request
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        
        # 3. Convert basic markdown to Telegram HTML
        # Code blocks: ```...\ncode\n```
        text = re.sub(r"```(?:\w+)?\n(.*?)```", r"<pre>\1</pre>", text, flags=re.DOTALL)
        # Inline code: `code`
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        # Bold: **bold**
        text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
        # Italic: *italic* (we already did bold so single * is safe)
        text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
        # Links: [text](url) -> url inside href is safe because it's not converted by the < escape, wait! 
        # The URL might have & in it which was converted to &amp;, that's fine for HTML.
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)

        payload: dict = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_to_id:
            try:
                payload["reply_to_message_id"] = int(reply_to_id)
            except (ValueError, TypeError):
                pass

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(self._url("sendMessage"), json=payload)
                resp.raise_for_status()
                data = resp.json()
                msg_id = str(data.get("result", {}).get("message_id", ""))
                logger.info("Telegram text sent to %s (msg_id: %s)", chat_id, msg_id)
                return {"status": "sent", "message_id": msg_id}
        except httpx.HTTPStatusError as e:
            logger.error("Telegram sendMessage HTTP %s: %s", e.response.status_code, e.response.text[:300])
            # Fallback: try without parse_mode if HTML caused the error
            try:
                payload.pop("parse_mode", None)
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(self._url("sendMessage"), json=payload)
                    resp.raise_for_status()
                    return {"status": "sent"}
            except Exception as e2:
                logger.error("Telegram sendMessage fallback also failed: %s", e2)
                return {"status": "error", "error": str(e2)}
        except Exception as e:
            logger.error("Telegram send_text failed: %s", e)
            return {"status": "error", "error": str(e)}

    async def send_media(
        self,
        chat_id: str,
        media_bytes: bytes,
        media_type: str,
        filename: str | None = None,
        caption: str | None = None,
    ) -> dict:
        """Send media via the appropriate Telegram method."""
        method_map = {
            "image":    ("sendPhoto",    "photo"),
            "audio":    ("sendAudio",    "audio"),
            "document": ("sendDocument", "document"),
            "video":    ("sendVideo",    "video"),
            "voice":    ("sendVoice",    "voice"),
        }
        method_name, field_name = method_map.get(media_type, ("sendDocument", "document"))
        fname = filename or f"file.{self._ext(media_type)}"

        data: dict = {"chat_id": chat_id}
        if caption:
            data["caption"] = caption

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(
                    self._url(method_name),
                    data=data,
                    files={field_name: (fname, media_bytes)},
                )
                resp.raise_for_status()
                logger.info("Telegram %s sent to %s", method_name, chat_id)
                return {"status": "sent"}
        except Exception as e:
            logger.error("Telegram send_media (%s) failed: %s", media_type, e)
            return {"status": "error", "error": str(e)}

    # ── Status ──

    async def send_typing_indicator(self, chat_id: str) -> None:
        """Show 'typing...' indicator — Telegram supports this natively."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    self._url("sendChatAction"),
                    json={"chat_id": chat_id, "action": "typing"},
                )
        except Exception:
            pass  # Best-effort

    async def mark_as_read(self, message_id: str) -> None:
        """No-op — Telegram bots cannot mark messages as read."""
        pass

    # ── Media download ──

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download Telegram media by file_id.

        Two-step:
          1. getFile(file_id) → file_path
          2. GET /file/bot<token>/<file_path> → bytes
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: Get file_path
                resp = await client.get(
                    self._url("getFile"),
                    params={"file_id": media_id},
                )
                resp.raise_for_status()
                file_info = resp.json().get("result", {})
                file_path = file_info.get("file_path", "")

                if not file_path:
                    raise ValueError(f"No file_path returned for file_id {media_id}")

                # Step 2: Download bytes
                file_url = _FILE_BASE.format(token=self._token, file_path=file_path)
                dl_resp = await client.get(file_url)
                dl_resp.raise_for_status()

                # Infer MIME type from extension
                mime = self._mime_from_path(file_path)
                logger.info(
                    "Downloaded Telegram media %s (%s, %d bytes)",
                    media_id, mime, len(dl_resp.content)
                )
                return dl_resp.content, mime

        except Exception as e:
            logger.error("Telegram media download failed: %s", e)
            raise

    # ── Helpers ──

    @staticmethod
    def _ext(media_type: str) -> str:
        return {"image": "jpg", "audio": "mp3", "video": "mp4",
                "voice": "ogg", "document": "bin"}.get(media_type, "bin")

    @staticmethod
    def _mime_from_path(file_path: str) -> str:
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        return {
            "ogg":  "audio/ogg",
            "oga":  "audio/ogg",
            "mp3":  "audio/mpeg",
            "m4a":  "audio/mp4",
            "jpg":  "image/jpeg",
            "jpeg": "image/jpeg",
            "png":  "image/png",
            "gif":  "image/gif",
            "webp": "image/webp",
            "mp4":  "video/mp4",
            "pdf":  "application/pdf",
        }.get(ext, "application/octet-stream")
