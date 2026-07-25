"""Audit logging — plain-text trail of what the assistant did and why.

Appends to data/audit.log. Each entry is a single JSON line with a
timestamp, event type, and details. Human-readable when tailed.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from jatayu.config import get_config


def setup_logging() -> None:
    """Configure system-wide logging based on config.yaml debug_mode."""
    cfg = get_config()
    level = logging.DEBUG if cfg.get("debug_mode", False) else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


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


def log_request_lifecycle(
    request_id: str,
    session_id: str,
    intent: str | None,
    model: str | None,
    tools_called: list[dict],
    lifecycle: list[str],
    llm_latency_ms: float,
    total_ms: float,
    error: str | None = None,
) -> None:
    """Write a single structured record for a completed request.

    Each record captures the full execution trace of one request:
    lifecycle state transitions, all tools called with per-tool timing,
    LLM latency, and total wall-clock duration.

    Args:
        request_id: UUID for this request.
        session_id: Session identifier (e.g. "ws:conv_abc123").
        intent: Classified intent (e.g. "email", "reminder") or None.
        model: Gemini model used (e.g. "gemini-flash-latest").
        tools_called: List of dicts: [{"name": ..., "duration_ms": ..., "success": ...}].
        lifecycle: List of state transition strings: ["CREATED→RUNNING", ...].
        llm_latency_ms: Time spent waiting for the Gemini API.
        total_ms: Total wall-clock time for the request.
        error: Error message if request failed, None otherwise.
    """
    log_event("request_complete", {
        "request_id": request_id,
        "session_id": session_id,
        "intent": intent,
        "model": model,
        "tools_called": tools_called,
        "lifecycle": lifecycle,
        "llm_latency_ms": round(llm_latency_ms, 1),
        "total_ms": round(total_ms, 1),
        "error": error,
    })
