"""Intent Router — selects the Agent responsible for executing a plan.

Reads from AgentRegistry. Reads from BrainState (selected_agent for continuity).
Writes selected agent back to BrainState.

Design rules (from Brain Contract v1):
- Reads from: AgentRegistry, BrainState
- Writes to: BrainState (selected_agent only)
- Never calls LLM, never makes network requests
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.pipeline.intent_classifier import IntentResult
    from jatayu.pipeline.planner import ExecutionPlan
    from jatayu.core.agents import AgentInfo, AgentRegistry
    from jatayu.pipeline.brain_state import BrainStateService

logger = logging.getLogger(__name__)


# ── Routing table ──────────────────────────────────────────────────────────────
# Maps intent → preferred agent name.
# The Agent Registry provides the actual AgentInfo with model preferences.

INTENT_AGENT_MAP: dict[str, str] = {
    "email":            "gemini",
    "calendar":         "gemini",
    "reminder":         "gemini",
    "memory":           "gemini",
    "search":           "gemini",
    "research":         "gemini",
    "document":         "gemini",
    "spreadsheet":      "gemini",
    "meeting":          "gemini",
    "creative_writing": "gemini",
    "social_media":     "gemini",
    "task_management":  "gemini",
    "conversation":     "gemini",
    "image":            "gemini",
    "voice":            "gemini",
    "coding":           "hermes",      # Hermes for all coding tasks
    "automation":       "openclaw",    # OpenClaw for automation
    "unknown":          "gemini",      # Safe default
}


class IntentRouter:
    """Selects the Agent responsible for handling a plan.

    Args:
        agent_registry: AgentRegistry instance.
        brain_state:    BrainStateService for recording selection.
    """

    def __init__(
        self,
        agent_registry: "AgentRegistry",
        brain_state: "BrainStateService | None" = None,
    ) -> None:
        self._registry = agent_registry
        self._brain_state = brain_state

    def route(
        self,
        intent: "IntentResult",
        plan: "ExecutionPlan",
        session_id: str = "",
    ) -> "AgentInfo":
        """Select the best agent for the given intent and plan.

        Priority:
        1. Plan's agent_hint (Planner may have a strong preference)
        2. INTENT_AGENT_MAP (config-driven)
        3. AgentRegistry.get_by_capability() (capability-based fallback)
        4. Gemini (universal safe default)

        Args:
            intent:     Classified intent.
            plan:       Generated execution plan (may carry agent_hint).
            session_id: Current session (for BrainState recording).

        Returns:
            AgentInfo for the selected agent.
        """
        # ── 1. Planner hint takes priority ─────────────────────────────────
        agent_name = plan.agent_hint

        # ── 2. Fall back to routing table ──────────────────────────────────
        if not agent_name:
            agent_name = INTENT_AGENT_MAP.get(intent.intent, "gemini")

        # ── 3. Look up agent record ────────────────────────────────────────
        agent = self._registry.get(agent_name)

        # ── 4. If agent is unavailable, fall back to gemini ────────────────
        if agent is None:
            logger.warning(
                "IntentRouter: agent '%s' not in registry — falling back to gemini",
                agent_name,
            )
            agent = self._registry.get("gemini")

        elif agent.status == "disconnected" and agent_name != "gemini":
            logger.info(
                "IntentRouter: agent '%s' is disconnected — falling back to gemini",
                agent_name,
            )
            agent = self._registry.get("gemini")

        # ── 5. Final safety net ────────────────────────────────────────────
        if agent is None:
            # This should never happen since gemini is always registered,
            # but create a minimal AgentInfo just in case
            from jatayu.core.agents import AgentInfo
            agent = AgentInfo(
                name="gemini",
                display_name="Gemini Core (fallback)",
                purpose="Fallback reasoning",
                capabilities=["conversation"],
                status="connected",
                version="unknown",
                url="via SDK",
                auth_type="api_key",
                health_endpoint="",
            )

        # ── 6. Record selection in BrainState ──────────────────────────────
        if self._brain_state and session_id:
            self._brain_state.set_active_agent(session_id, agent.name)

        logger.info(
            "IntentRouter: intent=%s → agent=%s (status=%s model=%s)",
            intent.intent,
            agent.name,
            agent.status,
            agent.preferred_model,
        )

        return agent
