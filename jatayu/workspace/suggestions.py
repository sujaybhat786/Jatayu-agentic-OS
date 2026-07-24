"""SuggestionEngine — proactive suggestion generator.

Scans all workspaces for signals and returns SuggestionItem objects.
Does NOT notify the user. Suggestions are data — future notification
systems decide when and how to surface them.

Design rules:
- Pure read — never writes to any store.
- No LLM calls. No network requests.
- Called on demand (daily brief, API request) or scheduled.

Detects:
    stale_work           — task not updated in 5+ days
    overdue              — task past due_date
    repeated_mention     — same entity appears in 3+ notes without a task
    unfinished_idea      — idea note older than 7 days with no linked task
    goals_without_tasks  — workspace has goals but zero tasks
    tasks_ready_to_unblock — blocked task whose all deps are now DONE
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from jatayu.workspace.models import (
    SuggestionItem,
    TaskStatus,
    NoteType,
    _new_id,
    _now,
)

if TYPE_CHECKING:
    from jatayu.workspace.service import WorkspaceService
    from jatayu.workspace.models import Workspace, WorkspaceTask, WorkspaceNote

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
STALE_DAYS          = 5    # task not updated in N days → stale_work
IDEA_STALE_DAYS     = 7    # idea note older than N days with no linked task
REPEATED_MENTION_N  = 3    # entity mentioned N+ times without action → repeated_mention


class SuggestionEngine:
    """Proactive suggestion generator.

    Args:
        workspace_service: WorkspaceService instance (read-only usage).
    """

    def __init__(self, workspace_service: "WorkspaceService") -> None:
        self._ws_service = workspace_service

    def generate(self, workspace_id: str | None = None) -> list[SuggestionItem]:
        """Generate suggestions for one workspace or all workspaces.

        Args:
            workspace_id: If provided, scan only this workspace.
                          If None, scan all workspaces.

        Returns:
            List of SuggestionItem objects, sorted by priority (high first).
        """
        if workspace_id:
            workspaces = [self._ws_service.get_by_id(workspace_id)]
            workspaces = [w for w in workspaces if w]
        else:
            workspaces = self._ws_service.list_all()

        suggestions: list[SuggestionItem] = []
        for ws in workspaces:
            suggestions.extend(self._scan_workspace(ws))

        # Sort: high → medium → low
        priority_order = {"high": 0, "medium": 1, "low": 2}
        suggestions.sort(key=lambda s: priority_order.get(s.priority, 99))

        logger.debug(
            "SuggestionEngine: generated %d suggestions across %d workspace(s)",
            len(suggestions), len(workspaces)
        )
        return suggestions

    # ── Per-workspace scanners ─────────────────────────────────────────────────

    def _scan_workspace(self, ws: "Workspace") -> list[SuggestionItem]:
        suggestions: list[SuggestionItem] = []
        suggestions.extend(self._check_stale_tasks(ws))
        suggestions.extend(self._check_overdue_tasks(ws))
        suggestions.extend(self._check_unfinished_ideas(ws))
        suggestions.extend(self._check_goals_without_tasks(ws))
        suggestions.extend(self._check_tasks_ready_to_unblock(ws))
        suggestions.extend(self._check_repeated_entity_mentions(ws))
        return suggestions

    def _check_stale_tasks(self, ws: "Workspace") -> list[SuggestionItem]:
        """Tasks not updated in STALE_DAYS days."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=STALE_DAYS)
        results = []
        for task in ws.get_tasks():
            if not TaskStatus(task.status).is_active():
                continue
            try:
                updated = datetime.fromisoformat(task.updated_at)
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                if updated < cutoff:
                    days_stale = (datetime.now(timezone.utc) - updated).days
                    results.append(SuggestionItem.new(
                        type="stale_work",
                        priority="medium" if days_stale < 10 else "high",
                        message=(
                            f"Task '{task.title}' in '{ws.name}' hasn't been updated "
                            f"in {days_stale} days."
                        ),
                        action_hint="Update task status or mark as done/cancelled",
                        workspace_id=ws.id,
                        workspace_name=ws.name,
                        entity_refs=task.entity_refs,
                        metadata={
                            "task_id": task.id,
                            "task_title": task.title,
                            "days_stale": days_stale,
                        },
                    ))
            except Exception:
                continue
        return results

    def _check_overdue_tasks(self, ws: "Workspace") -> list[SuggestionItem]:
        """Tasks past their due_date."""
        results = []
        for task in ws.get_overdue_tasks():
            days_overdue = 0
            try:
                due = datetime.fromisoformat(task.due_date)
                if due.tzinfo is None:
                    due = due.replace(tzinfo=timezone.utc)
                days_overdue = (datetime.now(timezone.utc) - due).days
            except Exception:
                pass

            results.append(SuggestionItem.new(
                type="overdue",
                priority="high",
                message=(
                    f"Task '{task.title}' in '{ws.name}' is {days_overdue} day(s) overdue."
                ),
                action_hint="Reschedule or complete this task",
                workspace_id=ws.id,
                workspace_name=ws.name,
                entity_refs=task.entity_refs,
                metadata={
                    "task_id": task.id,
                    "task_title": task.title,
                    "due_date": task.due_date,
                    "days_overdue": days_overdue,
                },
            ))
        return results

    def _check_unfinished_ideas(self, ws: "Workspace") -> list[SuggestionItem]:
        """Idea notes older than IDEA_STALE_DAYS with no linked task."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=IDEA_STALE_DAYS)
        all_task_ids = {t.id for t in ws.get_tasks()}
        results = []

        for note in ws.get_notes():
            if note.note_type != NoteType.IDEA:
                continue
            try:
                created = datetime.fromisoformat(note.created_at)
                if created.tzinfo is None:
                    created = created.replace(tzinfo=timezone.utc)
                if created >= cutoff:
                    continue
                days_old = (datetime.now(timezone.utc) - created).days
                results.append(SuggestionItem.new(
                    type="unfinished_idea",
                    priority="low",
                    message=(
                        f"Idea in '{ws.name}' from {days_old} days ago hasn't been actioned: "
                        f"'{note.preview(60)}'"
                    ),
                    action_hint="Convert this idea into a task or archive it",
                    workspace_id=ws.id,
                    workspace_name=ws.name,
                    entity_refs=note.entity_refs,
                    metadata={
                        "note_id": note.id,
                        "note_preview": note.preview(80),
                        "days_old": days_old,
                    },
                ))
            except Exception:
                continue
        return results

    def _check_goals_without_tasks(self, ws: "Workspace") -> list[SuggestionItem]:
        """Workspaces with goals but zero tasks."""
        if not ws.goals:
            return []
        active_tasks = ws.get_active_tasks()
        if active_tasks:
            return []
        return [SuggestionItem.new(
            type="goals_without_tasks",
            priority="medium",
            message=(
                f"Workspace '{ws.name}' has {len(ws.goals)} goal(s) but no active tasks."
            ),
            action_hint="Create tasks to make progress on your goals",
            workspace_id=ws.id,
            workspace_name=ws.name,
            metadata={"goal_count": len(ws.goals), "goals": ws.goals[:3]},
        )]

    def _check_tasks_ready_to_unblock(self, ws: "Workspace") -> list[SuggestionItem]:
        """Blocked tasks whose all dependencies are now DONE."""
        all_tasks = {t.id: t for t in ws.get_tasks()}
        results = []

        for task in ws.get_blocked_tasks():
            if not task.depends_on:
                continue
            all_deps_done = all(
                all_tasks.get(dep_id, None) is not None
                and all_tasks[dep_id].status == TaskStatus.DONE
                for dep_id in task.depends_on
            )
            if all_deps_done:
                results.append(SuggestionItem.new(
                    type="tasks_ready_to_unblock",
                    priority="high",
                    message=(
                        f"Task '{task.title}' in '{ws.name}' is blocked but all its "
                        f"dependencies are done — it can be started now."
                    ),
                    action_hint="Mark task as In Progress",
                    workspace_id=ws.id,
                    workspace_name=ws.name,
                    entity_refs=task.entity_refs,
                    metadata={"task_id": task.id, "task_title": task.title},
                ))
        return results

    def _check_repeated_entity_mentions(self, ws: "Workspace") -> list[SuggestionItem]:
        """Same entity mentioned in REPEATED_MENTION_N+ notes without a task linked to them."""
        notes = ws.get_notes()
        entity_note_count: dict[str, int] = {}
        entity_task_ids: dict[str, set] = {}

        for note in notes:
            for eid in note.entity_refs:
                entity_note_count[eid] = entity_note_count.get(eid, 0) + 1

        for task in ws.get_tasks():
            for eid in task.entity_refs:
                entity_task_ids.setdefault(eid, set()).add(task.id)

        results = []
        for entity_id, count in entity_note_count.items():
            if count >= REPEATED_MENTION_N and not entity_task_ids.get(entity_id):
                results.append(SuggestionItem.new(
                    type="repeated_mention",
                    priority="medium",
                    message=(
                        f"An entity is mentioned {count} times in notes in '{ws.name}' "
                        f"but has no tasks linked to it."
                    ),
                    action_hint="Create a task or action item for this entity",
                    workspace_id=ws.id,
                    workspace_name=ws.name,
                    entity_refs=[entity_id],
                    metadata={
                        "entity_id": entity_id,
                        "mention_count": count,
                    },
                ))
        return results
