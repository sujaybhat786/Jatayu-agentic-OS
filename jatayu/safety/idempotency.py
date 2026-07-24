"""Idempotency Tracker — prevents duplicate execution of send/destructive operations.

Keyed by md5(tool_name + session_id + args_hash) with a 5-minute TTL.
Distinguishes three states:
1. IN_FLIGHT / SUCCESS -> Blocks duplicate execution within 5 minutes.
2. CLEAN FAILURE -> Clears the hash immediately so user can fix typos and retry.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time

logger = logging.getLogger(__name__)

# Destructive / Send tool names that must be idempotent
_DESTRUCTIVE_TOOLS = frozenset({
    "google_gmail_send",
    "send_telegram_message",
    "google_drive_share",
    "google_drive_delete",
    "google_docs_delete",
    "google_sheets_delete_rows",
})


class IdempotencyTracker:
    """Thread-safe deduplication tracker for destructive and send operations."""

    def __init__(self, ttl_seconds: float = 300.0):
        import threading
        self.ttl_seconds = ttl_seconds
        self._lock = threading.Lock()
        # key -> (timestamp, status: "IN_FLIGHT" | "SUCCESS")
        self._history: dict[str, tuple[float, str]] = {}

    def _make_key(self, tool_name: str, session_id: str, tool_args: dict) -> str:
        """Create a deterministic hash key for an action."""
        args_str = json.dumps(tool_args, sort_keys=True)
        raw = f"{tool_name}:{session_id}:{args_str}"
        return hashlib.md5(raw.encode("utf-8")).hexdigest()

    def check_and_record(self, tool_name: str, session_id: str, tool_args: dict) -> bool:
        """Check if an action is a duplicate within TTL.

        Returns:
            True if it IS a duplicate (should be BLOCKED).
            False if it is new (RECORDED and allowed to proceed).
        """
        if tool_name not in _DESTRUCTIVE_TOOLS:
            return False  # Reads / drafts / safe ops are not deduplicated

        now = time.monotonic()
        key = self._make_key(tool_name, session_id, tool_args)

        with self._lock:
            # Clean expired entries
            expired = [k for k, (ts, _) in self._history.items() if now - ts > self.ttl_seconds]
            for k in expired:
                del self._history[k]

            if key in self._history:
                _, status = self._history[key]
                logger.warning(
                    "IdempotencyTracker: blocked duplicate action '%s' for session %s (status=%s, key=%s)",
                    tool_name, session_id, status, key
                )
                return True  # IS DUPLICATE

            self._history[key] = (now, "IN_FLIGHT")
            return False  # NEW ACTION

    def record_outcome(self, tool_name: str, session_id: str, tool_args: dict, is_success: bool) -> None:
        """Record the outcome of a tool execution.

        - If is_success=True: updates state to SUCCESS (retained for TTL to block duplicates).
        - If is_success=False (clean failure): CLEARS the key immediately so user can fix and retry!
        """
        if tool_name not in _DESTRUCTIVE_TOOLS:
            return

        key = self._make_key(tool_name, session_id, tool_args)
        with self._lock:
            if is_success:
                if key in self._history:
                    ts, _ = self._history[key]
                    self._history[key] = (ts, "SUCCESS")
            else:
                # Clean failure: remove key immediately
                if key in self._history:
                    del self._history[key]
                    logger.info(
                        "IdempotencyTracker: cleared key for clean failure '%s' in session %s — retry unlocked.",
                        tool_name, session_id
                    )
# Singleton instance
_tracker = IdempotencyTracker()

def get_idempotency_tracker() -> IdempotencyTracker:
    return _tracker
