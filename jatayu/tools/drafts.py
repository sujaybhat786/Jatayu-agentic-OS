"""Drafts tool — compose, list, and delete message drafts.

Drafts are held for user review. There is deliberately no "send" tool —
sending requires confirmation and will be gated in Tier 6.
Drafts are stored in data/drafts.json.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry


def _drafts_path() -> Path:
    return Path(get_config()["data_dir"]) / "drafts.json"


def _load() -> list[dict]:
    path = _drafts_path()
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return []


def _save(drafts: list[dict]) -> None:
    path = _drafts_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(drafts, f, indent=2, default=str)


# ------------------------------------------------------------------ #
#  Tool handlers                                                      #
# ------------------------------------------------------------------ #

def draft_message(recipient: str, purpose: str, body: str) -> str:
    """Compose a message draft for review.

    Args:
        recipient: Who the message is for.
        purpose: Brief reason — e.g. "follow up on meeting", "birthday wish".
        body: The actual message text.
    """
    drafts = _load()
    draft = {
        "id": uuid.uuid4().hex[:8],
        "recipient": recipient,
        "purpose": purpose,
        "body": body,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    drafts.append(draft)
    _save(drafts)
    return (
        f"✅ Draft saved (id: {draft['id']})\n"
        f"To: {recipient}\n"
        f"Purpose: {purpose}\n"
        f"---\n{body}\n---\n"
        f"(This is a draft — it hasn't been sent.)"
    )


def list_drafts() -> str:
    """Show all saved message drafts."""
    drafts = _load()
    if not drafts:
        return "No drafts saved."

    lines = []
    for d in drafts:
        preview = d["body"][:60] + ("…" if len(d["body"]) > 60 else "")
        lines.append(f"• [{d['id']}] To: {d['recipient']} — {d['purpose']}\n  \"{preview}\"")
    return "\n".join(lines)


def delete_draft(draft_id: str) -> str:
    """Delete a message draft by its id."""
    drafts = _load()
    for i, d in enumerate(drafts):
        if d["id"] == draft_id:
            removed = drafts.pop(i)
            _save(drafts)
            return f"✅ Deleted draft to {removed['recipient']} ({removed['purpose']})"
    return f"No draft found with id '{draft_id}'."


# ------------------------------------------------------------------ #
#  Registration                                                       #
# ------------------------------------------------------------------ #

def register(registry: ToolRegistry) -> None:
    """Register all draft tools."""
    registry.register(Tool(
        name="draft_message",
        description="Compose a message draft for the user to review. Use when the user asks to write, draft, or compose a message for someone. This only saves a draft — it does NOT send anything.",
        handler=draft_message,
        params=[
            ToolParam(name="recipient", type="string", description="Who the message is for"),
            ToolParam(name="purpose", type="string", description="Brief reason for the message"),
            ToolParam(name="body", type="string", description="The full message text"),
        ],
    ))

    registry.register(Tool(
        name="list_drafts",
        description="Show all saved message drafts. Use when the user asks to see their drafts.",
        handler=list_drafts,
        params=[],
    ))

    registry.register(Tool(
        name="delete_draft",
        description="Delete a message draft. Use when the user wants to discard a draft.",
        handler=delete_draft,
        requires_confirmation=True,  # deletes data
        params=[
            ToolParam(name="draft_id", type="string", description="The id of the draft to delete"),
        ],
    ))
