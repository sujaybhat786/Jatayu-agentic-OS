"""Session Manager — conversation continuity across all platforms.

Manages lightweight conversation sessions so the Brain can maintain
context across multiple messages from the same chat, regardless of
which platform they originate from.

Today: Simple in-memory session tracking with TTL-based expiry.
Tomorrow: Persistent storage, memory retrieval, context injection,
user preferences, and cross-platform session linking.

Sessions are keyed by "{source}:{chat_id}" — so WhatsApp chat 1234
and Telegram chat 1234 are distinct sessions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.comms.models import IncomingMessage

logger = logging.getLogger(__name__)


@dataclass
class Session:
    """Represents one ongoing conversation across any platform.

    Attributes:
        session_id:    Unique key — "{source}:{chat_id}".
        source:        Provider name (e.g. "whatsapp").
        chat_id:       Platform chat/conversation ID.
        sender_id:     Last sender's platform user ID.
        sender_name:   Last sender's display name.
        created_at:    ISO-8601 creation timestamp.
        last_active:   ISO-8601 last activity timestamp.
        message_count: Total messages processed in this session.
        context:       Extensible dict for future use:
                         - conversation history summary
                         - user preferences
                         - memory references
                         - active task state
    """
    session_id: str
    source: str
    chat_id: str
    sender_id: str
    sender_name: str
    created_at: str
    last_active: str
    message_count: int = 0
    context: dict = field(default_factory=dict)


class SessionManager:
    """Manages conversation sessions across all providers.

    Thread-safe for single-process async usage (FastAPI/uvicorn).
    Sessions expire after SESSION_TTL_HOURS of inactivity.

    Usage:
        mgr = SessionManager()
        session = mgr.get_or_create(incoming_message)
        session.message_count += 1
        mgr.update(session)
    """

    SESSION_TTL_HOURS: int = 24

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}

    @staticmethod
    def _make_key(source: str, chat_id: str) -> str:
        """Build the canonical session key."""
        return f"{source}:{chat_id}"

    def get_or_create(self, message: IncomingMessage) -> Session:
        """Retrieve an existing session or create a new one.

        If the session exists but has expired (past TTL), it is replaced
        with a fresh session.

        Args:
            message: The normalized incoming message.

        Returns:
            An active Session for this conversation.
        """
        key = self._make_key(message.source, message.chat_id)
        now = datetime.now(timezone.utc).isoformat()

        existing = self._sessions.get(key)
        if existing:
            # Check TTL
            try:
                last = datetime.fromisoformat(existing.last_active)
                if datetime.now(timezone.utc) - last > timedelta(hours=self.SESSION_TTL_HOURS):
                    logger.info("Session expired, creating new: %s", key)
                    existing = None
            except (ValueError, TypeError):
                existing = None

        if existing:
            # Update with latest sender info and activity time
            existing.sender_id = message.sender_id
            existing.sender_name = message.sender_name
            existing.last_active = now
            return existing

        # Create new session
        session = Session(
            session_id=key,
            source=message.source,
            chat_id=message.chat_id,
            sender_id=message.sender_id,
            sender_name=message.sender_name,
            created_at=now,
            last_active=now,
        )
        self._sessions[key] = session
        self.cleanup_expired()
        logger.info("New session created: %s (sender: %s)", key, message.sender_name)
        return session

    def update(self, session: Session) -> None:
        """Persist session state after processing a message."""
        session.last_active = datetime.now(timezone.utc).isoformat()
        self._sessions[session.session_id] = session

    def get(self, source: str, chat_id: str) -> Session | None:
        """Look up a session without creating one."""
        return self._sessions.get(self._make_key(source, chat_id))

    def cleanup_expired(self) -> int:
        """Remove all expired sessions. Returns count of removed sessions."""
        now = datetime.now(timezone.utc)
        cutoff = timedelta(hours=self.SESSION_TTL_HOURS)
        expired_keys = []

        for key, session in self._sessions.items():
            try:
                last = datetime.fromisoformat(session.last_active)
                if now - last > cutoff:
                    expired_keys.append(key)
            except (ValueError, TypeError):
                expired_keys.append(key)

        for key in expired_keys:
            del self._sessions[key]

        if expired_keys:
            logger.info("Cleaned up %d expired sessions", len(expired_keys))
        return len(expired_keys)

    @property
    def active_count(self) -> int:
        """Number of active sessions."""
        return len(self._sessions)
