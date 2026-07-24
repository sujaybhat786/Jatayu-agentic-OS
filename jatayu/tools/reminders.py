"""Reminders tool — set, list, and dismiss reminders.

Reminders are stored in data/reminders.json as a human-readable list.
Each reminder has an id, text, due time, and status.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry


def _reminders_path() -> Path:
    return Path(get_config()["data_dir"]) / "reminders.json"


def _load() -> list[dict]:
    path = _reminders_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def _save(reminders: list[dict]) -> None:
    path = _reminders_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(reminders, f, indent=2, default=str)


# ------------------------------------------------------------------ #
#  Tool handlers                                                      #
# ------------------------------------------------------------------ #

def set_reminder(text: str, due_time: str = "") -> str:
    """Create a new reminder.

    Args:
        text: What to be reminded about.
        due_time: When it's due (free-form text like "5pm", "tomorrow morning").
                  If blank, it's a general reminder with no specific time.
    """
    reminders = _load()
    reminder = {
        "id": uuid.uuid4().hex[:8],
        "text": text,
        "due_time": due_time or "no specific time",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "done": False,
    }
    reminders.append(reminder)
    _save(reminders)
    return f"✅ Reminder set: \"{text}\" — due: {reminder['due_time']} (id: {reminder['id']})"


def list_reminders() -> str:
    """Show all active (not-done) reminders."""
    reminders = _load()
    active = [r for r in reminders if not r.get("done")]
    if not active:
        return "No active reminders."

    lines = []
    for r in active:
        lines.append(f"• [{r['id']}] {r['text']} — due: {r['due_time']}")
    return "\n".join(lines)


def dismiss_reminder(reminder_id: str) -> str:
    """Mark a reminder as done by its id."""
    reminders = _load()
    for r in reminders:
        if r["id"] == reminder_id:
            r["done"] = True
            _save(reminders)
            return f"✅ Dismissed: \"{r['text']}\""
    return f"No reminder found with id '{reminder_id}'."


# ------------------------------------------------------------------ #
#  Registration                                                       #
# ------------------------------------------------------------------ #

def register(registry: ToolRegistry) -> None:
    """Register all reminder tools."""
    registry.register(Tool(
        name="set_reminder",
        description="Set a new reminder with a note and optional due time. Use this when the user asks to be reminded of something.",
        handler=set_reminder,
        params=[
            ToolParam(name="text", type="string", description="What to be reminded about"),
            ToolParam(name="due_time", type="string", description="When it's due, e.g. '5pm', 'tomorrow morning', 'in 2 hours'", required=False),
        ],
    ))

    registry.register(Tool(
        name="list_reminders",
        description="Show all active reminders. Use when the user asks what reminders they have.",
        handler=list_reminders,
        params=[],
    ))

    registry.register(Tool(
        name="dismiss_reminder",
        description="Mark a reminder as done. Use when the user says they've handled a reminder or wants to clear it.",
        handler=dismiss_reminder,
        requires_confirmation=True,  # deletes data
        params=[
            ToolParam(name="reminder_id", type="string", description="The id of the reminder to dismiss"),
        ],
    ))
