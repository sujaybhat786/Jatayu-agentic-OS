"""Proactive Intelligence Engine.

Primarily rule-based and deterministic generator of structured observations.
Uses Gemini only when genuine reasoning is required, otherwise relies on
hardcoded logic over Workspaces, Tasks, and EventLog to generate insights.
"""

import json
import logging
from pathlib import Path
from datetime import datetime, timezone, timedelta

from jatayu.config import get_config
from jatayu.intelligence.models import Observation

logger = logging.getLogger(__name__)

class ProactiveIntelligenceEngine:
    """Evaluates existing state to generate structured observations."""
    
    def __init__(self, workspace_service, event_log=None):
        self._ws_service = workspace_service
        self._event_log = event_log
        self.data_dir = Path(get_config()["data_dir"])
        self.obs_file = self.data_dir / "observations.json"
        
        self._observations: dict[str, Observation] = {}
        self._load()

    def _load(self):
        if self.obs_file.exists():
            try:
                with open(self.obs_file, "r") as f:
                    data = json.load(f)
                    self._observations = {k: Observation.from_dict(v) for k, v in data.items()}
            except Exception as e:
                logger.error("Failed to load observations: %s", e)

    def _save(self):
        self.obs_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.obs_file, "w") as f:
                json.dump({k: v.to_dict() for k, v in self._observations.items()}, f, indent=2)
        except Exception as e:
            logger.error("Failed to save observations: %s", e)

    def evaluate_all(self):
        """Run all deterministic rules to refresh observations."""
        now = datetime.now(timezone.utc)
        today_str = now.date().isoformat()
        upcoming_threshold = (now + timedelta(days=3)).date().isoformat()
        
        new_obs: dict[str, Observation] = {}
        
        workspaces = self._ws_service.list_all()
        
        for ws in workspaces:
            # 1. Overdue Tasks
            for t in ws.get_overdue_tasks():
                obs = Observation(
                    type="overdue_task",
                    priority="MEDIUM",
                    reason=f"Task '{t.title}' is overdue.",
                    suggested_action="Reschedule or complete the task.",
                    workspace_id=ws.id,
                    generated_from=["workspace.tasks"]
                )
                new_obs[obs.id] = obs
                
            # 2. Upcoming Deadlines
            for t in ws.get_active_tasks():
                if t.due_date and today_str <= t.due_date <= upcoming_threshold:
                    obs = Observation(
                        type="upcoming_deadline",
                        priority="MEDIUM",
                        reason=f"Task '{t.title}' is due on {t.due_date}.",
                        suggested_action="Prioritize this task.",
                        workspace_id=ws.id,
                        generated_from=["workspace.tasks"]
                    )
                    new_obs[obs.id] = obs
                    
            # 3. Goal without tasks
            if ws.goals and not ws.get_active_tasks():
                obs = Observation(
                    type="goal_without_tasks",
                    priority="LOW",
                    reason=f"Workspace has goals but no active tasks.",
                    suggested_action="Break down the goals into actionable tasks.",
                    workspace_id=ws.id,
                    generated_from=["workspace.goals"]
                )
                new_obs[obs.id] = obs
                
            # 4. Stale Workspace
            # Check last updated time of tasks and notes
            is_stale = False
            last_activity = ws.updated_at
            try:
                dt_last = datetime.fromisoformat(last_activity).replace(tzinfo=timezone.utc)
                if (now - dt_last).days > 7:
                    is_stale = True
            except Exception:
                pass
                
            if is_stale:
                obs = Observation(
                    type="stale_workspace",
                    priority="LOW",
                    reason="No activity in the last 7 days.",
                    suggested_action="Review and archive if completed, or schedule a check-in.",
                    workspace_id=ws.id,
                    generated_from=["workspace.timeline"]
                )
                new_obs[obs.id] = obs

        # Retain learning candidates (they are generated elsewhere or via LLM)
        for k, v in self._observations.items():
            if v.learning_candidate:
                new_obs[k] = v

        self._observations = new_obs
        self._save()

    def get_all(self) -> list[Observation]:
        """Return all current observations sorted by priority."""
        priority_map = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
        obs = list(self._observations.values())
        obs.sort(key=lambda x: priority_map.get(x.priority, 4))
        return obs
        
    def add_learning_candidate(self, reason: str, suggested_action: str, generated_from: list[str]) -> Observation:
        """Explicit method to add a learning candidate (e.g. from event log pattern analysis)."""
        obs = Observation(
            type="repeated_pattern",
            priority="LOW",
            reason=reason,
            suggested_action=suggested_action,
            generated_from=generated_from,
            learning_candidate=True
        )
        self._observations[obs.id] = obs
        self._save()
        return obs
