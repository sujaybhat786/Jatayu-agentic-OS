"""Workflow Runner — executes defined workflows via the ToolRegistry.

Steps are resolved from capabilities and dispatched through ToolRegistry.execute()
so the runner has no direct dependency on any specific tool implementation.

Condition evaluation uses a safe key-value comparator instead of eval() to
eliminate arbitrary code execution risk.
"""

from __future__ import annotations

import logging
import operator
from typing import TYPE_CHECKING, Any

from jatayu.workflows import Workflow, ExecutionState

if TYPE_CHECKING:
    from jatayu.core.capabilities import CapabilityRegistry
    from jatayu.tools import ToolRegistry

logger = logging.getLogger(__name__)


# ── Safe condition evaluator ──────────────────────────────────────────────────
# Replaces eval(). Supports simple "step_result.field == value" checks.
# Format: {"step_id": "step1", "field": "status", "op": "eq", "value": "success"}

_SAFE_OPS: dict[str, Any] = {
    "eq":  operator.eq,
    "ne":  operator.ne,
    "lt":  operator.lt,
    "le":  operator.le,
    "gt":  operator.gt,
    "ge":  operator.ge,
    "in":  lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
}


def _evaluate_condition(condition: dict, step_results: dict) -> bool:
    """Safely evaluate a step condition without using eval().

    Args:
        condition: Dict with keys: step_id, field, op, value.
                   Example: {"step_id": "step1", "field": "status", "op": "eq", "value": "success"}
        step_results: Current results from all completed steps.

    Returns:
        True if the condition passes, False otherwise.
    """
    if not isinstance(condition, dict):
        logger.warning("Invalid condition format (not a dict): %r — skipping step", condition)
        return False

    step_id = condition.get("step_id")
    field = condition.get("field", "status")
    op_name = condition.get("op", "eq")
    expected = condition.get("value")

    if step_id not in step_results:
        logger.info("Condition references unknown step '%s' — treating as False", step_id)
        return False

    step_result = step_results[step_id]
    actual = step_result.get(field) if isinstance(step_result, dict) else None

    op_fn = _SAFE_OPS.get(op_name)
    if op_fn is None:
        logger.warning("Unknown condition op '%s' — treating as False", op_name)
        return False

    try:
        return bool(op_fn(actual, expected))
    except Exception as e:
        logger.error("Condition evaluation error: %s — treating as False", e)
        return False


# ── Workflow Runner ───────────────────────────────────────────────────────────

class WorkflowRunner:
    """Executes a workflow by dispatching steps through the ToolRegistry.

    Steps reference capability names. The runner resolves them to tool names
    via CapabilityRegistry, then calls ToolRegistry.execute() — no direct
    dependency on any tool implementation.

    Args:
        capability_registry: Maps capability names → tool names.
        tool_registry:       Executes tools by name. Injected at runtime.
    """

    def __init__(
        self,
        capability_registry: CapabilityRegistry,
        tool_registry: ToolRegistry | None = None,
    ) -> None:
        self.capabilities = capability_registry
        self.tools = tool_registry

    def set_tool_registry(self, tool_registry: ToolRegistry) -> None:
        """Inject the ToolRegistry after Brain has finished building it."""
        self.tools = tool_registry

    def run(self, workflow: Workflow) -> ExecutionState:
        """Run a workflow to completion synchronously.

        Executes steps linearly in order, respecting conditions.
        Future versions will use topological sort on depends_on.

        Args:
            workflow: Workflow definition with ordered steps.

        Returns:
            ExecutionState with results for each step.
        """
        state = ExecutionState(workflow_id=workflow.id, status="running")

        if self.tools is None:
            logger.error(
                "WorkflowRunner has no ToolRegistry — "
                "call set_tool_registry() before running workflows"
            )
            state.status = "failed"
            state.error = "No ToolRegistry configured"
            return state

        try:
            for step in workflow.steps:
                state.current_step = step.id

                # ── Condition check ──────────────────────────────────────
                if step.condition:
                    if not _evaluate_condition(step.condition, state.step_results):
                        logger.info("Skipping step '%s' (condition false)", step.id)
                        state.step_results[step.id] = {"status": "skipped"}
                        continue

                # ── Resolve capability → tool name ───────────────────────
                tool_name = self.capabilities.resolve(step.capability)
                if not tool_name:
                    raise ValueError(
                        f"Capability '{step.capability}' not found or has no tools "
                        f"(step: '{step.id}')"
                    )

                # ── Execute via ToolRegistry ─────────────────────────────
                logger.info(
                    "Running step '%s': capability=%s → tool=%s",
                    step.id, step.capability, tool_name,
                )
                try:
                    result = self.tools.execute(tool_name, step.args)
                    state.step_results[step.id] = {"status": "success", "result": result}
                    logger.info("Step '%s' completed: %.120s", step.id, result)
                except Exception as e:
                    logger.error("Step '%s' failed: %s", step.id, e)
                    state.step_results[step.id] = {"status": "error", "error": str(e)}
                    raise

            state.status = "completed"
            state.current_step = None

        except Exception as e:
            state.status = "failed"
            state.error = str(e)

        return state
