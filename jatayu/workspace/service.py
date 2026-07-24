"""WorkspaceService — CRUD for all workspace data.

Storage layout:
    data/workspaces/
        index.json              entity_id → workspace_id
        {workspace_id}.json     one file per workspace

Design rules:
- Every write emits an EventLog event.
- Every write records a TimelineEntry in the workspace.
- Thread-safe via a per-workspace lock dict + global index lock.
- Backward compatible: if data/workspaces/ doesn't exist, it is created on first write.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from re import sub
from typing import TYPE_CHECKING, Any

from jatayu.workspace.models import (
    Workspace,
    WorkspaceTask,
    WorkspaceNote,
    WorkspaceMeeting,
    TimelineEntry,
    WorkspaceHealth,
    TaskStatus,
    NoteType,
    WorkspaceStatus,
    _now,
    _new_id,
)

if TYPE_CHECKING:
    from jatayu.pipeline.event_log import EventLog

logger = logging.getLogger(__name__)

MAX_TIMELINE_ENTRIES = 500


class WorkspaceService:
    """CRUD for project workspaces.

    Args:
        data_dir:  Root data directory (e.g. "data/").
        event_log: Optional EventLog for emitting workspace events.
    """

    def __init__(self, data_dir: str, event_log: "EventLog | None" = None) -> None:
        self._root = Path(data_dir) / "workspaces"
        self._root.mkdir(parents=True, exist_ok=True)
        self._index_path = self._root / "index.json"
        self._event_log = event_log
        self._index: dict[str, str] = {}       # entity_id → workspace_id
        self._locks: dict[str, threading.Lock] = {}
        self._index_lock = threading.Lock()
        self._load_index()
        logger.info("WorkspaceService: ready at %s (%d workspaces)", self._root, len(self._index))

    # ── Workspace lifecycle ────────────────────────────────────────────────────

    def get_or_create(self, entity_id: str, name: str) -> Workspace:
        """Return existing workspace for entity_id or create a new one."""
        with self._index_lock:
            workspace_id = self._index.get(entity_id)
        if workspace_id:
            ws = self._load_workspace(workspace_id)
            if ws:
                return ws

        # Create new workspace
        workspace_id = _slugify(name) or _new_id()
        # Ensure uniqueness
        if (self._root / f"{workspace_id}.json").exists():
            workspace_id = workspace_id + "-" + _new_id()[:4]

        ws = Workspace(
            id=workspace_id,
            name=name,
            entity_id=entity_id,
        )
        self._save_workspace(ws)
        with self._index_lock:
            self._index[entity_id] = workspace_id
            self._save_index()
        self._emit("workspace.created", {"workspace_id": workspace_id, "name": name})
        logger.info("WorkspaceService: created workspace '%s' for entity '%s'", name, entity_id)
        return ws

    def get_by_id(self, workspace_id: str) -> Workspace | None:
        return self._load_workspace(workspace_id)

    def find_by_entity(self, entity_id: str) -> Workspace | None:
        with self._index_lock:
            workspace_id = self._index.get(entity_id)
        if not workspace_id:
            return None
        return self._load_workspace(workspace_id)

    def list_all(self, include_deleted: bool = False) -> list[Workspace]:
        """Return all workspaces (active + others). Filters out deleted/archived by default."""
        workspaces = []
        for f in self._root.glob("*.json"):
            if f.name == "index.json":
                continue
            ws = self._load_workspace(f.stem)
            if ws:
                if not include_deleted and ws.status in (WorkspaceStatus.DELETED, WorkspaceStatus.ARCHIVED):
                    continue
                workspaces.append(ws)
        return sorted(workspaces, key=lambda w: w.updated_at, reverse=True)

    def list_summaries(self) -> list[dict]:
        """Return compact summaries of all workspaces (for list API)."""
        return [ws.to_summary() for ws in self.list_all()]

    def update_workspace_meta(self, workspace_id: str, **fields: Any) -> bool:
        """Update top-level workspace metadata fields (name, status, goals, team, knowledge_refs)."""
        ALLOWED = {"name", "status", "goals", "team", "knowledge_refs"}
        ws = self._load_workspace(workspace_id)
        if not ws:
            return False
        
        changed = False
        snapshot = {k: getattr(ws, k) for k in ALLOWED if hasattr(ws, k)}
        
        for k, v in fields.items():
            if k in ALLOWED and hasattr(ws, k):
                if getattr(ws, k) != v:
                    setattr(ws, k, v)
                    changed = True
                    
        if changed:
            if not hasattr(ws, "history"):
                ws.history = []
            ws.history.append({
                "timestamp": _now(),
                "state": snapshot
            })
            if hasattr(ws, "version"):
                ws.version += 1
            ws.updated_at = _now()
            self._save_workspace(ws)
            self._emit("workspace.updated", {"workspace_id": workspace_id, "fields": list(fields.keys())})
        return changed

    # ── Task CRUD ─────────────────────────────────────────────────────────────

    def add_task(self, workspace_id: str, task: WorkspaceTask) -> WorkspaceTask | None:
        """Add a task to a workspace. Returns saved task or None on failure."""
        ws = self._load_workspace(workspace_id)
        if not ws:
            return None
        task.workspace_id = workspace_id
        if not task.id:
            task.id = _new_id()
        ws.tasks.append(task.to_dict())
        ws.updated_at = _now()
        # Evaluate blocking immediately: if this task depends on unfinished tasks, mark BLOCKED
        ws.compute_blocked_status()
        self._record_timeline(ws, TimelineEntry.new(
            workspace_id=workspace_id,
            event_type="task_created",
            description=f"Task added: {task.title}",
            task_ids=[task.id],
            entity_refs=task.entity_refs,
        ))
        self._save_workspace(ws)
        # Refresh the saved task status (compute_blocked_status may have changed it)
        saved_ws = self._load_workspace(workspace_id)
        task = saved_ws.find_task(task.id) if saved_ws else task
        self._emit("workspace.task.created", {
            "workspace_id": workspace_id,
            "task_id": task.id,
            "title": task.title,
            "priority": task.priority,
            "due_date": task.due_date,
        })
        return task


    def update_task_status(
        self, workspace_id: str, task_id: str, status: str
    ) -> WorkspaceTask | None:
        """Update task status. When a task is completed, re-evaluates dependents."""
        ws = self._load_workspace(workspace_id)
        if not ws:
            return None

        all_tasks = {t.id: t for t in ws.get_tasks()}
        task = all_tasks.get(task_id)
        if not task:
            return None

        old_status = task.status
        task.status = status
        task.updated_at = _now()
        if status == TaskStatus.DONE:
            task.completed_at = _now()

        all_tasks[task_id] = task
        ws.tasks = [t.to_dict() for t in all_tasks.values()]
        ws.updated_at = _now()

        # Re-evaluate blocked status for all tasks after a completion
        if status == TaskStatus.DONE:
            ws.compute_blocked_status()

        event_type = "task_completed" if status == TaskStatus.DONE else "task_updated"
        desc = f"{'✅' if status == TaskStatus.DONE else '🔄'} Task {status}: {task.title}"
        self._record_timeline(ws, TimelineEntry.new(
            workspace_id=workspace_id,
            event_type=event_type,
            description=desc,
            task_ids=[task_id],
        ))
        self._save_workspace(ws)
        self._emit(f"workspace.task.{status}", {
            "workspace_id": workspace_id,
            "task_id": task_id,
            "title": task.title,
            "old_status": old_status,
        })
        return task

    def update_task(self, workspace_id: str, task_id: str, **fields: Any) -> WorkspaceTask | None:
        """Update arbitrary task fields."""
        ALLOWED = {"title", "description", "priority", "due_date", "assigned_to", "tags", "entity_refs", "depends_on"}
        ws = self._load_workspace(workspace_id)
        if not ws:
            return None
        all_tasks = {t.id: t for t in ws.get_tasks()}
        task = all_tasks.get(task_id)
        if not task:
            return None
        for k, v in fields.items():
            if k in ALLOWED and hasattr(task, k):
                setattr(task, k, v)
        task.updated_at = _now()
        all_tasks[task_id] = task
        ws.tasks = [t.to_dict() for t in all_tasks.values()]
        ws.updated_at = _now()
        self._save_workspace(ws)
        return task

    def get_blocked_tasks(self, workspace_id: str) -> list[WorkspaceTask]:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return []
        return ws.get_blocked_tasks()

    def get_dependency_chain(self, workspace_id: str, task_id: str) -> list[WorkspaceTask]:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return []
        return ws.get_dependency_chain(task_id)

    def list_tasks(
        self,
        workspace_id: str,
        status_filter: str | None = None,
        priority_max: int | None = None,
    ) -> list[WorkspaceTask]:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return []
        tasks = ws.get_tasks()
        if status_filter:
            tasks = [t for t in tasks if t.status == status_filter]
        if priority_max:
            tasks = [t for t in tasks if t.priority <= priority_max]
        return sorted(tasks, key=lambda t: (t.priority, t.due_date or "9999"))

    # ── Note CRUD ─────────────────────────────────────────────────────────────

    def add_note(self, workspace_id: str, note: WorkspaceNote) -> WorkspaceNote | None:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return None
        note.workspace_id = workspace_id
        if not note.id:
            note.id = _new_id()
        ws.notes.append(note.to_dict())
        ws.updated_at = _now()
        icon = {"decision": "⚡", "idea": "💡", "reminder": "🔔", "meeting_note": "📋"}.get(note.note_type, "📝")
        self._record_timeline(ws, TimelineEntry.new(
            workspace_id=workspace_id,
            event_type="note_added",
            description=f"{icon} {note.note_type.title()}: {note.preview()}",
            entity_refs=note.entity_refs,
        ))
        self._save_workspace(ws)
        self._emit("workspace.note.added", {
            "workspace_id": workspace_id,
            "note_id": note.id,
            "note_type": note.note_type,
        })
        return note

    def list_notes(
        self, workspace_id: str, note_type: str | None = None
    ) -> list[WorkspaceNote]:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return []
        notes = ws.get_notes()
        if note_type:
            notes = [n for n in notes if n.note_type == note_type]
        return sorted(notes, key=lambda n: n.created_at, reverse=True)

    # ── Meeting CRUD ──────────────────────────────────────────────────────────

    def add_meeting(
        self, workspace_id: str, meeting: WorkspaceMeeting
    ) -> WorkspaceMeeting | None:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return None
        meeting.workspace_id = workspace_id
        if not meeting.id:
            meeting.id = _new_id()
        ws.meetings.append(meeting.to_dict())
        ws.updated_at = _now()
        self._record_timeline(ws, TimelineEntry.new(
            workspace_id=workspace_id,
            event_type="meeting_added",
            description=f"📅 Meeting: {meeting.title} on {meeting.date[:10]}",
            entity_refs=meeting.attendees,
        ))
        self._save_workspace(ws)
        self._emit("workspace.meeting.added", {
            "workspace_id": workspace_id,
            "meeting_id": meeting.id,
            "title": meeting.title,
            "date": meeting.date,
        })
        return meeting

    # ── Timeline ──────────────────────────────────────────────────────────────

    def get_timeline(
        self, workspace_id: str, limit: int = 50
    ) -> list[TimelineEntry]:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return []
        timeline = ws.get_timeline()
        return timeline[:limit]

    def record_external_event(
        self,
        workspace_id: str,
        event_type: str,
        description: str,
        **kwargs: Any,
    ) -> TimelineEntry | None:
        """Record an externally triggered timeline entry (e.g. from Dispatcher)."""
        ws = self._load_workspace(workspace_id)
        if not ws:
            return None
        entry = TimelineEntry.new(
            workspace_id=workspace_id,
            event_type=event_type,
            description=description,
            **kwargs,
        )
        self._record_timeline(ws, entry)
        self._save_workspace(ws)
        return entry

    # ── Health ────────────────────────────────────────────────────────────────

    def compute_health(self, workspace_id: str) -> WorkspaceHealth:
        ws = self._load_workspace(workspace_id)
        if not ws:
            return WorkspaceHealth.empty(workspace_id)
        from jatayu.workspace.health import WorkspaceHealthCalculator
        return WorkspaceHealthCalculator().compute(ws)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _load_workspace(self, workspace_id: str) -> Workspace | None:
        path = self._root / f"{workspace_id}.json"
        if not path.exists():
            return None
        lock = self._get_lock(workspace_id)
        with lock:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return Workspace.from_dict(data)
            except Exception as exc:
                logger.error("WorkspaceService: failed to load '%s': %s", workspace_id, exc)
                return None

    def _save_workspace(self, ws: Workspace) -> None:
        path = self._root / f"{ws.id}.json"
        lock = self._get_lock(ws.id)
        with lock:
            try:
                path.write_text(
                    json.dumps(ws.to_dict(), indent=2, default=str),
                    encoding="utf-8",
                )
            except Exception as exc:
                logger.error("WorkspaceService: failed to save '%s': %s", ws.id, exc)

    def _get_lock(self, workspace_id: str) -> threading.Lock:
        if workspace_id not in self._locks:
            self._locks[workspace_id] = threading.Lock()
        return self._locks[workspace_id]

    def _load_index(self) -> None:
        if self._index_path.exists():
            try:
                self._index = json.loads(self._index_path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("WorkspaceService: failed to load index: %s", exc)
                self._index = {}

    def _save_index(self) -> None:
        try:
            self._index_path.write_text(
                json.dumps(self._index, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            logger.error("WorkspaceService: failed to save index: %s", exc)

    def _record_timeline(self, ws: Workspace, entry: TimelineEntry) -> None:
        """Append timeline entry and trim to MAX_TIMELINE_ENTRIES."""
        ws.timeline.append(entry.to_dict())
        if len(ws.timeline) > MAX_TIMELINE_ENTRIES:
            ws.timeline = ws.timeline[-MAX_TIMELINE_ENTRIES:]

    def _emit(self, event_type: str, data: dict) -> None:
        if self._event_log:
            try:
                self._event_log.emit(
                    type=event_type, data=data, source="workspace_service"
                )
            except Exception:
                pass


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = sub(r"[^\w\s-]", "", slug)
    slug = sub(r"[\s_]+", "-", slug)
    slug = sub(r"-+", "-", slug)
    return slug.strip("-")[:40]
