"""Abstract CommunicationAdapter interface + ProviderCapabilities.

Every messaging provider (WhatsApp, Telegram, Slack, Discord, etc.)
must implement this interface. The Communication Router and Provider
Registry interact ONLY through this abstraction — never through
provider-specific code.

To add a new provider:
  1. Create a new subpackage under jatayu/comms/ (e.g. jatayu/comms/telegram/)
  2. Implement CommunicationAdapter in that subpackage
  3. Register it with the ProviderRegistry on startup
  4. Done — zero changes to Brain, Router, or Dispatcher

ProviderCapabilities:
  Each adapter declares what it supports. The Router (and future model
  routing logic) can query capabilities instead of checking provider names.
  Example: "can this provider send voice?" — ask the capabilities, never
  branch on adapter type.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderCapabilities:
    """Declares the feature set of a communication provider.

    The Communication Router queries these flags to decide how to
    format and deliver responses. No provider-name checks anywhere.

    Example usage in the router:
        if adapter.capabilities.supports_voice:
            await adapter.send_media(chat_id, audio, "audio")
        else:
            await adapter.send_text(chat_id, transcript)
    """
    # ── Sending capabilities ──
    supports_text: bool = True
    supports_images: bool = False
    supports_documents: bool = False
    supports_audio: bool = False
    supports_video: bool = False
    supports_location: bool = False

    # ── UI capabilities ──
    supports_typing_indicator: bool = False
    supports_read_receipts: bool = False
    supports_message_threads: bool = False   # reply-to a specific message

    # ── Formatting capabilities ──
    supports_markdown: bool = False          # bold, italic, code blocks
    supports_html: bool = False              # HTML tags in messages
    max_message_length: int = 4096          # max chars per outgoing message

    # ── Channel capabilities ──
    supports_groups: bool = False
    supports_group_mention_trigger: bool = False

    # ── Voice conversation ──
    supports_voice_input: bool = False       # can receive voice notes
    supports_voice_output: bool = False      # can send voice notes back


class CommunicationAdapter(ABC):
    """Abstract interface every communication provider must implement.

    Implementations handle the platform-specific details of sending
    and receiving messages, media, and status updates. The rest of the
    system interacts with providers exclusively through this interface.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique identifier for this provider (e.g. 'whatsapp', 'telegram').

        Must be lowercase, no spaces. Used as the key in ProviderRegistry
        and matched against IncomingMessage.source.
        """
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Declare what this provider supports.

        The Router and Dispatcher query capabilities to make decisions.
        Never check adapter.provider_name to determine behavior.
        """
        ...

    # ── Sending ──

    @abstractmethod
    async def send_text(
        self,
        chat_id: str,
        text: str,
        reply_to_id: str | None = None,
    ) -> dict:
        """Send a text message to a chat.

        Args:
            chat_id:     Target conversation/chat/group.
            text:        Message text content.
            reply_to_id: Optional message ID to reply to (threading).

        Returns:
            Provider-specific result dict (at minimum {"status": "sent"}).
        """
        ...

    @abstractmethod
    async def send_media(
        self,
        chat_id: str,
        media_bytes: bytes,
        media_type: str,
        filename: str | None = None,
        caption: str | None = None,
    ) -> dict:
        """Send a media message (image, audio, document, video).

        Args:
            chat_id:     Target conversation/chat/group.
            media_bytes: Raw file bytes to upload and send.
            media_type:  Category — "image", "audio", "document", "video".
            filename:    Suggested filename for the recipient.
            caption:     Optional caption text displayed with the media.

        Returns:
            Provider-specific result dict.
        """
        ...

    # ── Status ──

    @abstractmethod
    async def send_typing_indicator(self, chat_id: str) -> None:
        """Show a typing / composing indicator in the chat.

        This is a best-effort signal — implementations should not raise
        on failure (some platforms don't support it).
        """
        ...

    @abstractmethod
    async def mark_as_read(self, message_id: str) -> None:
        """Mark a received message as read / seen.

        Best-effort — implementations should not raise on failure.
        """
        ...

    # ── Media ──

    @abstractmethod
    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Download media content by its platform-specific ID.

        Args:
            media_id: Platform-specific identifier for the media object.

        Returns:
            Tuple of (raw_bytes, mime_type).
        """
        ...
