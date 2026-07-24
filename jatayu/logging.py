"""Audit logging — plain-text trail of what the assistant did and why.

Appends to data/audit.log. Each entry is a single JSON line with a
timestamp, event type, and details. Human-readable when tailed.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from jatayu.config import get_config


def _log_path() -> Path:
    return Path(get_config()["data_dir"]) / "audit.log"


def log_event(event_type: str, details: dict | None = None) -> None:
    """Append an event to the audit log.

    Args:
        event_type: Short label — e.g. "tool_call", "confirmation",
                    "error", "startup".
        details: Optional dict of relevant data.
    """
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "event": event_type,
    }
    if details:
        entry.update(details)

    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def log_tool_call(tool_name: str, args: dict, result: str) -> None:
    """Log a tool execution."""
    log_event("tool_call", {
        "tool": tool_name,
        "args": args,
        "result": result[:500],  # cap long results
    })


def log_confirmation(tool_name: str, args: dict, approved: bool) -> None:
    """Log a confirmation gate decision."""
    log_event("confirmation", {
        "tool": tool_name,
        "args": args,
        "approved": approved,
    })


def log_error(context: str, error: str) -> None:
    """Log an error."""
    log_event("error", {
        "context": context,
        "error": str(error)[:500],
    })


def log_model_usage(model: str, input_tokens: int = 0, output_tokens: int = 0) -> None:
    """Log model usage for cost tracking."""
    log_event("model_usage", {
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
    })
