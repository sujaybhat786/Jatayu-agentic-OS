"""Telegram Update parser.

Converts raw Telegram Update dicts into normalized IncomingMessage
and Attachment objects. Supports text, commands, voice, photo, document,
audio, video, and location.

Command handling:
  Telegram /commands are detected and normalized with content_type="command"
  so the Router can route or acknowledge them independently without the
  Brain treating them as ordinary text.

No provider logic lives here — only normalization.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from jatayu.comms.models import Attachment, IncomingMessage

logger = logging.getLogger(__name__)


def parse_telegram_update(update: dict) -> IncomingMessage | None:
    """Parse one Telegram Update into a normalized IncomingMessage.

    Telegram Update structure:
      {
        "update_id": 123,
        "message": {
          "message_id": 456,
          "from": {"id": 789, "first_name": "...", "username": "..."},
          "chat": {"id": 789, "type": "private"|"group"|"supergroup"},
          "date": 1234567890,
          "text": "...",          # or voice/photo/document/etc.
          ...
        }
      }

    Returns None for unsupported update types (edited messages, polls, etc.)
    """
    # Only handle regular messages for now
    message = update.get("message") or update.get("channel_post")
    if not message:
        logger.debug("Skipping non-message update: %s", list(update.keys()))
        return None

    # ── Core fields ──
    message_id = str(message.get("message_id", ""))
    raw_ts = message.get("date", 0)
    try:
        ts = datetime.fromtimestamp(raw_ts, tz=timezone.utc).isoformat()
    except (ValueError, TypeError):
        ts = datetime.now(timezone.utc).isoformat()

    # ── Sender ──
    sender = message.get("from") or {}
    sender_id = str(sender.get("id", ""))
    first = sender.get("first_name", "")
    last = sender.get("last_name", "")
    username = sender.get("username", "")
    sender_name = f"{first} {last}".strip() or username or sender_id

    # ── Chat ──
    chat = message.get("chat", {})
    chat_id = str(chat.get("id", ""))
    chat_type = chat.get("type", "private")
    channel_type = "private" if chat_type == "private" else "group"

    # ── Reply-to ──
    reply_to = message.get("reply_to_message", {})
    reply_to_id = str(reply_to.get("message_id", "")) if reply_to else None

    # ── Content ──
    text = ""
    attachments: list[Attachment] = []
    msg_type = "text"

    if "text" in message:
        raw_text = message["text"]
        # Detect Telegram bot commands (/note, /remind, /task, /status, /help)
        if raw_text.startswith("/"):
            msg_type = "command"
            text = raw_text
        else:
            text = raw_text

    elif "voice" in message:
        voice = message["voice"]
        msg_type = "voice"
        attachments.append(Attachment(
            type="voice",
            mime=voice.get("mime_type", "audio/ogg"),
            media_id=voice.get("file_id"),
            metadata={"duration": voice.get("duration", 0)},
            source_metadata={
                "file_id": voice.get("file_id"),
                "file_unique_id": voice.get("file_unique_id"),
                "file_size": voice.get("file_size"),
            },
        ))

    elif "audio" in message:
        audio = message["audio"]
        msg_type = "audio"
        text = message.get("caption", "")
        attachments.append(Attachment(
            type="voice",   # normalized as voice for STT pipeline
            mime=audio.get("mime_type", "audio/mpeg"),
            filename=audio.get("file_name"),
            media_id=audio.get("file_id"),
            metadata={"duration": audio.get("duration", 0),
                      "performer": audio.get("performer", ""),
                      "title": audio.get("title", "")},
            source_metadata={
                "file_id": audio.get("file_id"),
                "file_unique_id": audio.get("file_unique_id"),
            },
        ))

    elif "photo" in message:
        # Telegram sends multiple resolutions — take the largest
        photos = message["photo"]
        best = max(photos, key=lambda p: p.get("file_size", 0))
        msg_type = "photo"
        text = message.get("caption", "")
        attachments.append(Attachment(
            type="image",
            mime="image/jpeg",
            media_id=best.get("file_id"),
            metadata={"width": best.get("width"), "height": best.get("height")},
            source_metadata={
                "file_id": best.get("file_id"),
                "file_unique_id": best.get("file_unique_id"),
                "all_sizes": [p.get("file_id") for p in photos],
            },
        ))

    elif "document" in message:
        doc = message["document"]
        msg_type = "document"
        text = message.get("caption", "")
        attachments.append(Attachment(
            type="document",
            mime=doc.get("mime_type", "application/octet-stream"),
            filename=doc.get("file_name"),
            media_id=doc.get("file_id"),
            source_metadata={
                "file_id": doc.get("file_id"),
                "file_unique_id": doc.get("file_unique_id"),
                "file_size": doc.get("file_size"),
            },
        ))

    elif "video" in message:
        video = message["video"]
        msg_type = "video"
        text = message.get("caption", "")
        attachments.append(Attachment(
            type="video",
            mime=video.get("mime_type", "video/mp4"),
            filename=video.get("file_name"),
            media_id=video.get("file_id"),
            metadata={"duration": video.get("duration", 0),
                      "width": video.get("width"),
                      "height": video.get("height")},
            source_metadata={
                "file_id": video.get("file_id"),
                "file_unique_id": video.get("file_unique_id"),
            },
        ))

    elif "video_note" in message:
        vnote = message["video_note"]
        msg_type = "video_note"
        attachments.append(Attachment(
            type="video",
            mime="video/mp4",
            media_id=vnote.get("file_id"),
            metadata={"duration": vnote.get("duration", 0)},
            source_metadata={"file_id": vnote.get("file_id"),
                             "file_unique_id": vnote.get("file_unique_id")},
        ))

    elif "location" in message:
        loc = message["location"]
        msg_type = "location"
        attachments.append(Attachment(
            type="location",
            metadata={
                "lat": loc.get("latitude"),
                "lon": loc.get("longitude"),
                "accuracy": loc.get("horizontal_accuracy"),
            },
        ))

    elif "contact" in message:
        contact = message["contact"]
        msg_type = "contact"
        attachments.append(Attachment(
            type="contact",
            metadata={
                "name": f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
                "phone": contact.get("phone_number", ""),
            },
        ))

    elif "sticker" in message:
        # Sticker support deferred — log and skip
        logger.debug("Sticker received from %s — skipped (Phase 2)", sender_id)
        return None

    else:
        logger.debug("Unhandled Telegram message type from %s: %s", sender_id, list(message.keys()))
        return None

    # Log all incoming messages for easy debugging
    logger.info(
        "Telegram [%s] from %s (%s) in %s chat %s: %s",
        msg_type,
        sender_name,
        sender_id,
        channel_type,
        chat_id,
        (text[:60] + "...") if len(text) > 60 else (text or "[media]"),
    )

    return IncomingMessage(
        source="telegram",
        sender_id=sender_id,
        sender_name=sender_name,
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        timestamp=ts,
        channel_type=channel_type,
        attachments=attachments,
        reply_to_id=reply_to_id,
        metadata={"telegram_type": msg_type, "update_id": str(update.get("update_id", ""))},
    )
