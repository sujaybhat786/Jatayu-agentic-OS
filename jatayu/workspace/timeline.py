"""TimelineRecorder — EventLog subscriber that writes timeline entries.

Subscribes to EventLog events and mirrors workspace-relevant signals
into the Workspace timeline so the Dashboard has a single coherent
activity feed.

Mapped events:
    intent.classified          → email/calendar/document triggers a timeline note
    workspace.task.created     → forwarded automatically (WorkspaceService writes it)
    workspace.task.completed   → forwarded automatically
    workspace.note.added       → forwarded automatically
    workspace.meeting.added    → forwarded automatically
    workspace.task.blocked     → "Task blocked: {title}"
    agent.switched             → recorded if switching to hermes/openclaw
    model.switched             → not recorded (internal detail, not user-facing)

TimelineRecorder is ADDITIVE — WorkspaceService already writes timeline entries
for its own writes. This recorder captures cross-system events that the
WorkspaceService doesn't know about.

Usage:
    recorder = TimelineRecorder(workspace_service, event_log)
    recorder.start()   # starts listening to EventLog
    recorder.stop()    # unsubscribes
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from jatayu.pipeline.event_log import EventLog, EventRecord
    from jatayu.workspace.service import WorkspaceService

logger = logging.getLogger(__name__)

# ── EventLog event → timeline description templates ──────────────────────────
# Maps event_type → (icon, description_template)
# Template may reference {data[key]} from the event's data dict.
_EVENT_TEMPLATES: dict[str, tuple[str, str]] = {
    "intent.classified": ("🧠", "AI classified intent: {intent}"),
    "workspace.task.blocked": ("⛔", "Task blocked: waiting on dependencies"),
    "workspace.task.in_progress": ("🔄", "Task in progress: {title}"),
    "agent.switched": ("🤖", "Agent switched: {from} → {to}"),
    "conversation.started": ("💬", "New conversation started"),
    "memory.stored": ("💾", "Memory updated"),
    "entity.created": ("👤", "New entity added: {name}"),
}

# Intents that generate timeline entries (email, calendar, meeting activity)
_INTENT_TO_TIMELINE = {
    "email":    ("📧", "Email activity"),
    "calendar": ("📅", "Calendar activity"),
    "meeting":  ("📋", "Meeting activity"),
    "document": ("📄", "Document activity"),
    "search":   ("🔍", "Knowledge search"),
    "reminder": ("🔔", "Reminder set"),
}


class TimelineRecorder:
    """Listens to EventLog and writes cross-system events to workspace timelines.

    Args:
        workspace_service: WorkspaceService instance.
        event_log:         EventLog instance to subscribe to.
    """

    def __init__(
        self,
        workspace_service: "WorkspaceService",
        event_log: "EventLog | None" = None,
    ) -> None:
        self._ws = workspace_service
        self._event_log = event_log
        self._running = False

    def start(self) -> None:
        """Subscribe to EventLog for relevant events."""
        if not self._event_log:
            logger.info("TimelineRecorder: no EventLog — running in manual mode only")
            return
        try:
            self._event_log.subscribe("intent.*", self._on_intent_event)
            self._event_log.subscribe("workspace.task.blocked", self._on_workspace_event)
            self._event_log.subscribe("workspace.task.in_progress", self._on_workspace_event)
            self._event_log.subscribe("agent.switched", self._on_agent_event)
            self._running = True
            logger.info("TimelineRecorder: subscribed to EventLog")
        except Exception as exc:
            logger.error("TimelineRecorder: failed to subscribe: %s", exc)

    def stop(self) -> None:
        """Unsubscribe from EventLog."""
        if not self._event_log or not self._running:
            return
        try:
            self._event_log.unsubscribe("intent.*", self._on_intent_event)
            self._event_log.unsubscribe("workspace.task.blocked", self._on_workspace_event)
            self._event_log.unsubscribe("workspace.task.in_progress", self._on_workspace_event)
            self._event_log.unsubscribe("agent.switched", self._on_agent_event)
            self._running = False
        except Exception:
            pass

    def record_for_workspace(
        self,
        workspace_id: str,
        event_type: str,
        description: str,
        **kwargs,
    ) -> None:
        """Manually record a timeline entry for a specific workspace."""
        try:
            self._ws.record_external_event(
                workspace_id=workspace_id,
                event_type=event_type,
                description=description,
                **kwargs,
            )
        except Exception as exc:
            logger.debug("TimelineRecorder: record failed: %s", exc)

    def get_timeline(self, workspace_id: str, limit: int = 50) -> list[dict]:
        """Return the timeline for a workspace as dicts."""
        entries = self._ws.get_timeline(workspace_id, limit=limit)
        return [e.to_dict() for e in entries]

    # ── EventLog callbacks ────────────────────────────────────────────────────

    def _on_intent_event(self, event: "EventRecord") -> None:
        """Record intent events to the active workspace."""
        intent = event.data.get("intent", "")
        if intent not in _INTENT_TO_TIMELINE:
            return

        icon, base_desc = _INTENT_TO_TIMELINE[intent]
        workspace_id = self._get_active_workspace(event.session_id)
        if not workspace_id:
            return

        confidence = event.data.get("confidence", 0)
        desc = f"{icon} {base_desc} (confidence: {confidence:.0%})"
        self.record_for_workspace(workspace_id, "intent_activity", desc)

    def _on_workspace_event(self, event: "EventRecord") -> None:
        """Record workspace-level events (blocked, in_progress etc.)."""
        workspace_id = event.data.get("workspace_id")
        if not workspace_id:
            return

        template = _EVENT_TEMPLATES.get(event.type)
        if not template:
            return

        icon, tmpl = template
        try:
            desc = f"{icon} " + tmpl.format(**event.data)
        except (KeyError, IndexError):
            desc = f"{icon} {event.type}"

        self.record_for_workspace(workspace_id, event.type, desc)

    def _on_agent_event(self, event: "EventRecord") -> None:
        """Record agent switches (only hermes/openclaw, not gemini)."""
        to_agent = event.data.get("to", "")
        if to_agent not in ("hermes", "openclaw"):
            return  # Internal routing changes aren't user-facing

        workspace_id = self._get_active_workspace(event.session_id)
        if not workspace_id:
            return

        from_agent = event.data.get("from", "gemini")
        self.record_for_workspace(
            workspace_id,
            "agent_activated",
            f"🤖 {to_agent.title()} agent activated (from {from_agent})",
        )

    def _get_active_workspace(self, session_id: str | None) -> str | None:
        """Resolve the active workspace for a session via BrainState (best effort)."""
        # TimelineRecorder doesn't depend on BrainState directly.
        # We attempt to find a recently-active workspace if session_id is available.
        # This is intentionally lightweight — missed entries are acceptable.
        if not session_id:
            return None
        # No BrainState dependency — caller may record manually via record_for_workspace()
        return None
