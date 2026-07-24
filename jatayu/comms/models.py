"""Normalized message models for the Communication Layer.

Every messaging provider (WhatsApp, Telegram, Slack, etc.) normalizes
its platform-specific payload into these generic dataclasses before
handing off to the CommunicationRouter.

Key design decisions:
  - All media (images, voice, documents, video, contacts, locations)
    are represented as generic Attachment objects.
  - IncomingMessage never contains provider-specific fields.
  - The Brain and RequestDispatcher never see platform details.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Attachment:
    """Generic attachment — images, voice, documents, video all use this.

    Every media type is normalized into one structure so the Communication
    Router, Request Dispatcher, and Brain never deal with type-specific
    fields scattered across the message.

    Attributes:
        type:            Category — "image", "voice", "document", "video",
                         "contact", "location".
        mime:            MIME type if known (e.g. "audio/ogg", "image/jpeg").
        filename:        Original filename if the platform provides one.
        data:            Raw bytes (populated after download; None before).
        media_id:        Platform-specific media ID for lazy downloading.
        media_url:       Direct URL if the platform provides one.
        metadata:        Type-specific extras. Examples:
                           location → {"lat": 12.97, "lon": 77.59, "name": "..."}
                           contact  → {"name": "Ram", "phone": "+91..."}
                           document → {"page_count": 5}
        source_metadata: Provider-specific raw metadata preserved for later use.
                         Never used by the Brain or Router — stored for
                         provider-level operations (e.g. Telegram file IDs
                         for re-sending, WhatsApp media IDs for expiry checks).
                         Example (Telegram): {"file_id": "...", "file_unique_id": "..."}
                         Example (WhatsApp): {"sha256": "...", "voice": True}
    """
    type: str
    mime: str | None = None
    filename: str | None = None
    data: bytes | None = None
    media_id: str | None = None
    media_url: str | None = None
    metadata: dict = field(default_factory=dict)
    source_metadata: dict = field(default_factory=dict)


@dataclass
class IncomingMessage:
    """Provider-agnostic normalized message from any platform.

    The Communication Router receives one of these for every inbound
    message, regardless of whether it came from WhatsApp, Telegram,
    Slack, or any future provider.

    Attributes:
        source:       Provider name — "whatsapp", "telegram", "slack", etc.
        sender_id:    Platform-specific user identifier (e.g. phone number).
        sender_name:  Display name of the sender (if available).
        chat_id:      Conversation / chat / group identifier.
        message_id:   Platform-specific message ID (used for reply-to).
        text:         Text content. For voice messages, this is populated
                      after STT transcription.
        timestamp:    ISO-8601 string.
        channel_type: "private" or "group".
        attachments:  List of Attachment objects (images, voice, docs, etc.).
        reply_to_id:  Message ID this message is replying to (if any).
        metadata:     Provider-specific extras that don't fit elsewhere.
    """
    source: str
    sender_id: str
    sender_name: str
    chat_id: str
    message_id: str
    text: str
    timestamp: str
    channel_type: str = "private"
    attachments: list[Attachment] = field(default_factory=list)
    reply_to_id: str | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class OutgoingMessage:
    """Normalized response to send back through any provider.

    The Communication Router builds one of these and passes it to
    the originating adapter's send methods.

    Attributes:
        chat_id:      Target conversation / chat / group.
        text:         Response text content.
        reply_to_id:  Message ID to reply to (threading).
        attachments:  Media to send back (images, documents, audio).
        metadata:     Provider-specific extras for the outbound message.
    """
    chat_id: str
    text: str
    reply_to_id: str | None = None
    attachments: list[Attachment] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
