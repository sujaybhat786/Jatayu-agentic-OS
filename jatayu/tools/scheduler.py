"""Scheduler tool — manage today's task list.

A simple daily plan stored in data/schedule.json. Tasks have a
description, priority, and completion status.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, date
from pathlib import Path

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry


def _schedule_path() -> Path:
    return Path(get_config()["data_dir"]) / "schedule.json"


def _load() -> dict:
    """Load the schedule. Tasks persist across days until explicitly completed —
    previously this reset to empty on every date change, silently deleting
    anything not finished by midnight. That's fixed: only a brand-new file
    starts with today's date; existing tasks are never auto-wiped."""
    path = _schedule_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"date": str(date.today()), "tasks": []}


def _save(data: dict) -> None:
    path = _schedule_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


# ------------------------------------------------------------------ #
#  Tool handlers                                                      #
# ------------------------------------------------------------------ #

def add_task(description: str, priority: str = "medium") -> str:
    """Add a task to today's schedule.

    Args:
        description: What the task is.
        priority: 'high', 'medium', or 'low'.
    """
    data = _load()
    task = {
        "id": uuid.uuid4().hex[:8],
        "description": description,
        "priority": priority.lower(),
        "done": False,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    }
    data["tasks"].append(task)
    _save(data)
    return f"✅ Added to today's schedule: \"{description}\" (priority: {priority}, id: {task['id']})"


def list_tasks() -> str:
    """Show today's tasks, grouped by status."""
    data = _load()
    tasks = data.get("tasks", [])
    if not tasks:
        return f"No tasks scheduled for today ({date.today()})."

    pending = [t for t in tasks if not t.get("done")]
    done = [t for t in tasks if t.get("done")]

    lines = [f"📅 Today's schedule ({date.today()}):"]

    if pending:
        lines.append("\n📋 To do:")
        for t in pending:
            marker = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(t["priority"], "⚪")
            lines.append(f"  {marker} [{t['id']}] {t['description']}")

    if done:
        lines.append("\n✅ Done:")
        for t in done:
            lines.append(f"  ✓ [{t['id']}] {t['description']}")

    return "\n".join(lines)


def complete_task(task_id: str) -> str:
    """Mark a task as done."""
    data = _load()
    for t in data["tasks"]:
        if t["id"] == task_id:
            t["done"] = True
            _save(data)
            return f"✅ Done: \"{t['description']}\""
    return f"No task found with id '{task_id}'."


def reorder_tasks(task_ids: list[str]) -> str:
    """Reorder tasks by providing the ids in the desired order.

    Args:
        task_ids: List of task ids in the new order.
    """
    data = _load()
    task_map = {t["id"]: t for t in data["tasks"]}

    # Validate all ids exist
    unknown = [tid for tid in task_ids if tid not in task_map]
    if unknown:
        return f"Unknown task ids: {', '.join(unknown)}"

    # Put requested ids first in order, then any not mentioned
    reordered = [task_map[tid] for tid in task_ids if tid in task_map]
    remaining = [t for t in data["tasks"] if t["id"] not in task_ids]
    data["tasks"] = reordered + remaining
    _save(data)
    return "✅ Tasks reordered."


# ------------------------------------------------------------------ #
#  Registration                                                       #
# ------------------------------------------------------------------ #

def register(registry: ToolRegistry) -> None:
    """Register all scheduler tools."""
    registry.register(Tool(
        name="add_task",
        description="Add a task to today's schedule. Use when the user wants to plan, schedule, or add something to their day.",
        handler=add_task,
        params=[
            ToolParam(name="description", type="string", description="What the task is"),
            ToolParam(name="priority", type="string", description="Priority level", required=False, enum=["high", "medium", "low"]),
        ],
    ))

    registry.register(Tool(
        name="list_tasks",
        description="Show today's task list. Use when the user asks about their schedule, plan, or tasks for today.",
        handler=list_tasks,
        params=[],
    ))

    registry.register(Tool(
        name="complete_task",
        description="Mark a task as done. Use when the user says they finished or completed a task.",
        handler=complete_task,
        params=[
            ToolParam(name="task_id", type="string", description="The id of the task to mark done"),
        ],
    ))

    registry.register(Tool(
        name="reorder_tasks",
        description="Reorder today's tasks. Use when the user wants to reprioritize or rearrange their schedule.",
        handler=reorder_tasks,
        params=[
            ToolParam(name="task_ids", type="array", description="Task ids in the desired new order"),
        ],
    ))
