"""WhatsApp Cloud API adapter.

Implements the CommunicationAdapter interface using the Meta WhatsApp
Cloud API (Graph API v20.0). All API calls use httpx (already a
project dependency) — no new packages required.

Configuration is via environment variables:
  WHATSAPP_ACCESS_TOKEN    — Meta permanent access token
  WHATSAPP_PHONE_NUMBER_ID — WhatsApp Business phone number ID

API reference: https://developers.facebook.com/docs/whatsapp/cloud-api
"""

from __future__ import annotations

import logging

import httpx

from jatayu.comms.adapter import CommunicationAdapter

logger = logging.getLogger(__name__)

_API_BASE = "https://graph.facebook.com/v20.0"


class WhatsAppAdapter(CommunicationAdapter):
    """WhatsApp Cloud API implementation of CommunicationAdapter.

    Handles sending/receiving text, media, typing indicators, and
    read receipts through the Meta WhatsApp Cloud API.

    Args:
        access_token:    Meta permanent access token.
        phone_number_id: WhatsApp Business phone number ID.
    """

    def __init__(
        self,
        access_token: str,
        phone_number_id: str,
    ) -> None:
        self._token = access_token
        self._phone_id = phone_number_id
        self._messages_url = f"{_API_BASE}/{self._phone_id}/messages"
        self._media_url_base = f"{_API_BASE}"
        logger.info("WhatsApp adapter initialized (phone_id: %s)", phone_number_id)

    @property
    def provider_name(self) -> str:
        return "whatsapp"

    def _headers(self) -> dict[str, str]:
        """Standard authorization headers for Meta API."""
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    # ── Sending ──

    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
    ) -> dict:
        """Send a text message to a WhatsApp chat.

        Args:
            chat_id:     Recipient phone number (e.g. "919876543210").
            text:        Message text (max 4096 chars per WhatsApp limit).
            reply_to_id: Optional message ID to quote-reply.
        """
        payload: dict = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": chat_id,
            "type": "text",
            "text": {"body": text},
        }

        if reply_to_id:
            payload["context"] = {"message_id": reply_to_id}

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._messages_url,
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                msg_id = (
                    data.get("messages", [{}])[0].get("id", "unknown")
                    if data.get("messages")
                    else "unknown"
                )
                logger.info("WhatsApp text sent to %s (msg_id: %s)", chat_id, msg_id)
                return {"status": "sent", "message_id": msg_id}
        except httpx.HTTPStatusError as e:
            logger.error(
                "WhatsApp send_text HTTP %s: %s",
                e.response.status_code,
                e.response.text[:300],
            )
            return {"status": "error", "error": str(e)}
        except Exception as e:
            logger.error("WhatsApp send_text failed: %s", e)
            return {"status": "error", "error": str(e)}

    async def send_media(
        self,
        chat_id: str,
        media_bytes: bytes,
        media_type: str,
        filename: str | None = None,
        caption: str | None = None,
    ) -> dict:
        """Send a media message (image, audio, document, video).

        First uploads the media to WhatsApp servers, then sends a
        message referencing the uploaded media ID.
        """
        # Map media types to WhatsApp API types and MIME defaults
        type_config = {
            "image": {"wa_type": "image", "mime": "image/jpeg"},
            "audio": {"wa_type": "audio", "mime": "audio/mpeg"},
            "document": {"wa_type": "document", "mime": "application/pdf"},
            "video": {"wa_type": "video", "mime": "video/mp4"},
        }

        config = type_config.get(media_type, type_config["document"])
        wa_type = config["wa_type"]
        mime = config["mime"]

        try:
            # Step 1: Upload media
            upload_url = f"{_API_BASE}/{self._phone_id}/media"
            async with httpx.AsyncClient(timeout=60.0) as client:
                upload_resp = await client.post(
                    upload_url,
                    headers={"Authorization": f"Bearer {self._token}"},
                    data={"messaging_product": "whatsapp", "type": mime},
                    files={"file": (filename or "file", media_bytes, mime)},
                )
                upload_resp.raise_for_status()
                media_id = upload_resp.json().get("id")

            if not media_id:
                return {"status": "error", "error": "Media upload returned no ID"}

            # Step 2: Send media message
            payload: dict = {
                "messaging_product": "whatsapp",
                "to": chat_id,
                "type": wa_type,
                wa_type: {"id": media_id},
            }
            if caption and wa_type in ("image", "document", "video"):
                payload[wa_type]["caption"] = caption
            if filename and wa_type == "document":
                payload[wa_type]["filename"] = filename

            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    self._messages_url,
                    headers=self._headers(),
                    json=payload,
                )
                resp.raise_for_status()
                logger.info("WhatsApp media (%s) sent to %s", wa_type, chat_id)
                return {"status": "sent", "media_id": media_id}
        except Exception as e:
            logger.error("WhatsApp send_media failed: %s", e)
            return {"status": "error", "error": str(e)}

    # ── Status ──

    async def send_typing_indicator(self, chat_id: str) -> None:
        """Show 'typing...' indicator in the WhatsApp chat."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "typing",
            "to": chat_id,
        }
        try:
            # WhatsApp doesn't have an official typing endpoint via Cloud API,
            # but some implementations use the messages endpoint with a reaction.
            # For now, this is a no-op placeholder that logs the intent.
            logger.debug("Typing indicator for %s (WhatsApp Cloud API has limited support)", chat_id)
        except Exception:
            pass

    async def mark_as_read(self, message_id: str) -> None:
        """Mark a message as read (blue ticks)."""
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                await client.post(
                    self._messages_url,
                    headers=self._headers(),
                    json=payload,
                )
                logger.debug("Marked as read: %s", message_id)
        except Exception as e:
            logger.debug("Mark-as-read failed (non-critical): %s", e)

    # ── Media download ──

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media content from WhatsApp servers.

        WhatsApp media download is a two-step process:
          1. GET /media/{media_id} → returns the media URL
          2. GET {media_url}       → returns the actual bytes

        Returns:
            Tuple of (raw_bytes, mime_type).
        """
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                # Step 1: Get the media URL
                meta_resp = await client.get(
                    f"{self._media_url_base}/{media_id}",
                    headers=self._headers(),
                )
                meta_resp.raise_for_status()
                meta_data = meta_resp.json()
                media_url = meta_data.get("url")
                mime_type = meta_data.get("mime_type", "application/octet-stream")

                if not media_url:
                    raise ValueError(f"No URL returned for media {media_id}")

                # Step 2: Download the actual bytes
                dl_resp = await client.get(
                    media_url,
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                dl_resp.raise_for_status()

                logger.info(
                    "Downloaded WhatsApp media %s (%s, %d bytes)",
                    media_id,
                    mime_type,
                    len(dl_resp.content),
                )
                return dl_resp.content, mime_type

        except Exception as e:
            logger.error("WhatsApp media download failed: %s", e)
            raise
