"""Planner — generates a deterministic ExecutionPlan from intent + task.

ABSOLUTE RULE: The Planner NEVER calls the LLM. NEVER makes network requests.
It maps (IntentResult, Task) → ExecutionPlan using pre-built templates.

For unknown intents or unrecognized patterns, it emits a passthrough plan
that falls through to the full Brain agent loop as a safe fallback.

Design rules (from Brain Contract v1):
- Pure template matching — no ML, no API calls, no eval().
- Reads from BrainState (workspace context only).
- Never reads from ConversationService or EntityMemory.
- Task.entities is the only entity data it sees (pre-resolved by TaskExtractor).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jatayu.pipeline.intent_classifier import IntentResult
    from jatayu.pipeline.task_extractor import Task
    from jatayu.pipeline.context_builder import ContextPacket

logger = logging.getLogger(__name__)


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class PlanStep:
    """A single executable step in a plan."""
    step_id: str
    description: str
    tool_name: str                           # exact tool name from ToolRegistry
    args: dict = field(default_factory=dict) # may contain {step_id.field} refs
    depends_on: list[str] = field(default_factory=list)
    optional: bool = False
    requires_confirmation: bool = False

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "description": self.description,
            "tool_name": self.tool_name,
            "args": self.args,
            "depends_on": self.depends_on,
            "optional": self.optional,
            "requires_confirmation": self.requires_confirmation,
        }


@dataclass
class ExecutionPlan:
    """The complete plan for executing a user request.

    If fallback_to_agent_loop=True, steps are empty and the Brain
    handles everything via its existing tool loop.
    """
    intent: str
    steps: list[PlanStep] = field(default_factory=list)
    agent_hint: str | None = None        # preferred agent name
    model_hint: str | None = None        # preferred model
    requires_confirmation: bool = False  # any step requires it
    fallback_to_agent_loop: bool = True  # True = Brain handles it (safe default)
    plan_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "intent": self.intent,
            "steps": [s.to_dict() for s in self.steps],
            "agent_hint": self.agent_hint,
            "requires_confirmation": self.requires_confirmation,
            "fallback_to_agent_loop": self.fallback_to_agent_loop,
        }


# ── Planner ────────────────────────────────────────────────────────────────────

class Planner:
    """Generates deterministic ExecutionPlans from intent + task.

    Uses pre-built templates for known intents. For unrecognized patterns,
    emits a passthrough plan (fallback_to_agent_loop=True) that preserves
    the current Brain agent loop behavior.

    NEVER calls the LLM. NEVER makes network requests.
    """

    def plan(
        self,
        intent: "IntentResult",
        task: "Task",
        context: "ContextPacket",
    ) -> ExecutionPlan:
        """Generate an ExecutionPlan for the given intent and task.

        Args:
            intent:  Classified intent.
            task:    Extracted task with entities and parameters.
            context: Assembled context packet.

        Returns:
            ExecutionPlan with steps or fallback flag.
        """
        intent_name = intent.intent
        sub_intent = intent.sub_intent

        # Route to the appropriate template
        builder = _TEMPLATE_MAP.get(intent_name)
        if builder is None:
            plan = self._fallback_plan(intent_name)
        else:
            try:
                plan = builder(self, intent, task, context)
            except Exception as exc:
                logger.warning(
                    "Planner: template for '%s' raised %s — using fallback",
                    intent_name, exc
                )
                plan = self._fallback_plan(intent_name)

        logger.info(
            "Planner: %s → %d steps fallback=%s agent=%s",
            intent_name,
            len(plan.steps),
            plan.fallback_to_agent_loop,
            plan.agent_hint,
        )

        return plan

    # ── Templates ──────────────────────────────────────────────────────────────

    def _plan_email(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Plan email actions based on sub-intent."""
        sub = intent.sub_intent or "draft"
        people = task.get_people()
        params = task.parameters
        steps = []

        if sub in ("send", "draft", "reply"):
            # Step 1: Resolve person entity if we have one
            recipient_resolved = False
            if people:
                person = people[0]
                if person.resolved_id:
                    # Already resolved — use directly
                    recipient_resolved = True
                else:
                    steps.append(PlanStep(
                        step_id="resolve_recipient",
                        description=f"Look up contact: {person.raw_text}",
                        tool_name="get_person",
                        args={"name": person.raw_text},
                    ))

            # Step 2: Draft the email
            draft_args: dict = {
                "subject": params.get("subject_hint", task.goal),
            }
            if people and not recipient_resolved:
                draft_args["to"] = "{resolve_recipient.email}"
            elif people and people[0].resolved_id:
                # We have a resolved entity — the resolved_name was set
                draft_args["recipient_name"] = people[0].resolved_name

            steps.append(PlanStep(
                step_id="draft_email",
                description="Draft the email",
                tool_name="google_gmail_draft",
                args=draft_args,
                depends_on=["resolve_recipient"] if (people and not recipient_resolved) else [],
            ))

            if sub == "send":
                steps.append(PlanStep(
                    step_id="send_email",
                    description="Send the drafted email",
                    tool_name="google_gmail_send",
                    args={"draft_id": "{draft_email.draft_id}"},
                    depends_on=["draft_email"],
                    requires_confirmation=True,
                ))

            return ExecutionPlan(
                intent="email",
                steps=steps,
                agent_hint="gemini",
                requires_confirmation=sub == "send",
                fallback_to_agent_loop=False,
            )

        elif sub == "read":
            return ExecutionPlan(
                intent="email",
                steps=[PlanStep(
                    step_id="read_email",
                    description="Read recent emails",
                    tool_name="google_gmail_read",
                    args={"max_results": 5},
                )],
                agent_hint="gemini",
                fallback_to_agent_loop=False,
            )

        # Unknown email sub-intent → fallback
        return self._fallback_plan("email")

    def _plan_calendar(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Plan calendar actions."""
        sub = intent.sub_intent or "read"
        params = task.parameters

        if sub == "read":
            return ExecutionPlan(
                intent="calendar",
                steps=[PlanStep(
                    step_id="read_calendar",
                    description="Check calendar",
                    tool_name="google_calendar_read",
                    args={},
                )],
                agent_hint="gemini",
                fallback_to_agent_loop=False,
            )

        elif sub == "create":
            steps = [PlanStep(
                step_id="create_event",
                description="Create calendar event",
                tool_name="google_calendar_create",
                args={
                    "title": params.get("title_hint", task.goal),
                    "duration": params.get("duration", "1 hour"),
                    "date": task.deadline or "today",
                },
                requires_confirmation=True,
            )]
            return ExecutionPlan(
                intent="calendar",
                steps=steps,
                agent_hint="gemini",
                requires_confirmation=True,
                fallback_to_agent_loop=False,
            )

        return self._fallback_plan("calendar")

    def _plan_reminder(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Plan reminder actions."""
        sub = intent.sub_intent or "set"
        params = task.parameters

        if sub == "set":
            return ExecutionPlan(
                intent="reminder",
                steps=[PlanStep(
                    step_id="set_reminder",
                    description="Set reminder",
                    tool_name="set_reminder",
                    args={
                        "text": params.get("reminder_text", task.goal),
                        "when": task.deadline or "in 1 hour",
                    },
                )],
                agent_hint="gemini",
                fallback_to_agent_loop=False,
            )

        elif sub == "list":
            return ExecutionPlan(
                intent="reminder",
                steps=[PlanStep(
                    step_id="list_reminders",
                    description="List all reminders",
                    tool_name="list_reminders",
                    args={},
                )],
                agent_hint="gemini",
                fallback_to_agent_loop=False,
            )

        return self._fallback_plan("reminder")

    def _plan_memory(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Plan memory operations."""
        sub = intent.sub_intent or "store"

        if sub == "store":
            return ExecutionPlan(
                intent="memory",
                steps=[PlanStep(
                    step_id="remember",
                    description="Store fact in memory",
                    tool_name="remember",
                    args={"fact": task.goal, "category": "user_stated"},
                )],
                agent_hint="gemini",
                fallback_to_agent_loop=False,
            )

        # retrieve / delete → fallback (Brain handles these via tool loop)
        return self._fallback_plan("memory")

    def _plan_search(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Plan knowledge search."""
        return ExecutionPlan(
            intent="search",
            steps=[PlanStep(
                step_id="knowledge_search",
                description="Search organizational knowledge",
                tool_name="knowledge_search",
                args={"query": intent.raw_text},
            )],
            agent_hint="gemini",
            fallback_to_agent_loop=False,
        )

    def _plan_task_management(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Plan task management actions."""
        sub = intent.sub_intent or "list"

        if sub == "add":
            return ExecutionPlan(
                intent="task_management",
                steps=[PlanStep(
                    step_id="add_task",
                    description="Add task",
                    tool_name="add_task",
                    args={"task": task.goal, "due": task.deadline},
                )],
                agent_hint="gemini",
                fallback_to_agent_loop=False,
            )

        return self._fallback_plan("task_management")

    def _plan_coding(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Coding tasks route to Hermes agent."""
        return ExecutionPlan(
            intent="coding",
            steps=[],  # Hermes handles the full loop itself
            agent_hint="hermes",
            fallback_to_agent_loop=True,  # Hermes uses its own agentic loop
        )

    def _plan_automation(
        self, intent: "IntentResult", task: "Task", ctx: "ContextPacket"
    ) -> ExecutionPlan:
        """Automation tasks route to OpenClaw agent."""
        return ExecutionPlan(
            intent="automation",
            steps=[],
            agent_hint="openclaw",
            fallback_to_agent_loop=True,  # OpenClaw uses its own loop
        )

    def _fallback_plan(self, intent_name: str) -> ExecutionPlan:
        """Generate a safe passthrough plan for unknown/unhandled intents.

        The fallback plan has no steps and sets fallback_to_agent_loop=True,
        which tells the Dispatcher to let Brain handle it via the existing
        Gemini tool loop — exactly the current behavior.
        """
        return ExecutionPlan(
            intent=intent_name,
            steps=[],
            agent_hint="gemini",
            fallback_to_agent_loop=True,
        )


# ── Template dispatch map ──────────────────────────────────────────────────────
# Maps intent name → bound method on Planner.
# New templates: add method + entry here. No other changes needed.

_TEMPLATE_MAP: dict[str, Any] = {
    "email":           Planner._plan_email,
    "calendar":        Planner._plan_calendar,
    "reminder":        Planner._plan_reminder,
    "memory":          Planner._plan_memory,
    "search":          Planner._plan_search,
    "task_management": Planner._plan_task_management,
    "coding":          Planner._plan_coding,
    "automation":      Planner._plan_automation,
    # These all fall through to the Brain's agent loop for now
    # (they get their context filtered by ContextBuilder, which is the main win)
    "conversation":    None,
    "research":        None,
    "creative_writing":None,
    "document":        None,
    "spreadsheet":     None,
    "meeting":         None,
    "social_media":    None,
    "image":           None,
    "voice":           None,
    "unknown":         None,
}
