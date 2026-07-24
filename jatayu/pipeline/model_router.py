"""Model Router — fulfills the Agent's preferred model selection.

The Agent Registry owns model preference. ModelRouter does NOT choose
independently — it serves what the Agent requests, with config.yaml
overrides for intent-level tuning and fallback.

Design rules (from Brain Contract v1):
- Reads from: AgentInfo.preferred_model, config.yaml model_routing table, BrainState
- Writes to: BrainState (current_model)
- Never calls the LLM
- Never makes network requests
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from jatayu.config import get_config

if TYPE_CHECKING:
    from jatayu.pipeline.intent_classifier import IntentResult
    from jatayu.core.agents import AgentInfo
    from jatayu.pipeline.brain_state import BrainStateService

logger = logging.getLogger(__name__)


@dataclass
class ModelConfig:
    """The fully resolved model configuration for one LLM call."""
    model: str
    provider: str          # "gemini" | "anthropic" | "ollama"
    temperature: float = 1.0
    max_tokens: int | None = None
    api_key_env: str | None = None

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }


class ModelRouter:
    """Resolves the model to use for a given agent + intent combination.

    Priority order:
        1. Agent's preferred_model (Agent Registry owns model preference)
        2. config.yaml model_routing[intent] (intent-level override)
        3. config.yaml providers.gemini.default_model (provider default)
        4. config.yaml model (top-level fallback — the existing key)

    The ModelRouter also records the selected model in BrainState
    so the dashboard can display what model is active.

    Args:
        brain_state: Optional BrainStateService for state recording.
    """

    def __init__(self, brain_state: "BrainStateService | None" = None) -> None:
        self._brain_state = brain_state
        self._config = get_config()
        self._model_routing: dict = self._config.get("model_routing", {})
        self._providers: dict = self._config.get("providers", {})

    def select(
        self,
        agent: "AgentInfo",
        intent: "IntentResult",
        session_id: str = "",
    ) -> ModelConfig:
        """Select the best model for this agent + intent combination.

        Args:
            agent:      Selected AgentInfo (owns model preference).
            intent:     Classified intent (used for config overrides).
            session_id: Current session (for BrainState recording).

        Returns:
            ModelConfig with fully resolved model parameters.
        """
        # ── 1. Start with agent's preferred model ──────────────────────────
        model = agent.preferred_model if agent and hasattr(agent, "preferred_model") else None

        # ── 2. Apply intent-level config override (if set explicitly) ──────
        # Config can force a specific model for certain intents regardless of agent
        config_model = self._model_routing.get(intent.intent)
        if config_model:
            # Config override wins over agent preference
            # EXCEPTION: if agent has a stronger latency requirement, prefer flash
            if agent and "pro" in config_model and agent.latency_target_ms < 2000:
                # Latency-sensitive agent prefers flash even for pro intents
                config_model = self._model_routing.get("default", model)
            model = config_model

        # ── 3. Final fallback chain ────────────────────────────────────────
        if not model:
            model = (
                self._providers.get("gemini", {}).get("default_model")
                or self._config.get("model")
                or "gemini-3.5-flash"
            )

        # ── 4. Determine provider ──────────────────────────────────────────
        provider = self._infer_provider(model)

        # ── 5. Get temperature from provider config ────────────────────────
        temperature = self._providers.get(provider, {}).get("temperature", 1.0)

        config = ModelConfig(
            model=model,
            provider=provider,
            temperature=temperature,
        )

        # ── 6. Record in BrainState ────────────────────────────────────────
        if self._brain_state and session_id:
            self._brain_state.set_active_model(session_id, model)

        logger.info(
            "ModelRouter: agent=%s intent=%s → model=%s provider=%s",
            agent.name if agent else "gemini", intent.intent, model, provider,
        )

        return config

    def _infer_provider(self, model: str) -> str:
        """Infer the provider from the model name."""
        if model.startswith("gemini"):
            return "gemini"
        elif model.startswith("claude"):
            return "anthropic"
        elif "/" in model:
            return "ollama"  # ollama models are typically "namespace/name"
        return "gemini"  # safe default

    def get_backup_config(self, primary: ModelConfig, agent: "AgentInfo") -> ModelConfig:
        """Return a backup ModelConfig if the primary model fails.

        Uses the agent's backup_model field.
        """
        backup_model = agent.backup_model or "gemini-3.5-flash"
        if backup_model == primary.model:
            # If backup is the same as primary, use the flash model
            backup_model = "gemini-3.5-flash"

        return ModelConfig(
            model=backup_model,
            provider=self._infer_provider(backup_model),
            temperature=primary.temperature,
        )
