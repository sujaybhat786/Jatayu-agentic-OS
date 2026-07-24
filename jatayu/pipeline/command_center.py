"""Command Center — Lane 0 fast path. Runs BEFORE the Brain.

Intercepts requests that don't need an LLM and returns instant answers.
Returns a FastResult to short-circuit the Brain, or None to fall through.

Lane 0 covers:
  - Slash commands (/brief, /remind, /email, /search, /memory, /help)
  - Zero-LLM canned intents (greetings, time/date)
  - Direct tool reads (list_reminders, list_memories — no reasoning needed)
  - Session cache (exact/near-duplicate queries within 10 min TTL)
  - Qwen-local slot (pluggable, skipped if not installed)

Design rules:
  - NO LLM calls. NO network requests. Pure in-memory or direct tool reads.
  - Stateless across requests except the per-session cache.
  - Quality is non-negotiable: only route to Lane 0 when risk of wrong
    answer is effectively zero.
"""

from __future__ import annotations

import hashlib
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

logger = logging.getLogger(__name__)


# ── Lane taxonomy ─────────────────────────────────────────────────────────────

LANE_0 = 0   # instant, zero LLM
LANE_1 = 1   # single LLM call, filtered context, Flash
LANE_2 = 2   # multi-step / research / Pro model / agent plugins


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class FastResult:
    """Returned by CommandCenter when a request is handled without the Brain."""
    text: str
    lane: int = LANE_0
    source: str = "command_center"   # "cache", "slash", "greeting", "tool", "qwen"
    from_cache: bool = False


# ── Session cache entry ───────────────────────────────────────────────────────

@dataclass
class CacheEntry:
    text: str
    expires_at: float   # monotonic time


# ── Greeting corpus ───────────────────────────────────────────────────────────

_GREETINGS_IN = frozenset([
    "hi", "hello", "hey", "hello jatayu", "hi jatayu", "hey jatayu",
    "good morning", "good evening", "good afternoon", "good night",
    "sup", "yo", "howdy", "hiya", "greetings",
])

_GREETINGS_OUT = [
    "Hey! What can I do for you?",
    "Hello! Ready when you are.",
    "Hi there! What's on your mind?",
    "Hey! What do you need?",
    "Hello! How can I help?",
]

_THANKS_IN = frozenset([
    "thanks", "thank you", "ty", "thx", "cheers", "thanks a lot",
    "thank you so much", "thanks a lot", "thanks jatayu",
])

_THANKS_OUT = [
    "Of course!",
    "Happy to help.",
    "Anytime!",
    "Sure thing.",
    "You're welcome!",
]

_TIME_QUERIES = frozenset([
    "what time is it", "what's the time", "time please", "time?",
    "current time", "what time", "tell me the time",
    "what's today's date", "what is today's date", "what date is it",
    "today's date", "date today", "what day is it", "what is the date",
])

_HELP_TEXT = """Here's what I can do:

📧 **Email** — read, draft, send via Gmail
📅 **Calendar** — check schedule, add events
💾 **Drive / Docs / Sheets** — search, create, edit, share
🔔 **Reminders** — set, list, dismiss
🧠 **Memory** — remember people, projects, facts
💬 **Telegram** — send messages
📓 **Notion / Obsidian** — search and write notes
🌐 **Hermes** — analyze websites and complex tasks
🖱️ **OpenClaw** — browser automation

Slash commands: /brief  /remind  /email  /search  /memory  /help

Just tell me what you need — I'll figure out the rest."""


# ── Command Center ────────────────────────────────────────────────────────────

