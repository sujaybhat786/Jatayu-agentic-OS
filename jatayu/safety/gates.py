"""Confirmation gate — stops consequential actions until the user says yes.

Any tool flagged with requires_confirmation=True must pass through this
gate before executing. The gate sits between "model chose to call tool"
and "tool actually runs," covering spoken, typed, and all future input
modes equally.

Rules:
- Confirmation is per-action — approving one doesn't pre-authorize the next.
- The gate states plainly what the assistant intends to do.
- On denial, the tool does NOT run and the model is told.

Web context: confirmation is async — a WebSocket event is emitted and the
gate waits for a callback response. CLI context: stdin is used as before.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Patterns that look like injected instructions
_INJECTION_PATTERNS = [
    r"ignore\s+(your|all|previous)\s+(rules|instructions|guidelines)",
    r"disregard\s+(your|all|previous)",
    r"you\s+are\s+now\s+(?:a|an)\s+",
    r"system\s*:\s*",
    r"new\s+instructions?\s*:",
    r"override\s+(your|all|previous)",
    r"forget\s+(your|all|previous)\s+(rules|instructions)",
]
_INJECTION_RE = re.compile(
    "|".join(_INJECTION_PATTERNS), re.IGNORECASE
)


def check_for_injection(text: str) -> str | None:
    """Scan text for patterns that look like injected instructions.

    Args:
        text: Any text the assistant has pulled in from the outside
              (tool results, file contents, transcripts, etc.).

    Returns:
        A warning string if suspicious content is found, None otherwise.
    """
    if _INJECTION_RE.search(text):
        return (
            "⚠️  This content appears to contain instructions directed "
            "at the assistant (e.g. 'ignore your rules'). I'm flagging "
            "it for your review rather than acting on it."
        )
    return None


def request_confirmation(
    tool_name: str,
    args: dict[str, Any],
    description: str | None = None,
    confirm_fn: Callable[[str, dict, str | None], bool | None] | None = None,
) -> bool:
    """Ask the user to confirm a consequential action.

    If confirm_fn is provided, uses that callback. Non-blocking for the
    event loop.

    In CLI context or if confirm_fn is None: prints to stdout and reads from stdin.

    Args:
        tool_name: Name of the tool about to run.
        args: Arguments that will be passed to the tool.
        description: Optional human-readable description of the action.
        confirm_fn: Optional callback to invoke for confirmation.

    Returns:
        True if the user confirms, False otherwise.
    """
    # ── Provided callback (e.g. Web mode) ──────────────────────────────────
    if confirm_fn is not None:
        try:
            result = confirm_fn(tool_name, args, description)
            if result is not None:
                logger.info(
                    "Confirmation %s via callback: %s",
                    "approved" if result else "denied",
                    tool_name,
                )
                return result
            # Callback returned None → client disconnected, fall through to deny
            logger.warning(
                "Confirmation callback returned None for %s — auto-denying", tool_name
            )
            return False
        except Exception as e:
            logger.error("Confirmation callback raised %s — auto-denying", e)
            return False

    # ── CLI mode: stdin fallback ───────────────────────────────────────────
    print("\n" + "─" * 50)
    print("🔒 Confirmation required")
    print(f"   Action: {tool_name}")

    if description:
        print(f"   What: {description}")

    # Show key arguments (skip very long values)
    for key, val in args.items():
        val_str = str(val)
        if len(val_str) > 100:
            val_str = val_str[:100] + "…"
        print(f"   {key}: {val_str}")

    print("─" * 50)

    while True:
        try:
            answer = input("   Proceed? (yes/no): ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("   → Cancelled.")
            return False

        if answer in ("yes", "y"):
            print("   → Approved.")
            return True
        elif answer in ("no", "n"):
            print("   → Denied.")
            return False
        else:
            print("   Please type 'yes' or 'no'.")
