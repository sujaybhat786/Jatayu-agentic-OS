"""Workflow Engine — orchestrates multi-step processes across agents and capabilities."""

from dataclasses import dataclass, field
from typing import Any, Literal

@dataclass
class WorkflowStep:
    """A single step in a workflow."""
    id: str
    capability: str                 # The registered capability to execute (e.g. 'draft_email')
    args: dict[str, Any]            # Arguments to pass to the capability
    depends_on: list[str] = field(default_factory=list)  # IDs of steps that must complete first
    condition: str | None = None    # Optional python eval string (e.g. "results['step1'].status == 'success'")

@dataclass
class Workflow:
    """A defined workflow."""
    id: str
    name: str
    description: str
    steps: list[WorkflowStep]

@dataclass
class ExecutionState:
    """State of a running workflow."""
    workflow_id: str
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    step_results: dict[str, Any] = field(default_factory=dict)
    current_step: str | None = None
    error: str | None = None