class CommandCenter:
    """Dispatches Lane 0 requests without touching the Brain.

    Args:
        brain_instance: The shared Brain (used only for direct tool reads).
        cache_ttl_s:    How long session cache entries live (default 10 min).
    """

    def __init__(
        self,
        brain_instance=None,
        cache_ttl_s: float = 600,
    ) -> None:
        self._brain = brain_instance
        self._cache_ttl = cache_ttl_s
        # Per-session cache: session_id → {key: CacheEntry}
        self._caches: dict[str, dict[str, CacheEntry]] = {}

    # ── Public entry point ────────────────────────────────────────────────────

    def dispatch(
        self,
        text: str,
        session_id: str,
        intent: str | None = None,
        on_status: Callable[[str], None] | None = None,
    ) -> FastResult | None:
        """Try to handle the request without the Brain.

        Returns a FastResult to short-circuit, or None to fall through.

        Args:
            text:       The user's raw message text.
            session_id: Used for session-scoped caching.
            intent:     Pre-classified intent (may be None if classifier failed).
            on_status:  Optional status callback (unused in Lane 0, kept for API symmetry).
        """
        stripped = text.strip()
        lower = stripped.lower()

        # ── 1. Slash commands ──────────────────────────────────────────────
        if stripped.startswith("/"):
            result = self._handle_slash(stripped, session_id)
            if result:
                return result

        # ── 2. Greetings ───────────────────────────────────────────────────
        if lower in _GREETINGS_IN:
            return FastResult(text=random.choice(_GREETINGS_OUT), source="greeting")

        # ── 3. Thanks ──────────────────────────────────────────────────────
        if lower in _THANKS_IN:
            return FastResult(text=random.choice(_THANKS_OUT), source="greeting")

        # ── 4. Time / date ─────────────────────────────────────────────────
        if lower in _TIME_QUERIES or lower.rstrip("?") in _TIME_QUERIES:
            return FastResult(text=self._now_formatted(), source="time")

        # ── 5. Direct tool reads (no reasoning needed) ─────────────────────
        if intent in ("reminder",) and any(
            kw in lower for kw in ("list", "show", "what are my", "any reminders")
        ):
            result = self._direct_list_reminders()
            if result:
                return FastResult(text=result, source="tool")

        if intent == "memory" and any(
            kw in lower for kw in ("list", "show", "what do you know", "what do you remember")
        ):
            result = self._direct_list_memories()
            if result:
                return FastResult(text=result, source="tool")

        # ── 6. Session cache ───────────────────────────────────────────────
        # Never cache state-changing intents
        _state_changing = {
            "email", "calendar", "memory", "reminder", "task_management",
            "document", "spreadsheet", "meeting",
        }
        if intent not in _state_changing:
            cached = self._cache_lookup(session_id, lower)
            if cached:
                return FastResult(
                    text=cached + "\n*(from a moment ago)*",
                    source="cache",
                    from_cache=True,
                )

        # ── 7. Qwen-local slot ─────────────────────────────────────────────
        # Only route to Qwen when ALL conditions hold:
        #   • intent is conversation or simple_qa
        #   • no entity names detected (no tool need)
        #   • input < 200 chars
        #   • Qwen is available
        if (
            intent in ("conversation", None)
            and len(stripped) < 200
            and self._qwen_available()
        ):
            qwen_reply = self._qwen_complete(stripped)
            if qwen_reply:
                self._cache_store(session_id, lower, qwen_reply)
                return FastResult(text=qwen_reply, source="qwen")

        return None   # fall through to Brain

    # ── Slash command handler ─────────────────────────────────────────────────

    def _handle_slash(self, text: str, session_id: str) -> FastResult | None:
        """Handle /command shortcuts."""
        parts = text.lower().strip().split(maxsplit=1)
        cmd = parts[0]
        arg = parts[1] if len(parts) > 1 else ""

        if cmd == "/help":
            return FastResult(text=_HELP_TEXT, source="slash")

        if cmd == "/brief":
            return FastResult(
                text="__SLASH_BRIEF__",   # sentinel: server.py resolves to daily brief
                source="slash",
            )

        if cmd == "/remind":
            result = self._direct_list_reminders()
            return FastResult(
                text=result or "No reminders set.",
                source="slash",
            )

        if cmd == "/memory":
            result = self._direct_list_memories()
            return FastResult(
                text=result or "No memories stored yet.",
                source="slash",
            )

        if cmd in ("/email", "/search"):
            # These need the Brain — return None to fall through
            # but inject the intent so the Brain knows the sub-task
            return None

        return None

    # ── Direct tool reads ─────────────────────────────────────────────────────

    def _direct_list_reminders(self) -> str | None:
        """Read reminders directly without the Brain."""
        try:
            from jatayu.tools.reminders import list_reminders
            return list_reminders()
        except Exception as e:
            logger.debug("CommandCenter: list_reminders failed: %s", e)
            return None

    def _direct_list_memories(self) -> str | None:
        """Read memories directly without the Brain."""
        try:
            from jatayu.memory.store import list_memories
            return list_memories()
        except Exception as e:
            logger.debug("CommandCenter: list_memories failed: %s", e)
            return None

    # ── Session cache ─────────────────────────────────────────────────────────

    def _cache_key(self, text: str) -> str:
        return hashlib.md5(text.encode()).hexdigest()

    def _cache_lookup(self, session_id: str, text: str) -> str | None:
        cache = self._caches.get(session_id, {})
        key = self._cache_key(text)
        entry = cache.get(key)
        if entry and time.monotonic() < entry.expires_at:
            return entry.text
        return None

    def _cache_store(self, session_id: str, text: str, reply: str) -> None:
        if session_id not in self._caches:
            self._caches[session_id] = {}
        key = self._cache_key(text)
        self._caches[session_id][key] = CacheEntry(
            text=reply,
            expires_at=time.monotonic() + self._cache_ttl,
        )

    def cache_store_reply(self, session_id: str, user_text: str, reply: str) -> None:
        """Called by server.py after a successful Brain reply to populate the cache."""
        self._cache_store(session_id, user_text.lower(), reply)

    def invalidate_session_cache(self, session_id: str) -> None:
        """Clear a session's cache (call after state-changing intents)."""
        self._caches.pop(session_id, None)

    # ── Qwen-local slot ───────────────────────────────────────────────────────

    def _qwen_available(self) -> bool:
        """Check if a local Qwen-compatible endpoint is reachable."""
        # Future: check for ollama / llama.cpp running on localhost:11434
        # For now always False — slot is reserved, not blocking anything.
        return False

    def _qwen_complete(self, text: str) -> str | None:
        """Run text through Qwen-local. Returns None if unavailable."""
        return None

    # ── Utilities ─────────────────────────────────────────────────────────────

    @staticmethod
    def _now_formatted() -> str:
        now = datetime.now()
        return now.strftime("It's %I:%M %p on %A, %B %-d %Y.")


# ── Lane assignment helper ────────────────────────────────────────────────────

# Intents that map to Lane 2 (Deep — Pro model / agent plugins)
_LANE_2_INTENTS = frozenset([
    "research", "coding", "creative_writing", "automation", "social_media",
    "unknown",  # conservative: unknown → deep
])

# Intents that map to Lane 0 (Fast path — no LLM or direct tool read)
_LANE_0_INTENTS = frozenset([
    "conversation",
])


def assign_lane(intent: str | None, text: str) -> int:
    """Assign a lane (0/1/2) to a classified intent.

    This is informational — CommandCenter.dispatch() makes the final call.
    The lane is attached to IntentResult.lane for routing and logging.
    """
    if intent in _LANE_2_INTENTS:
        return LANE_2
    if intent in _LANE_0_INTENTS and len(text.strip()) < 150:
        return LANE_0
    return LANE_1
