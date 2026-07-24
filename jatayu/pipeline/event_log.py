"""Event Log — persistent, append-only record of all JATAYU pipeline events.

Every service emits events here. Dashboard, Battle Ground, and analytics
subscribe to the same stream instead of polling individual services.

Design rules (from Brain Contract v1):
- Append-only: entries are never modified or deleted.
- Sync: emit() is synchronous and never raises.
- No imports from pipeline services (prevents circular deps).
- Storage: data/event_log.jsonl (one JSON object per line).
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any
import uuid

logger = logging.getLogger(__name__)

# ── Event taxonomy ─────────────────────────────────────────────────────────────
EVENT_TYPES = frozenset([
    # Memory
    "entity.created", "entity.updated", "entity.deleted",
    "fact.stored", "fact.updated", "fact.forgotten",
    "relationship.created",
    # Pipeline
    "intent.classified", "task.extracted", "plan.generated",
    "agent.selected", "model.selected",
    "tool.called", "tool.succeeded", "tool.failed",
    "response.generated",
    # Workspace
    "workspace.created", "workspace.updated", "workspace.expired",
    "project.activated", "agent.switched",
    # External
    "email.sent", "email.received", "calendar.event.created",
    "reminder.added", "reminder.triggered",
    "task.completed", "meeting.started",
    # System
    "model.switched", "provider.fallback", "kill_switch.triggered",
    "confirmation.requested", "confirmation.approved", "confirmation.denied",
    # Legacy (from existing EventBus)
    "ConversationCreated", "MessageCreated", "ConversationDeleted",
    "startup", "injection_detected",
])


@dataclass
class PipelineEvent:
    """A single event record in the JATAYU event log."""
    event_id: str
    type: str
    session_id: str
    source: str          # which service emitted it
    timestamp: str
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> PipelineEvent:
        return cls(**d)


# Type alias
EventCallback = Callable[[PipelineEvent], None]


class EventLog:
    """Persistent, append-only event log.

    Thread-safe. emit() never raises — errors are logged and swallowed.
    Subscribers are notified synchronously after each emit.

    Args:
        data_dir: Directory containing event_log.jsonl.
                  Created automatically if it does not exist.
        max_memory: Maximum number of recent events to keep in memory
                    for fast in-process queries. Older events are only
                    in the JSONL file.
    """

    def __init__(self, data_dir: str, max_memory: int = 2000) -> None:
        self._path = Path(data_dir) / "event_log.jsonl"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._max_memory = max_memory
        self._lock = threading.Lock()
        self._subscribers: dict[str, list[EventCallback]] = defaultdict(list)
        self._wildcard_subscribers: list[EventCallback] = []
        self._recent: list[PipelineEvent] = []

        # Load last N events into memory for fast queries
        self._load_recent()

    # ── Emit ──────────────────────────────────────────────────────────────────

    def emit(
        self,
        type: str,
        data: dict | None = None,
        source: str = "unknown",
        session_id: str = "",
    ) -> PipelineEvent:
        """Record an event and notify subscribers.

        Never raises. Errors are logged but not propagated so a logging
        failure never crashes the main pipeline.

        Args:
            type:       Event type string (see EVENT_TYPES).
            data:       Arbitrary payload dict.
            source:     Name of the emitting service.
            session_id: Active session, if known.

        Returns:
            The created PipelineEvent record.
        """
        event = PipelineEvent(
            event_id=uuid.uuid4().hex[:12],
            type=type,
            session_id=session_id,
            source=source,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data=data or {},
        )

        # Persist
        try:
            with self._lock:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), default=str) + "\n")
                # Update in-memory buffer
                self._recent.append(event)
                if len(self._recent) > self._max_memory:
                    self._recent = self._recent[-self._max_memory:]
        except Exception as exc:
            logger.error("EventLog: failed to persist event %s: %s", type, exc)

        # Notify subscribers (best-effort, never crash on callback errors)
        self._notify(event)

        return event

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, event_type: str, callback: EventCallback) -> None:
        """Subscribe to a specific event type or '*' for all events."""
        if event_type == "*":
            self._wildcard_subscribers.append(callback)
        else:
            self._subscribers[event_type].append(callback)

    def unsubscribe(self, event_type: str, callback: EventCallback) -> None:
        """Remove a subscription."""
        if event_type == "*":
            self._wildcard_subscribers = [
                c for c in self._wildcard_subscribers if c is not callback
            ]
        else:
            self._subscribers[event_type] = [
                c for c in self._subscribers[event_type] if c is not callback
            ]

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_recent(
        self,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[PipelineEvent]:
        """Return the most recent events, optionally filtered by session."""
        events = self._recent
        if session_id:
            events = [e for e in events if e.session_id == session_id]
        return events[-limit:]

    def get_by_type(
        self,
        event_type: str,
        limit: int = 100,
    ) -> list[PipelineEvent]:
        """Return the most recent events of a specific type."""
        return [e for e in self._recent if e.type == event_type][-limit:]

    def to_api_list(self, session_id: str | None = None, limit: int = 50) -> list[dict]:
        """Serialize recent events for the REST API."""
        return [e.to_dict() for e in self.get_recent(session_id, limit)]

    # ── Internal ──────────────────────────────────────────────────────────────

    def _notify(self, event: PipelineEvent) -> None:
        for callback in self._subscribers.get(event.type, []):
            try:
                callback(event)
            except Exception as exc:
                logger.error("EventLog subscriber error (%s): %s", event.type, exc)
        for callback in self._wildcard_subscribers:
            try:
                callback(event)
            except Exception as exc:
                logger.error("EventLog wildcard subscriber error: %s", exc)

    def _load_recent(self) -> None:
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").strip().splitlines()
            tail = lines[-self._max_memory:]
            for line in tail:
                try:
                    self._recent.append(PipelineEvent.from_dict(json.loads(line)))
                except Exception:
                    pass  # Corrupt line — skip silently
        except Exception as exc:
            logger.warning("EventLog: could not load recent events: %s", exc)
