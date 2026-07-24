"""Workspace data models — pure data classes, no I/O, no external imports.

All models are JSON-serializable via .to_dict() / from_dict().
All IDs are stable slugs (or UUID hex for new records).
Entity IDs from entities.py are the join key across all models.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any


# ── Enums ──────────────────────────────────────────────────────────────────────

class TaskStatus(str, Enum):
    TODO        = "todo"
    IN_PROGRESS = "in_progress"
    DONE        = "done"
    BLOCKED     = "blocked"
    CANCELLED   = "cancelled"

    def is_active(self) -> bool:
        return self in (TaskStatus.TODO, TaskStatus.IN_PROGRESS, TaskStatus.BLOCKED)

    def is_terminal(self) -> bool:
        return self in (TaskStatus.DONE, TaskStatus.CANCELLED)


class NoteType(str, Enum):
    NOTE         = "note"
    DECISION     = "decision"
    IDEA         = "idea"
    REMINDER     = "reminder"
    MEETING_NOTE = "meeting_note"


class CaptureType(str, Enum):
    TASK      = "task"
    REMINDER  = "reminder"
    NOTE      = "note"
    MEETING   = "meeting"
    DECISION  = "decision"
    IDEA      = "idea"
    DEADLINE  = "deadline"


class WorkspaceStatus(str, Enum):
    ACTIVE    = "active"
    PAUSED    = "paused"
    COMPLETED = "completed"
    ARCHIVED  = "archived"
    DELETED   = "deleted"


# ── Task model ─────────────────────────────────────────────────────────────────

@dataclass
class WorkspaceTask:
    """A single task inside a workspace.

    depends_on is a list of task IDs that must be DONE before this task
    can be moved to IN_PROGRESS. If any dependency is not done, status
    should be BLOCKED.
    """
    id: str
    title: str
    description: str = ""
    status: str = TaskStatus.TODO
    priority: int = 3                     # 1 (highest) → 5 (lowest)
    due_date: str | None = None           # ISO 8601 date string
    assigned_to: str | None = None        # entity_id
    depends_on: list[str] = field(default_factory=list)   # list of task_ids
    workspace_id: str = ""
    entity_refs: list[str] = field(default_factory=list)  # linked entity_ids
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    completed_at: str | None = None
    source: str = "manual"               # "manual" | "fast_capture" | "telegram" | "web"

    @classmethod
    def new(cls, title: str, **kwargs) -> "WorkspaceTask":
        return cls(id=_new_id(), title=title, **kwargs)

    def is_overdue(self) -> bool:
        if not self.due_date or self.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
            return False
        try:
            due = datetime.fromisoformat(self.due_date)
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            return datetime.now(timezone.utc) > due
        except Exception:
            return False

    def mark_done(self) -> None:
        self.status = TaskStatus.DONE
        self.completed_at = _now()
        self.updated_at = _now()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "priority": self.priority,
            "due_date": self.due_date,
            "assigned_to": self.assigned_to,
            "depends_on": self.depends_on,
            "workspace_id": self.workspace_id,
            "entity_refs": self.entity_refs,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
            "is_overdue": self.is_overdue(),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "WorkspaceTask":
        data.pop("is_overdue", None)  # computed field, not stored
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Note model ─────────────────────────────────────────────────────────────────

@dataclass
class WorkspaceNote:
    """A note, decision, idea, or reminder attached to a workspace."""
    id: str
    content: str
    note_type: str = NoteType.NOTE
    tags: list[str] = field(default_factory=list)
    entity_refs: list[str] = field(default_factory=list)  # linked entity_ids
    workspace_id: str = ""
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    source: str = "manual"

    @classmethod
    def new(cls, content: str, note_type: str = NoteType.NOTE, **kwargs) -> "WorkspaceNote":
        return cls(id=_new_id(), content=content, note_type=note_type, **kwargs)

    def preview(self, max_len: int = 80) -> str:
        if len(self.content) <= max_len:
            return self.content
        return self.content[:max_len].rsplit(" ", 1)[0] + "…"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkspaceNote":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Meeting model ──────────────────────────────────────────────────────────────

@dataclass
class WorkspaceMeeting:
    """A meeting record linked to a workspace."""
    id: str
    title: str
    date: str                                              # ISO 8601
    duration_min: int = 60
    attendees: list[str] = field(default_factory=list)    # entity_ids
    notes: str = ""
    action_item_ids: list[str] = field(default_factory=list)  # task_ids
    workspace_id: str = ""
    created_at: str = field(default_factory=lambda: _now())
    source: str = "manual"

    @classmethod
    def new(cls, title: str, date: str, **kwargs) -> "WorkspaceMeeting":
        return cls(id=_new_id(), title=title, date=date, **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkspaceMeeting":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Timeline model ─────────────────────────────────────────────────────────────

@dataclass
class TimelineEntry:
    """A single entry in the workspace activity feed."""
    id: str
    workspace_id: str
    event_type: str        # "task_created" | "task_done" | "note_added" | "meeting_added" | etc.
    description: str
    entity_refs: list[str] = field(default_factory=list)
    task_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: _now())

    @classmethod
    def new(
        cls,
        workspace_id: str,
        event_type: str,
        description: str,
        **kwargs,
    ) -> "TimelineEntry":
        return cls(
            id=_new_id(),
            workspace_id=workspace_id,
            event_type=event_type,
            description=description,
            **kwargs,
        )

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "TimelineEntry":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# ── Health model ───────────────────────────────────────────────────────────────

@dataclass
class WorkspaceHealth:
    """Computed health snapshot for a workspace."""
    workspace_id: str
    health_score: float          # 0 – 100
    health_status: str           # "healthy" | "at_risk" | "stale" | "critical"
    completion_pct: float        # 0 – 100
    total_tasks: int
    active_tasks: int
    overdue_count: int
    blocked_count: int
    recent_activity_count: int   # events in last 7 days
    days_since_activity: int | None
    has_goals: bool
    computed_at: str = field(default_factory=lambda: _now())

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def empty(cls, workspace_id: str) -> "WorkspaceHealth":
        return cls(
            workspace_id=workspace_id,
            health_score=50.0,
            health_status="healthy",
            completion_pct=0.0,
            total_tasks=0,
            active_tasks=0,
            overdue_count=0,
            blocked_count=0,
            recent_activity_count=0,
            days_since_activity=None,
            has_goals=False,
        )


# ── CaptureItem model ──────────────────────────────────────────────────────────

@dataclass
class CaptureItem:
    """A single classified item produced by FastCapture."""
    type: str                         # CaptureType value
    content: str
    confidence: float                 # 0.0 – 1.0
    entity_refs: list[str] = field(default_factory=list)
    workspace_id: str | None = None
    due_date: str | None = None
    source_text: str = ""            # original sentence/bullet
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CaptureResult:
    """Full result from a FastCapture call."""
    items: list[CaptureItem] = field(default_factory=list)
    detected_workspace_id: str | None = None
    detected_workspace_name: str | None = None
    detected_entities: list[dict] = field(default_factory=list)
    requires_clarification: bool = False
    clarification_question: str | None = None
    raw_text: str = ""

    def to_dict(self) -> dict:
        return {
            "items": [i.to_dict() for i in self.items],
            "detected_workspace_id": self.detected_workspace_id,
            "detected_workspace_name": self.detected_workspace_name,
            "detected_entities": self.detected_entities,
            "requires_clarification": self.requires_clarification,
            "clarification_question": self.clarification_question,
        }


# ── Suggestion model ───────────────────────────────────────────────────────────

@dataclass
class SuggestionItem:
    """A proactive suggestion generated by the SuggestionEngine."""
    id: str
    type: str          # stale_work | overdue | repeated_mention | unfinished_idea | goals_without_tasks | tasks_ready_to_unblock
    priority: str      # high | medium | low
    message: str
    action_hint: str
    workspace_id: str | None = None
    workspace_name: str | None = None
    entity_refs: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    generated_at: str = field(default_factory=lambda: _now())

    @classmethod
    def new(cls, type: str, priority: str, message: str, action_hint: str, **kwargs) -> "SuggestionItem":
        return cls(id=_new_id(), type=type, priority=priority,
                   message=message, action_hint=action_hint, **kwargs)

    def to_dict(self) -> dict:
        return asdict(self)
# ── DailyBrief model ──────────────────────────────────────────────────────────

@dataclass
class WorkspaceBriefItem:
    """Summary of a single workspace for the Daily Brief."""
    workspace_id: str
    workspace_name: str
    health: WorkspaceHealth
    tasks_due_today: list[dict]
    overdue_tasks: list[dict]
    recent_notes: list[dict]

    def to_dict(self) -> dict:
        return {
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace_name,
            "health": self.health.to_dict(),
            "tasks_due_today": self.tasks_due_today,
            "overdue_tasks": self.overdue_tasks,
            "recent_notes": self.recent_notes,
        }


@dataclass
class DailyBrief:
    """Structured morning brief — pure data, UI renders it."""
    generated_at: str
    workspace_summaries: list[WorkspaceBriefItem] = field(default_factory=list)
    tasks_due_today: list[dict] = field(default_factory=list)
    tasks_overdue: list[dict] = field(default_factory=list)
    upcoming_tasks: list[dict] = field(default_factory=list)     # due this week
    health_alerts: list[dict] = field(default_factory=list)      # health < 40
    suggestions: list[dict] = field(default_factory=list)
    recent_entities: list[dict] = field(default_factory=list)
    total_workspaces: int = 0
    total_active_tasks: int = 0
    
    # Expanded Morning Brief Fields
    meetings_today: list[dict] = field(default_factory=list)
    blocked_workspaces: list[dict] = field(default_factory=list)
    high_priority_observations: list[dict] = field(default_factory=list)
    recent_memory_updates: list[dict] = field(default_factory=list)
    people_awaiting_response: list[dict] = field(default_factory=list)
    suggested_first_task: dict | None = None

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "total_workspaces": self.total_workspaces,
            "total_active_tasks": self.total_active_tasks,
            "meetings_today": self.meetings_today,
            "blocked_workspaces": self.blocked_workspaces,
            "high_priority_observations": self.high_priority_observations,
            "recent_memory_updates": self.recent_memory_updates,
            "people_awaiting_response": self.people_awaiting_response,
            "suggested_first_task": self.suggested_first_task,
            "workspace_summaries": [w.to_dict() for w in self.workspace_summaries],
            "tasks_due_today": self.tasks_due_today,
            "tasks_overdue": self.tasks_overdue,
            "upcoming_tasks": self.upcoming_tasks,
            "health_alerts": self.health_alerts,
            "suggestions": self.suggestions,
            "recent_entities": self.recent_entities,
        }


# ── Main Workspace model ───────────────────────────────────────────────────────

@dataclass
class Workspace:
    """A project workspace — the OS-level container for all work items.

    Every project entity maps to exactly one Workspace.
    Everything is linked via entity_id instead of free text.
    """
    id: str                                                 # stable slug
    name: str
    entity_id: str                                          # links to project in entities.json
    status: str = WorkspaceStatus.ACTIVE
    goals: list[str] = field(default_factory=list)
    tasks: list[dict] = field(default_factory=list)         # serialized WorkspaceTask dicts
    notes: list[dict] = field(default_factory=list)         # serialized WorkspaceNote dicts
    meetings: list[dict] = field(default_factory=list)      # serialized WorkspaceMeeting dicts
    timeline: list[dict] = field(default_factory=list)      # serialized TimelineEntry dicts (last 200)
    team: list[str] = field(default_factory=list)           # entity_ids of team members
    knowledge_refs: list[str] = field(default_factory=list) # doc names / Obsidian links
    version: int = 1
    history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())

    # ── Task helpers ──────────────────────────────────────────────────────

    def get_tasks(self) -> list[WorkspaceTask]:
        result = []
        for t in self.tasks:
            try:
                result.append(WorkspaceTask.from_dict(dict(t)))
            except Exception:
                pass
        return result

    def get_active_tasks(self) -> list[WorkspaceTask]:
        return [t for t in self.get_tasks() if TaskStatus(t.status).is_active()]

    def get_done_tasks(self) -> list[WorkspaceTask]:
        return [t for t in self.get_tasks() if t.status == TaskStatus.DONE]

    def get_blocked_tasks(self) -> list[WorkspaceTask]:
        return [t for t in self.get_tasks() if t.status == TaskStatus.BLOCKED]

    def get_overdue_tasks(self) -> list[WorkspaceTask]:
        return [t for t in self.get_tasks() if t.is_overdue()]

    def get_tasks_due_today(self) -> list[WorkspaceTask]:
        today = datetime.now(timezone.utc).date().isoformat()
        return [
            t for t in self.get_tasks()
            if t.due_date and t.due_date.startswith(today) and not t.status == TaskStatus.DONE
        ]

    def find_task(self, task_id: str) -> WorkspaceTask | None:
        for t in self.get_tasks():
            if t.id == task_id:
                return t
        return None

    # ── Note helpers ──────────────────────────────────────────────────────

    def get_notes(self) -> list[WorkspaceNote]:
        result = []
        for n in self.notes:
            try:
                result.append(WorkspaceNote.from_dict(dict(n)))
            except Exception:
                pass
        return result

    def get_recent_notes(self, days: int = 7) -> list[WorkspaceNote]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for n in self.get_notes():
            try:
                created = datetime.fromisoformat(n.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    result.append(n)
            except Exception:
                pass
        return sorted(result, key=lambda n: n.created_at, reverse=True)

    # ── Timeline helpers ──────────────────────────────────────────────────

    def get_timeline(self) -> list[TimelineEntry]:
        result = []
        for e in self.timeline:
            try:
                result.append(TimelineEntry.from_dict(dict(e)))
            except Exception:
                pass
        return sorted(result, key=lambda e: e.timestamp, reverse=True)

    def get_recent_timeline(self, days: int = 7) -> list[TimelineEntry]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = []
        for entry in self.get_timeline():
            try:
                ts = datetime.fromisoformat(entry.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                if ts >= cutoff:
                    result.append(entry)
            except Exception:
                pass
        return result

    # ── Dependency helpers ────────────────────────────────────────────────

    def get_dependency_chain(self, task_id: str) -> list[WorkspaceTask]:
        """Return all tasks that block the given task_id (transitive)."""
        all_tasks = {t.id: t for t in self.get_tasks()}
        chain: list[WorkspaceTask] = []
        visited: set[str] = set()

        def _collect(tid: str) -> None:
            if tid in visited:
                return
            visited.add(tid)
            t = all_tasks.get(tid)
            if t:
                for dep_id in t.depends_on:
                    dep = all_tasks.get(dep_id)
                    if dep and not dep.status == TaskStatus.DONE:
                        chain.append(dep)
                        _collect(dep_id)

        _collect(task_id)
        return chain

    def compute_blocked_status(self) -> None:
        """Update BLOCKED status for all tasks based on their dependencies."""
        all_tasks = {t.id: t for t in self.get_tasks()}
        changed = False

        for task in all_tasks.values():
            if not task.depends_on or task.status in (TaskStatus.DONE, TaskStatus.CANCELLED):
                continue
            blocking = [
                all_tasks[dep_id]
                for dep_id in task.depends_on
                if dep_id in all_tasks and not all_tasks[dep_id].status == TaskStatus.DONE
            ]
            should_be_blocked = len(blocking) > 0
            if should_be_blocked and task.status != TaskStatus.BLOCKED:
                task.status = TaskStatus.BLOCKED
                task.updated_at = _now()
                changed = True
            elif not should_be_blocked and task.status == TaskStatus.BLOCKED:
                task.status = TaskStatus.TODO
                task.updated_at = _now()
                changed = True

        if changed:
            self.tasks = [t.to_dict() for t in all_tasks.values()]
            self.updated_at = _now()

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "entity_id": self.entity_id,
            "status": self.status,
            "goals": self.goals,
            "tasks": self.tasks,
            "notes": self.notes,
            "meetings": self.meetings,
            "timeline": self.timeline[-200:],  # Keep last 200 entries
            "team": self.team,
            "knowledge_refs": self.knowledge_refs,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Workspace":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    def to_summary(self) -> dict:
        """Compact summary for list views and BrainState injection."""
        active = self.get_active_tasks()
        return {
            "id": self.id,
            "name": self.name,
            "entity_id": self.entity_id,
            "status": self.status,
            "goal_count": len(self.goals),
            "active_task_count": len(active),
            "total_task_count": len(self.tasks),
            "note_count": len(self.notes),
            "team_count": len(self.team),
            "updated_at": self.updated_at,
        }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _new_id() -> str:
    return uuid.uuid4().hex[:12]
