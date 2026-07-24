"""Communication Router — stateless orchestrator for messaging traffic.

This is a pure orchestrator. Its ONLY responsibilities are:
  1. Validate sender authorization
  2. Resolve/create session
  3. Handle media (download attachments, transcribe voice)
  4. Check group trigger rules
  5. Forward to RequestDispatcher
  6. Return response via originating adapter

It contains NO business logic, NO Brain references, NO tool execution,
NO model selection, and NO memory management. Those belong in the
RequestDispatcher and Brain.

Voice interactions are INDEPENDENT of this layer and never flow through
here. This router handles only messaging platform traffic.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.comms.adapter import CommunicationAdapter
    from jatayu.voice.voice_manager import VoiceManager

from jatayu.comms.models import IncomingMessage
from jatayu.comms.dispatcher import RequestDispatcher
from jatayu.comms.registry import ProviderRegistry
from jatayu.comms.session import SessionManager

logger = logging.getLogger(__name__)

# WhatsApp has a 4096-character message limit
_MAX_MESSAGE_LENGTH = 4000


class CommunicationRouter:
    """Stateless orchestrator for all messaging platform traffic.

    Receives normalized IncomingMessage objects from webhook handlers,
    orchestrates the processing pipeline, and sends responses back
    through the originating adapter.

    This class is intentionally stateless regarding business logic.
    All intelligence lives in the RequestDispatcher and Brain.

    Args:
        dispatcher:       RequestDispatcher instance (Brain abstraction).
        registry:         ProviderRegistry with registered adapters.
        session_manager:  SessionManager for conversation continuity.
        voice_manager:    VoiceManager for transcribing voice attachments.
        authorized_users: Per-provider allowlists.
                          Example: {"whatsapp": ["+91..."]}
                          Empty list = allow everyone.
    """

    def __init__(
        self,
        dispatcher: RequestDispatcher,
        registry: ProviderRegistry,
        session_manager: SessionManager,
        voice_manager: VoiceManager,
        authorized_users: dict[str, list[str]] | None = None,
    ) -> None:
        self._dispatcher = dispatcher
        self._registry = registry
        self._sessions = session_manager
        self._voice = voice_manager
        self._authorized = authorized_users or {}

    # ── Public entry point ──

    async def handle_incoming(self, message: IncomingMessage) -> None:
        """Universal message handler — stateless orchestration only.

        Called by webhook handlers after they normalize the platform
        payload into an IncomingMessage.

        Processing pipeline:
          1. Authorize sender
          2. Get originating adapter
          3. Mark as read + typing indicator
          4. Download and transcribe voice attachments
          5. Check group trigger rules
          6. Resolve session
          7. Forward to RequestDispatcher
          8. Send response back through adapter
        """
        # 1. Authorize sender
        if not self._is_authorized(message):
            logger.warning(
                "Unauthorized message from %s on %s — ignoring",
                message.sender_id,
                message.source,
            )
            return

        # 2. Get the adapter for this provider
        adapter = self._registry.get(message.source)
        if not adapter:
            logger.error(
                "No adapter registered for provider '%s'", message.source
            )
            return

        # 3. Mark as read + show typing (best-effort, don't fail on errors)
        await self._safe_status(adapter, message)

        # 4. Handle voice attachments → transcribe to text
        await self._process_voice_attachments(message, adapter)

        # 5. If still no text after voice processing, acknowledge receipt
        if not message.text or not message.text.strip():
            has_media = bool(message.attachments)
            if has_media:
                ack = "📎 I received your file. Processing support for this media type is coming soon."
            else:
                ack = "I received an empty message."
            await self._safe_send(adapter, message.chat_id, ack, message.message_id)
            return

        # 6. Group trigger check — only respond when addressed
        if message.channel_type == "group":
            if not self._is_triggered(message):
                return  # Not addressed to Jatayu — stay silent

        # 7. Resolve or create session
        session = self._sessions.get_or_create(message)

        # 8. Dispatch to Brain via RequestDispatcher
        try:
            response = await self._dispatcher.dispatch(message, session)
        except Exception as e:
            logger.error("Dispatch failed for %s: %s", message.message_id, e)
            response = f"⚠️ I encountered an error: {e}"

        # 9. Update session
        session.message_count += 1
        self._sessions.update(session)

        # 10. Send response back (split if needed for platform limits)
        await self._send_response(adapter, message.chat_id, response, message.message_id)

    # ── Authorization ──

    def _is_authorized(self, msg: IncomingMessage) -> bool:
        """Check if the sender is in the provider's allowlist.

        If no allowlist is configured for the provider, everyone is allowed.
        """
        allowed = self._authorized.get(msg.source, [])
        if not allowed:
            return True  # No allowlist = open
        return msg.sender_id in allowed

    # ── Group trigger ──

    def _is_triggered(self, msg: IncomingMessage) -> bool:
        """Check if Jatayu is being addressed in a group message.

        Uses mention-only mode: only respond when the message contains
        a trigger phrase. This prevents noise in active groups.
        """
        text = msg.text.lower()
        triggers = ["jatayu", "@jatayu", "hey jatayu", "hi jatayu"]
        return any(t in text for t in triggers)

    # ── Voice processing ──

    async def _process_voice_attachments(
        self,
        message: IncomingMessage,
        adapter: CommunicationAdapter,
    ) -> None:
        """Download and transcribe voice attachments.

        If the message has no text and contains a voice attachment,
        download the audio and run it through the STT pipeline.
        The transcribed text is written into message.text.
        """
        if message.text and message.text.strip():
            return  # Already has text, no need to transcribe

        voice_attachments = [a for a in message.attachments if a.type == "voice"]
        if not voice_attachments:
            return

        att = voice_attachments[0]  # Process the first voice attachment

        try:
            # Download audio bytes if not already present
            if not att.data and att.media_id:
                att.data, att.mime = await adapter.download_media(att.media_id)

            if att.data:
                # Run STT in a thread (VoiceManager.transcribe is synchronous)
                loop = asyncio.get_event_loop()
                transcript = await loop.run_in_executor(
                    None,
                    lambda: self._voice.transcribe(
                        att.data, att.mime or "audio/ogg"
                    ),
                )
                if transcript:
                    message.text = transcript
                    logger.info(
                        "Voice transcribed from %s: %.80s...",
                        message.source,
                        transcript,
                    )
        except Exception as e:
            logger.error("Voice transcription failed: %s", e)

    # ── Response sending ──

    async def _send_response(
        self,
        adapter: CommunicationAdapter,
        chat_id: str,
        text: str,
        reply_to_id: str | None,
    ) -> None:
        """Send a response, splitting into chunks if needed."""
        if not text:
            return

        if len(text) <= _MAX_MESSAGE_LENGTH:
            await self._safe_send(adapter, chat_id, text, reply_to_id)
        else:
            # Split at newline boundaries when possible
            chunks = self._split_text(text, _MAX_MESSAGE_LENGTH)
            for chunk in chunks:
                await self._safe_send(adapter, chat_id, chunk, reply_to_id)

    @staticmethod
    def _split_text(text: str, max_len: int) -> list[str]:
        """Split text into chunks, preferring newline boundaries."""
        chunks = []
        while text:
            if len(text) <= max_len:
                chunks.append(text)
                break
            # Try to split at a newline near the limit
            split_pos = text.rfind("\n", 0, max_len)
            if split_pos < max_len // 2:
                # No good newline break — split at space
                split_pos = text.rfind(" ", 0, max_len)
            if split_pos < max_len // 2:
                # No good split point — hard split
                split_pos = max_len
            chunks.append(text[:split_pos])
            text = text[split_pos:].lstrip("\n")
        return chunks

    # ── Safe helpers (never raise) ──

    @staticmethod
    async def _safe_status(
        adapter: CommunicationAdapter,
        message: IncomingMessage,
    ) -> None:
        """Mark as read and send typing indicator — best effort."""
        try:
            await adapter.mark_as_read(message.message_id)
        except Exception:
            pass
        try:
            await adapter.send_typing_indicator(message.chat_id)
        except Exception:
            pass

    @staticmethod
    async def _safe_send(
        adapter: CommunicationAdapter,
        chat_id: str,
        text: str,
        reply_to_id: str | None,
    ) -> None:
        """Send text — log errors but never raise."""
        try:
            await adapter.send_text(chat_id, text, reply_to_id)
        except Exception as e:
            logger.error("Failed to send response: %s", e)
