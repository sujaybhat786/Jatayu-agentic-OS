"""WorkspaceHealthCalculator — pure computation, zero I/O.

Formula (Brain Contract v1 design spec):
    health_score = (
        40% * completion_score       # done tasks / total tasks
      + 30% * recency_score          # activity in last 7 days
      + 20% * unblocked_ratio        # (active - blocked) / active
      + 10% * goals_bonus            # 10 if goals exist, 0 if not
    ) * 100

Clamped to [0, 100]. Returns WorkspaceHealth with status label.

Status thresholds:
    ≥ 70  → healthy
    ≥ 45  → at_risk
    ≥ 20  → stale
    < 20  → critical
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from jatayu.workspace.models import Workspace, WorkspaceHealth, TaskStatus, _now

if TYPE_CHECKING:
    pass


# ── Weights ────────────────────────────────────────────────────────────────────
WEIGHT_COMPLETION = 0.40
WEIGHT_RECENCY    = 0.30
WEIGHT_UNBLOCKED  = 0.20
WEIGHT_GOALS      = 0.10

# ── Status thresholds ──────────────────────────────────────────────────────────
STATUS_HEALTHY  = 70
STATUS_AT_RISK  = 45
STATUS_STALE    = 20

# ── Recency window ─────────────────────────────────────────────────────────────
RECENT_DAYS = 7


class WorkspaceHealthCalculator:
    """Computes a WorkspaceHealth snapshot for a given Workspace.

    Pure function — no I/O, no EventLog, no external calls.
    Can be called at any time without side effects.
    """

    def compute(self, ws: Workspace) -> WorkspaceHealth:
        """Compute health for a workspace.

        Args:
            ws: Workspace instance with current tasks, timeline, and goals.

        Returns:
            WorkspaceHealth with score, status, and component metrics.
        """
        tasks = ws.get_tasks()
        total   = len(tasks)
        done    = len([t for t in tasks if t.status == TaskStatus.DONE])
        active  = len([t for t in tasks if TaskStatus(t.status).is_active()])
        blocked = len([t for t in tasks if t.status == TaskStatus.BLOCKED])
        overdue = len([t for t in tasks if t.is_overdue()])
        has_goals = len(ws.goals) > 0

        # ── 1. Completion score ─────────────────────────────────────────────
        if total == 0:
            completion_pct = 0.0
            completion_score = 0.5   # No tasks yet → neutral (not penalised)
        else:
            completion_pct = round(done / total * 100, 1)
            completion_score = done / total

        # ── 2. Recency score ────────────────────────────────────────────────
        recent_entries = ws.get_recent_timeline(days=RECENT_DAYS)
        recent_count = len(recent_entries)

        # Score: 0 = no activity, 1 = 10+ activities in last 7 days
        recency_score = min(recent_count / 10.0, 1.0)

        # Days since last activity
        days_since: int | None = None
        all_entries = ws.get_timeline()
        if all_entries:
            try:
                latest = all_entries[0]  # already sorted desc
                ts = datetime.fromisoformat(latest.timestamp)
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                delta = datetime.now(timezone.utc) - ts
                days_since = delta.days
                # Extra penalty: if > 14 days with no activity
                if days_since > 14:
                    recency_score = max(0.0, recency_score - 0.3)
                elif days_since > 7:
                    recency_score = max(0.0, recency_score - 0.15)
            except Exception:
                pass
        else:
            # No timeline at all → workspace is brand new, neutral score
            recency_score = 0.5

        # ── 3. Unblocked ratio ──────────────────────────────────────────────
        if active == 0:
            unblocked_ratio = 1.0  # No active tasks → not blocked
        else:
            unblocked_ratio = max(0.0, (active - blocked) / active)

        # Overdue penalty: each overdue task reduces unblocked_ratio by 5%
        if overdue > 0:
            unblocked_ratio = max(0.0, unblocked_ratio - (overdue * 0.05))

        # ── 4. Goals bonus ──────────────────────────────────────────────────
        goals_bonus = 1.0 if has_goals else 0.0

        # ── 5. Composite score ──────────────────────────────────────────────
        raw = (
            WEIGHT_COMPLETION * completion_score
            + WEIGHT_RECENCY  * recency_score
            + WEIGHT_UNBLOCKED * unblocked_ratio
            + WEIGHT_GOALS    * goals_bonus
        )
        health_score = round(min(max(raw * 100, 0.0), 100.0), 1)

        # ── 6. Status label ─────────────────────────────────────────────────
        if health_score >= STATUS_HEALTHY:
            health_status = "healthy"
        elif health_score >= STATUS_AT_RISK:
            health_status = "at_risk"
        elif health_score >= STATUS_STALE:
            health_status = "stale"
        else:
            health_status = "critical"

        return WorkspaceHealth(
            workspace_id=ws.id,
            health_score=health_score,
            health_status=health_status,
            completion_pct=completion_pct,
            total_tasks=total,
            active_tasks=active,
            overdue_count=overdue,
            blocked_count=blocked,
            recent_activity_count=recent_count,
            days_since_activity=days_since,
            has_goals=has_goals,
        )
