"""Request Dispatcher — the single wiring point between comms and the brain pipeline.

The Communication Layer calls ONLY this dispatcher — never brain.send()
directly. This is the single integration point that decouples messaging
from intelligence.

Phase 2 upgrade: the Future Hooks are now filled with the live pipeline:
  IntentClassifier → TaskExtractor → BrainState → ContextBuilder
  → Planner → IntentRouter → ModelRouter → Brain → ResponseBuilder
  → EventLog → ConversationService

All pipeline services are optional-injected. If any are None, the dispatcher
falls back to brain.send() unchanged — 100% backward compatible.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jatayu.brain import Brain
    from jatayu.comms.models import IncomingMessage
    from jatayu.comms.session import Session
    from jatayu.pipeline.brain_state import BrainStateService
    from jatayu.pipeline.intent_classifier import IntentClassifier
    from jatayu.pipeline.task_extractor import TaskExtractor
    from jatayu.pipeline.context_builder import ContextBuilder
    from jatayu.pipeline.planner import Planner
    from jatayu.pipeline.intent_router import IntentRouter
    from jatayu.pipeline.model_router import ModelRouter
    from jatayu.pipeline.response_builder import ResponseBuilder
    from jatayu.pipeline.event_log import EventLog

logger = logging.getLogger(__name__)


class RequestDispatcher:
    """Single entry point for all messaging requests into the Brain.

    The Communication Router hands off normalized IncomingMessage objects
    to this dispatcher. The dispatcher is responsible for:
      1. Pre-processing  — classify intent, extract task, build context
      2. Planning        — deterministic execution plan
      3. Routing         — select agent + model
      4. Execution       — call Brain (and tools via Brain's agent loop)
      5. Post-processing — extract learnable signals, persist response
      6. Return          — response string to the communication layer

    All pipeline services are optional. If any are None, the dispatcher
    uses the safe fallback path (brain.send() directly).

    The Communication Layer never needs to change when new intelligence
    capabilities are added — only this dispatcher evolves.
    """

    def __init__(
        self,
        brain: Brain,
        conv_service=None,
        # ── Pipeline services (all optional for backward compat) ──────────
        brain_state: "BrainStateService | None" = None,
        intent_classifier: "IntentClassifier | None" = None,
        task_extractor: "TaskExtractor | None" = None,
        context_builder: "ContextBuilder | None" = None,
        planner: "Planner | None" = None,
        intent_router: "IntentRouter | None" = None,
        model_router: "ModelRouter | None" = None,
        response_builder: "ResponseBuilder | None" = None,
        event_log: "EventLog | None" = None,
    ) -> None:
        self._brain = brain
        self._conv = conv_service
        # Pipeline services
        self._brain_state = brain_state
        self._classifier = intent_classifier
        self._task_extractor = task_extractor
        self._context_builder = context_builder
        self._planner = planner
        self._intent_router = intent_router
        self._model_router = model_router
        self._response_builder = response_builder
        self._event_log = event_log

        # Log pipeline mode
        pipeline_active = all([
            intent_classifier, task_extractor, brain_state,
            context_builder, planner, intent_router, model_router,
        ])
        if pipeline_active:
            logger.info("RequestDispatcher: PIPELINE MODE active")
        else:
            logger.info("RequestDispatcher: FALLBACK MODE (brain.send() direct)")

    # ── Public API ─────────────────────────────────────────────────────────────

    async def dispatch(
        self,
        message: "IncomingMessage",
        session: "Session",
    ) -> str:
        """Process an incoming message and return a response string.

        Args:
            message: Normalized incoming message (text populated, voice transcribed).
            session: Active conversation session.

        Returns:
            Response text to send back to the user.
        """
        if not message.text or not message.text.strip():
            return "I received your message but couldn't extract any text."

        user_text = message.text.strip()
        session_id = session.session_id

        # ── 1. Conversation persistence (always, regardless of pipeline) ───
        conv_id = await self._ensure_conversation(session, message, user_text)

        # ── 2. Choose path: full pipeline or legacy fallback ────────────────
        pipeline_ready = bool(
            self._classifier and self._task_extractor and self._brain_state
            and self._context_builder and self._planner
            and self._intent_router and self._model_router
        )

        if pipeline_ready:
            response = await self._pipeline_dispatch(user_text, session_id, conv_id, message.source)
        else:
            response = await self._fallback_dispatch(user_text)

        # ── 3. Persist response ────────────────────────────────────────────
        if not response:
            response = "I processed your request but didn't get a response. Please try again."

        await self._persist_response(conv_id, response, message.source)

        # ── 4. Post-pipeline: BrainState workspace update ─────────────────
        if self._brain_state:
            try:
                self._brain_state.set_phase(session_id, "idle")
            except Exception:
                pass

        return response

    # ── Pipeline path ──────────────────────────────────────────────────────────

    async def _pipeline_dispatch(
        self, user_text: str, session_id: str, conv_id: str | None, source: str
    ) -> str:
        """Full pipeline: classify → extract → build context → plan → route → execute."""
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._run_pipeline_sync(user_text, session_id, conv_id, source),
            )
        except Exception as exc:
            logger.error("Pipeline dispatch failed: %s — falling back to brain.send()", exc)
            return await self._fallback_dispatch(user_text)

    def _run_pipeline_sync(
        self, user_text: str, session_id: str, conv_id: str | None, source: str
    ) -> str:
        """Synchronous pipeline execution (runs in thread executor)."""

        # ── Phase: Classifying ─────────────────────────────────────────────
        self._brain_state.set_phase(session_id, "classifying")
        snapshot = self._brain_state.get_snapshot(session_id)
        intent = self._classifier.classify(user_text, snapshot)

        self._emit("intent.classified", {
            "intent": intent.intent,
            "confidence": intent.confidence,
            "sub_intent": intent.sub_intent,
        }, session_id)

        # ── Phase: Task extraction ─────────────────────────────────────────
        task = self._task_extractor.extract(user_text, intent, snapshot)

        self._emit("task.extracted", {
            "goal": task.goal,
            "entity_count": len(task.entities),
            "deadline": task.deadline,
        }, session_id)

        # ── Update BrainState with current task ────────────────────────────
        self._brain_state.update_workspace(session_id, current_task=task.goal)
        if conv_id:
            self._brain_state.set_active_conversation(session_id, conv_id)

        # Refresh snapshot after workspace update
        snapshot = self._brain_state.get_snapshot(session_id)

        # ── Phase: Planning ────────────────────────────────────────────────
        self._brain_state.set_phase(session_id, "planning")
        context = self._context_builder.build(intent, task, snapshot, conv_id)
        plan = self._planner.plan(intent, task, context)

        self._emit("plan.generated", {
            "plan_id": plan.plan_id,
            "intent": plan.intent,
            "steps": len(plan.steps),
            "fallback": plan.fallback_to_agent_loop,
        }, session_id)

        # ── Phase: Agent + Model routing ───────────────────────────────────
        agent = self._intent_router.route(intent, plan, session_id)
        model_config = self._model_router.select(agent, intent, session_id)

        self._emit("agent.selected", {"agent": agent.name if agent else "gemini"}, session_id)
        self._emit("model.selected", {"model": model_config.model}, session_id)

        # ── Phase: Execution ───────────────────────────────────────────────
        self._brain_state.set_phase(session_id, "executing")

        # Update Brain's model if it differs from current
        if model_config.model != self._brain.model:
            logger.info(
                "ModelRouter: switching model %s → %s",
                self._brain.model, model_config.model
            )
            self._brain.model = model_config.model

        # Inject filtered tools into Brain for this call
        filtered_tools = context.tools_to_expose
        original_tool_filter = getattr(self._brain, "_active_tool_filter", None)

        if filtered_tools is not None:
            # None means "all tools" (unknown intent fallback)
            self._brain._active_tool_filter = set(filtered_tools)
        else:
            self._brain._active_tool_filter = None

        raw_response = self._brain.send(user_text)

        # Restore tool filter
        self._brain._active_tool_filter = original_tool_filter

        # ── Phase: Response processing ─────────────────────────────────────
        self._brain_state.set_phase(session_id, "responding")

        if self._response_builder:
            processed = self._response_builder.process(
                raw_response=raw_response,
                conversation_text=user_text,
                intent=intent,
                task=task,
                workspace=snapshot.workspace,
            )

            # Apply workspace updates suggested by ResponseBuilder
            if processed.workspace_updates:
                safe_updates = {
                    k: v for k, v in processed.workspace_updates.items()
                    if not k.startswith("touch_entity_")
                }
                if safe_updates:
                    self._brain_state.update_workspace(session_id, **safe_updates)

            self._emit("response.generated", {
                "intent": intent.intent,
                "entity_candidates": len(processed.entity_candidates),
                "fact_candidates": len(processed.fact_candidates),
            }, session_id)

            return processed.text

        return raw_response

    # ── Fallback path ──────────────────────────────────────────────────────────

    async def _fallback_dispatch(self, user_text: str) -> str:
        """Legacy path: brain.send() directly (current behavior)."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None,
                lambda: self._brain.send(user_text),
            )
        except Exception as exc:
            logger.error("Brain dispatch failed: %s", exc)
            return f"⚠️ I encountered an error processing your request: {exc}"

    # ── Conversation helpers ───────────────────────────────────────────────────

    async def _ensure_conversation(
        self,
        session: "Session",
        message: "IncomingMessage",
        user_text: str,
    ) -> str | None:
        """Ensure a conversation record exists and log the user message."""
        if not self._conv:
            return None

        conv_id = session.context.get("conversation_id")
        if not conv_id:
            conv_id = self._conv.create_conversation(
                session_id=session.session_id,
                provider=message.source
            )
            session.context["conversation_id"] = conv_id

        try:
            self._conv.append_message(
                conversation_id=conv_id,
                role="user",
                content=user_text,
                provider=message.source,
            )
        except Exception as exc:
            logger.error("Failed to log user message: %s", exc)

        return conv_id

    async def _persist_response(
        self, conv_id: str | None, response: str, source: str
    ) -> None:
        """Persist the assistant response to conversation history."""
        if not self._conv or not conv_id:
            return
        try:
            self._conv.append_message(
                conversation_id=conv_id,
                role="assistant",
                content=response,
                status="complete",
                provider=source,
            )
        except Exception as exc:
            logger.error("Failed to persist assistant response: %s", exc)

    # ── EventLog helper ────────────────────────────────────────────────────────

    def _emit(self, event_type: str, data: dict, session_id: str) -> None:
        if self._event_log:
            try:
                self._event_log.emit(
                    type=event_type,
                    data=data,
                    source="dispatcher",
                    session_id=session_id,
                )
            except Exception:
                pass
