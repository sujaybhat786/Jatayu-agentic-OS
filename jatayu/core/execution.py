"""Standardized execution result — uniform output from all tools and agents.

Every tool execution can optionally return a structured result. This format
ensures the orchestrator can normalize outputs from any source before
presenting them to the user.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ExecutionResult:
    """Structured result from any tool or agent execution.

    Usage:
        result = ExecutionResult.success(
            summary="Created 3 tasks",
            data={"tasks": [...]},
            agent_used="jatayu",
            capability="create_task",
        )
    """

    status: str                          # "success" | "error" | "partial"
    summary: str                         # Human-readable summary
    data: Any = None                     # Raw result data
    artifacts: list[str] = field(default_factory=list)  # File paths produced
    generated_files: list[str] = field(default_factory=list) # Code files generated
    execution_time: float = 0.0          # Seconds
    agent_used: str = ""                 # Which agent executed this
    capability: str = ""                 # Which capability was invoked
    confidence: float = 1.0             # 0.0 - 1.0
    suggested_next: str = ""             # Suggested follow-up action
    logs: list[str] = field(default_factory=list)       # Execution logs
    errors: list[str] = field(default_factory=list)  # Error messages

    @classmethod
    def success(cls, summary: str, **kwargs) -> ExecutionResult:
        """Create a successful result."""
        return cls(status="success", summary=summary, **kwargs)

    @classmethod
    def error(cls, summary: str, errors: list[str] | None = None, **kwargs) -> ExecutionResult:
        """Create an error result."""
        return cls(status="error", summary=summary, errors=errors or [summary], **kwargs)

    @classmethod
    def partial(cls, summary: str, **kwargs) -> ExecutionResult:
        """Create a partial-success result."""
        return cls(status="partial", summary=summary, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "data": self.data if not callable(self.data) else str(self.data),
            "artifacts": self.artifacts,
            "generated_files": self.generated_files,
            "execution_time": round(self.execution_time, 3),
            "agent_used": self.agent_used,
            "capability": self.capability,
            "confidence": self.confidence,
            "suggested_next": self.suggested_next,
            "logs": self.logs,
            "errors": self.errors
        }

    def to_tool_string(self) -> str:
        """Convert to a string suitable for returning from a tool handler."""
        parts = [self.summary]
        if self.errors:
            parts.append(f"Errors: {'; '.join(self.errors)}")
        if self.suggested_next:
            parts.append(f"Suggested next: {self.suggested_next}")
        return "\n".join(parts)


class ExecutionTimer:
    """Context manager for timing tool/agent execution.

    Usage:
        with ExecutionTimer() as timer:
            do_work()
        print(timer.elapsed)  # seconds
    """

    def __init__(self):
        self.start_time: float = 0.0
        self.elapsed: float = 0.0

    def __enter__(self) -> ExecutionTimer:
        self.start_time = time.monotonic()
        return self

    def __exit__(self, *args) -> None:
        self.elapsed = time.monotonic() - self.start_time
