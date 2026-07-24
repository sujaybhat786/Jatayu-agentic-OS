"""DailyBriefAggregator — builds a structured Morning Brief.

Aggregates all workspace health, tasks, suggestions, and entity data
into a single DailyBrief structure. Returns pure data — NO formatting.
The Dashboard renders it.

Design rules:
- Read-only. Never writes to any store.
- No LLM calls. No network requests.
- Called on demand from the /api/daily-brief endpoint.
- Calendar integration is a placeholder (formatted as a note field)
  until Google Calendar real-time data is cached separately.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from jatayu.workspace.models import (
    DailyBrief,
    WorkspaceBriefItem,
    WorkspaceHealth,
    _now,
)
from jatayu.workspace.health import WorkspaceHealthCalculator
from jatayu.workspace.suggestions import SuggestionEngine

if TYPE_CHECKING:
    from jatayu.workspace.service import WorkspaceService

logger = logging.getLogger(__name__)

# ── Thresholds ─────────────────────────────────────────────────────────────────
HEALTH_ALERT_THRESHOLD = 40.0   # workspaces below this score get a health alert
RECENT_NOTE_DAYS       = 3      # include notes from last N days in brief
UPCOMING_TASK_DAYS     = 7      # tasks due within N days = "upcoming"


class DailyBriefAggregator:
    """Builds a structured Morning Brief from all workspace data.

    Args:
        workspace_service: WorkspaceService instance.
    """

    def __init__(self, workspace_service: "WorkspaceService", proactive_engine=None) -> None:
        self._ws_service = workspace_service
        self._health_calc = WorkspaceHealthCalculator()
        self._suggestion_engine = SuggestionEngine(workspace_service)
        self._proactive_engine = proactive_engine

    def generate(self) -> DailyBrief:
        """Build and return a DailyBrief for today.

        Returns:
            DailyBrief with workspace summaries, tasks, suggestions, health alerts.
        """
        workspaces = self._ws_service.list_all()
        now = datetime.now(timezone.utc)
        today_str = now.date().isoformat()
        week_end = (now + timedelta(days=UPCOMING_TASK_DAYS)).date().isoformat()

        workspace_summaries: list[WorkspaceBriefItem] = []
        all_tasks_today: list[dict] = []
        all_tasks_overdue: list[dict] = []
        all_tasks_upcoming: list[dict] = []
        health_alerts: list[dict] = []
        total_active = 0

        for ws in workspaces:
            health = self._health_calc.compute(ws)
            tasks_today = [t.to_dict() for t in ws.get_tasks_due_today()]
            overdue = [t.to_dict() for t in ws.get_overdue_tasks()]
            recent_notes = [n.to_dict() for n in ws.get_recent_notes(days=RECENT_NOTE_DAYS)]

            # Upcoming (not today, due this week, not done)
            upcoming = []
            for t in ws.get_tasks():
                if t.due_date and t.due_date > today_str and t.due_date <= week_end:
                    if t.status not in ("done", "cancelled"):
                        upcoming.append(t.to_dict())

            # Tag each task with workspace name for global lists
            for td in tasks_today:
                td["workspace_name"] = ws.name
            for td in overdue:
                td["workspace_name"] = ws.name
            for td in upcoming:
                td["workspace_name"] = ws.name

            all_tasks_today.extend(tasks_today)
            all_tasks_overdue.extend(overdue)
            all_tasks_upcoming.extend(upcoming)
            total_active += len(ws.get_active_tasks())

            # Health alerts
            if health.health_score < HEALTH_ALERT_THRESHOLD:
                health_alerts.append({
                    "workspace_id": ws.id,
                    "workspace_name": ws.name,
                    "health_score": health.health_score,
                    "health_status": health.health_status,
                    "overdue_count": health.overdue_count,
                    "days_since_activity": health.days_since_activity,
                })

            workspace_summaries.append(WorkspaceBriefItem(
                workspace_id=ws.id,
                workspace_name=ws.name,
                health=health,
                tasks_due_today=tasks_today,
                overdue_tasks=overdue,
                recent_notes=recent_notes[:5],  # Limit to 5 per workspace
            ))

        # Sort workspace summaries: worst health first (needs most attention)
        workspace_summaries.sort(key=lambda w: w.health.health_score)

        # Sort global task lists by priority
        all_tasks_overdue.sort(key=lambda t: t.get("priority", 3))
        all_tasks_today.sort(key=lambda t: t.get("priority", 3))
        all_tasks_upcoming.sort(
            key=lambda t: (t.get("due_date") or "9999", t.get("priority", 3))
        )

        # Suggestions
        suggestions = self._suggestion_engine.generate()
        suggestion_dicts = [s.to_dict() for s in suggestions[:20]]  # Top 20

        # Recent entities (last updated)
        recent_entities = self._get_recent_entities()

        brief = DailyBrief(
            generated_at=_now(),
            workspace_summaries=workspace_summaries,
            tasks_due_today=all_tasks_today,
            tasks_overdue=all_tasks_overdue,
            upcoming_tasks=all_tasks_upcoming[:20],
            health_alerts=health_alerts,
            suggestions=suggestion_dicts,
            recent_entities=recent_entities,
            total_workspaces=len(workspaces),
            total_active_tasks=total_active,
            meetings_today=[],  # To be populated from calendar integration later
            blocked_workspaces=[],  # Could be pulled from workspace status if added
            high_priority_observations=self._get_high_priority_observations(),
            recent_memory_updates=recent_entities,
            people_awaiting_response=[],  # Placeholder for email/comms integrations
            suggested_first_task=self._get_suggested_first_task(all_tasks_overdue, all_tasks_today)
        )

        logger.info(
            "DailyBrief: %d workspaces, %d tasks today, %d overdue, %d suggestions",
            len(workspaces),
            len(all_tasks_today),
            len(all_tasks_overdue),
            len(suggestions),
        )

        return brief

    def _get_recent_entities(self) -> list[dict]:
        """Return recently updated entity records for the brief."""
        try:
            from jatayu.memory.entities import list_entities
            entities = list_entities()
            # Sort by updated_at descending, return top 10
            entities_sorted = sorted(
                entities,
                key=lambda e: e.get("updated_at", ""),
                reverse=True,
            )
            return entities_sorted[:10]
        except Exception as e:
            logger.error("Failed to load recent entities for daily brief: %s", e)
            return []

    def _get_high_priority_observations(self) -> list[dict]:
        if not self._proactive_engine:
            return []
        
        self._proactive_engine.evaluate_all()
        observations = self._proactive_engine.get_all()
        # Include CRITICAL, HIGH, and MEDIUM for the brief
        return [o.to_dict() for o in observations if o.priority in ("CRITICAL", "HIGH", "MEDIUM")]

    def _get_suggested_first_task(self, overdue: list[dict], today: list[dict]) -> dict | None:
        all_candidates = overdue + today
        if not all_candidates:
            return None
        # Sort by priority, then by due date
        all_candidates.sort(key=lambda t: (t.get("priority", 3), t.get("due_date", "9999")))
        return all_candidates[0]
