"""BrainState Service — central shared state for the JATAYU pipeline.

All pipeline services read their runtime context from here.
All pipeline services write state changes through here.
No service reads from another service directly.

Design rules (from Brain Contract v1):
- Single source of truth for all runtime state.
- Every write emits an event via EventLog.
- No imports from pipeline services (no circular deps).
- Storage: data/workspaces.json for crash recovery.
- Sessions expire after 2 hours of inactivity.
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jatayu.pipeline.event_log import EventLog

logger = logging.getLogger(__name__)

SESSION_TTL_HOURS = 2


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class Workspace:
    """What JATAYU is actively working on right now.

    This is the user-facing concept inside BrainState. It describes
    what the OS is currently doing, not internal LLM context.
    """
    session_id: str
    current_project: dict | None = None          # entity record
    current_document: str | None = None          # document name/id
    current_meeting: dict | None = None          # entity record
    open_draft: str | None = None                # draft subject/id
    selected_agent: str | None = None            # agent name
    current_people: list[dict] = field(default_factory=list)
    current_task: str | None = None              # human-readable current task
    current_goals: list[str] = field(default_factory=list)
    today_focus: str | None = None
    running_tasks: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())
    last_used: str = field(default_factory=lambda: _now())
    expires_at: str = field(default_factory=lambda: _expiry())

    def is_expired(self) -> bool:
        try:
            exp = datetime.fromisoformat(self.expires_at)
            return datetime.now(timezone.utc) > exp
        except Exception:
            return True

    def touch(self) -> None:
        """Refresh TTL on activity."""
        self.last_used = _now()
        self.expires_at = _expiry()

    def to_dict(self) -> dict:
        return asdict(self)

    def to_summary(self) -> str:
        """Compact text representation for system prompt injection."""
        parts = []
        if self.current_project:
            parts.append(f"Active project: {self.current_project.get('name', 'Unknown')}")
        if self.current_document:
            parts.append(f"Current document: {self.current_document}")
        if self.current_people:
            names = [p.get("name", "?") for p in self.current_people[:3]]
            parts.append(f"Active people: {', '.join(names)}")
        if self.current_task:
            parts.append(f"Current task: {self.current_task}")
        if self.open_draft:
            parts.append(f"Open draft: {self.open_draft}")
        if self.selected_agent:
            parts.append(f"Selected agent: {self.selected_agent}")
        if self.today_focus:
            parts.append(f"Today's focus: {self.today_focus}")
        return "\n".join(parts) if parts else ""


@dataclass
class BrainStateSnapshot:
    """Full observable state at a single point in time.

    Passed to pipeline services that need a consistent read-only view.
    """
    workspace: Workspace
    active_conversation_id: str | None = None
    active_agent: str | None = None
    pipeline_phase: str = "idle"   # "classifying" | "planning" | "executing" | "responding" | "idle"
    current_model: str | None = None


# ── Service ───────────────────────────────────────────────────────────────────

class BrainStateService:
    """Central shared state service.

    All pipeline services read from and write to this service.
    No service reads from another service directly.

    Args:
        data_dir:  Directory for workspace persistence.
        event_log: EventLog instance. If None, events are logged but not emitted.
    """

    def __init__(self, data_dir: str, event_log: EventLog | None = None) -> None:
        self._path = Path(data_dir) / "workspaces.json"
        self._event_log = event_log
        self._workspaces: dict[str, Workspace] = {}
        self._meta: dict[str, dict] = {}   # session_id → {conv_id, agent, phase, model}
        self._lock = threading.RLock()
        self._load()

    # ── Workspace API ─────────────────────────────────────────────────────────

    def get_workspace(self, session_id: str) -> Workspace:
        """Return the workspace for a session, creating it if needed."""
        with self._lock:
            ws = self._workspaces.get(session_id)
            if ws is None or ws.is_expired():
                ws = Workspace(session_id=session_id)
                self._workspaces[session_id] = ws
                self._emit("workspace.created", {"session_id": session_id}, session_id)
            return ws

    def update_workspace(self, session_id: str, **fields: Any) -> None:
        """Update specific fields on a workspace.

        Valid fields mirror the Workspace dataclass attributes.
        Unknown fields are ignored with a warning.
        """
        with self._lock:
            ws = self.get_workspace(session_id)
            changed = {}
            for key, value in fields.items():
                if not hasattr(ws, key):
                    logger.warning("BrainState: unknown workspace field '%s' — ignored", key)
                    continue
                setattr(ws, key, value)
                changed[key] = value
            ws.touch()
            if changed:
                self._emit("workspace.updated", {"session_id": session_id, "fields": list(changed.keys())}, session_id)
                self._persist()

    def get_snapshot(self, session_id: str) -> BrainStateSnapshot:
        """Return a read-only snapshot of the full brain state."""
        ws = self.get_workspace(session_id)
        meta = self._meta.get(session_id, {})
        return BrainStateSnapshot(
            workspace=ws,
            active_conversation_id=meta.get("conv_id"),
            active_agent=meta.get("agent"),
            pipeline_phase=meta.get("phase", "idle"),
            current_model=meta.get("model"),
        )

    # ── Metadata setters ──────────────────────────────────────────────────────

    def set_phase(self, session_id: str, phase: str) -> None:
        """Update the pipeline execution phase for observability."""
        with self._lock:
            self._meta.setdefault(session_id, {})["phase"] = phase

    def set_active_conversation(self, session_id: str, conversation_id: str) -> None:
        with self._lock:
            self._meta.setdefault(session_id, {})["conv_id"] = conversation_id

    def set_active_agent(self, session_id: str, agent_name: str) -> None:
        """Record which agent is currently handling this session."""
        with self._lock:
            old = self._meta.get(session_id, {}).get("agent")
            self._meta.setdefault(session_id, {})["agent"] = agent_name
            if old != agent_name:
                self._emit("agent.switched", {"from": old, "to": agent_name}, session_id)

    def set_active_model(self, session_id: str, model: str) -> None:
        """Record which model is currently active for this session."""
        with self._lock:
            old = self._meta.get(session_id, {}).get("model")
            self._meta.setdefault(session_id, {})["model"] = model
            if old != model:
                self._emit("model.switched", {"from": old, "to": model}, session_id)

    # ── Project / People helpers ──────────────────────────────────────────────

    def activate_project(self, session_id: str, project: dict) -> None:
        """Mark a project as the active workspace project."""
        self.update_workspace(session_id, current_project=project)
        self._emit("project.activated", {"project": project.get("name")}, session_id)

    def add_active_person(self, session_id: str, person: dict) -> None:
        """Add a person to the active people list (dedup by id)."""
        ws = self.get_workspace(session_id)
        existing_ids = {p.get("id") for p in ws.current_people}
        if person.get("id") not in existing_ids:
            people = ws.current_people + [person]
            self.update_workspace(session_id, current_people=people)

    # ── Expiry ────────────────────────────────────────────────────────────────

    def expire_old_workspaces(self) -> int:
        """Remove expired workspaces. Returns count removed."""
        removed = 0
        with self._lock:
            expired = [sid for sid, ws in self._workspaces.items() if ws.is_expired()]
            for sid in expired:
                del self._workspaces[sid]
                self._meta.pop(sid, None)
                self._emit("workspace.expired", {"session_id": sid}, sid)
                removed += 1
            if removed:
                self._persist()
        return removed

    # ── Serialization ─────────────────────────────────────────────────────────

    def to_dict(self, session_id: str | None = None) -> dict:
        """Serialize state for the REST API (/api/brain/state)."""
        if session_id:
            snap = self.get_snapshot(session_id)
            return {
                "workspace": snap.workspace.to_dict(),
                "pipeline_phase": snap.pipeline_phase,
                "active_agent": snap.active_agent,
                "active_conversation_id": snap.active_conversation_id,
                "current_model": snap.current_model,
            }
        return {
            "session_count": len(self._workspaces),
            "sessions": [ws.session_id for ws in self._workspaces.values()],
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _emit(self, event_type: str, data: dict, session_id: str) -> None:
        if self._event_log:
            try:
                self._event_log.emit(
                    type=event_type,
                    data=data,
                    source="brain_state",
                    session_id=session_id,
                )
            except Exception as exc:
                logger.error("BrainState: event emission failed: %s", exc)

    def _persist(self) -> None:
        """Write current workspaces to disk (crash recovery)."""
        try:
            data = {sid: ws.to_dict() for sid, ws in self._workspaces.items()}
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
        except Exception as exc:
            logger.error("BrainState: persistence failed: %s", exc)

    def _load(self) -> None:
        """Load workspaces from disk on startup."""
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            loaded = 0
            for sid, data in raw.items():
                try:
                    ws = Workspace(**data)
                    if not ws.is_expired():
                        self._workspaces[sid] = ws
                        loaded += 1
                except Exception:
                    pass  # Corrupt entry — skip
            logger.info("BrainState: loaded %d active workspace(s)", loaded)
        except Exception as exc:
            logger.warning("BrainState: could not load workspaces: %s", exc)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=SESSION_TTL_HOURS)).isoformat()
