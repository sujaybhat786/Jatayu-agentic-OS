"""Intent Classifier — rule-based, no LLM, no API call.

Classifies what TYPE of action the user wants based on keyword patterns.
Extracted and formalized from the _offline_router in server.py.

Design rules (from Brain Contract v1):
- Rule-based only. NEVER calls the LLM. NEVER makes network requests.
- Reads from BrainState for workspace context hints (optional).
- Stateless — every call is independent.
- Returns IntentResult with confidence score.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.pipeline.brain_state import BrainStateSnapshot

logger = logging.getLogger(__name__)


# ── Intent taxonomy ────────────────────────────────────────────────────────────

INTENTS = [
    "conversation",
    "research",
    "creative_writing",
    "coding",
    "email",
    "calendar",
    "reminder",
    "search",
    "memory",
    "document",
    "spreadsheet",
    "image",
    "voice",
    "automation",
    "social_media",
    "task_management",
    "meeting",
    "unknown",
]

# Sub-intents by intent type
SUB_INTENTS: dict[str, list[str]] = {
    "email":    ["read", "draft", "send", "reply", "search", "delete"],
    "calendar": ["read", "create", "update", "delete", "check"],
    "document": ["read", "create", "edit", "delete", "search"],
    "spreadsheet": ["read", "create", "update", "append"],
    "memory":   ["store", "retrieve", "update", "delete"],
    "reminder": ["set", "list", "dismiss"],
    "task_management": ["add", "complete", "list", "update"],
    "meeting":  ["schedule", "find", "summarize"],
    "search":   ["knowledge", "web", "files"],
}


# ── Result model ───────────────────────────────────────────────────────────────

@dataclass
class IntentResult:
    """Output of the IntentClassifier."""
    intent: str              # canonical intent from INTENTS
    confidence: float        # 0.0 - 1.0
    sub_intent: str | None   # e.g. "draft" for email
    raw_text: str            # original input, passed to downstream services
    requires_tool_groups: list[str] = field(default_factory=list)  # tool group names

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "confidence": self.confidence,
            "sub_intent": self.sub_intent,
            "requires_tool_groups": self.requires_tool_groups,
        }


# ── Keyword rule tables ────────────────────────────────────────────────────────
# Extracted and expanded from server.py _offline_router (lines 610-906).
# Each entry is (pattern, intent, sub_intent, confidence).
# Evaluated in order — first match wins within a priority tier.

_RULES: list[tuple[re.Pattern, str, str | None, float]] = []


def _add(pattern: str, intent: str, sub_intent: str | None = None, confidence: float = 0.85) -> None:
    _RULES.append((re.compile(pattern, re.IGNORECASE), intent, sub_intent, confidence))


# ── Email patterns ─────────────────────────────────────────────────────────────
_add(r"\bsend\s+(an?\s+)?email\b",              "email", "send",   0.97)
_add(r"\bsend\s+(an?\s+)?mail\b",               "email", "send",   0.97)
_add(r"\bemail\s+\w+",                           "email", "send",   0.90)
_add(r"\bdraft\s+(an?\s+)?email\b",              "email", "draft",  0.97)
_add(r"\bwrite\s+(an?\s+)?email\b",              "email", "draft",  0.95)
_add(r"\bcompose\s+(an?\s+)?email\b",            "email", "draft",  0.95)
_add(r"\breply\s+to\s+(my\s+)?email\b",          "email", "reply",  0.95)
_add(r"\bread\s+(my\s+)?email(s)?\b",            "email", "read",   0.95)
_add(r"\bcheck\s+(my\s+)?email(s)?\b",           "email", "read",   0.90)
_add(r"\bany\s+(new\s+)?emails?\b",              "email", "read",   0.88)
_add(r"\binbox\b",                               "email", "read",   0.80)
_add(r"\bgmail\b",                               "email", None,     0.75)

# ── Calendar patterns ──────────────────────────────────────────────────────────
_add(r"\bschedule\s+(a\s+)?(meeting|call|event)\b", "calendar", "create", 0.97)
_add(r"\bbook\s+(a\s+)?(meeting|call|slot)\b",       "calendar", "create", 0.97)
_add(r"\bcreate\s+(a\s+)?(calendar\s+)?event\b",     "calendar", "create", 0.95)
_add(r"\badd\s+(a\s+)?(meeting|event)\s+to\b",       "calendar", "create", 0.93)
_add(r"\bwhat('s| is)\s+on\s+my\s+calendar\b",       "calendar", "read",   0.97)
_add(r"\bcheck\s+(my\s+)?calendar\b",                "calendar", "read",   0.95)
_add(r"\bwhat\s+(am\s+I|do\s+I\s+have)\s+(today|tomorrow|this week)\b", "calendar", "read", 0.92)
_add(r"\bmy\s+(schedule|agenda)\b",                  "calendar", "read",   0.88)
_add(r"\bcancel\s+(the\s+)?(meeting|event)\b",       "calendar", "delete", 0.95)

# ── Reminder patterns ──────────────────────────────────────────────────────────
_add(r"\bset\s+(a\s+)?reminder\b",               "reminder", "set",     0.97)
_add(r"\bremind\s+me\b",                          "reminder", "set",     0.97)
_add(r"\bdon'?t\s+let\s+me\s+forget\b",           "reminder", "set",     0.90)
_add(r"\blist\s+(my\s+)?reminders?\b",            "reminder", "list",    0.95)
_add(r"\bshow\s+(my\s+)?reminders?\b",            "reminder", "list",    0.90)
_add(r"\bdismiss\s+(the\s+)?reminder\b",          "reminder", "dismiss", 0.95)

# ── Task management patterns ───────────────────────────────────────────────────
_add(r"\badd\s+(a\s+)?task\b",                   "task_management", "add",      0.95)
_add(r"\bcreate\s+(a\s+)?task\b",                "task_management", "add",      0.95)
_add(r"\bmark\s+(it\s+|the\s+task\s+)?as\s+done\b", "task_management", "complete", 0.95)
_add(r"\bcomplete\s+(the\s+)?task\b",            "task_management", "complete", 0.90)
_add(r"\bmy\s+(to.?do|tasks?|checklist)\b",      "task_management", "list",     0.85)

# ── Document patterns ──────────────────────────────────────────────────────────
_add(r"\bcreate\s+(a\s+)?(google\s+)?doc(ument)?\b", "document", "create", 0.97)
_add(r"\bwrite\s+(a\s+)?doc(ument)?\b",               "document", "create", 0.90)
_add(r"\bopen\s+(the\s+)?doc(ument)?\b",              "document", "read",   0.88)
_add(r"\bread\s+(the\s+)?doc(ument)?\b",              "document", "read",   0.90)
_add(r"\bedit\s+(the\s+)?doc(ument)?\b",              "document", "edit",   0.90)
_add(r"\bupdate\s+(the\s+)?doc(ument)?\b",            "document", "edit",   0.85)
_add(r"\bobsidian\b",                                  "document", None,     0.80)
_add(r"\bnotion\b",                                    "document", None,     0.75)
_add(r"\bnote\b",                                      "document", "create", 0.70)

# ── Spreadsheet patterns ───────────────────────────────────────────────────────
_add(r"\bcreate\s+(a\s+)?(google\s+)?sheet(s)?\b",    "spreadsheet", "create", 0.97)
_add(r"\bspreadsheet\b",                               "spreadsheet", None,     0.85)
_add(r"\bgoogle\s+sheets?\b",                          "spreadsheet", None,     0.90)
_add(r"\badd\s+(a\s+)?row\b",                          "spreadsheet", "append", 0.85)
_add(r"\bupdate\s+(the\s+)?sheet\b",                   "spreadsheet", "update", 0.88)

# ── Memory patterns ────────────────────────────────────────────────────────────
_add(r"\bremember\s+(that|this|my|her|his|their)\b",  "memory", "store",    0.97)
_add(r"\bmake\s+a\s+note\s+(that|of)\b",              "memory", "store",    0.93)
_add(r"\bdon'?t\s+forget\s+that\b",                   "memory", "store",    0.90)
_add(r"\bwhat\s+do\s+you\s+(know|remember)\s+about\b","memory", "retrieve", 0.90)
_add(r"\bforget\s+(that|this|about)\b",               "memory", "delete",   0.90)
_add(r"\bmy\s+memories?\b",                           "memory", "retrieve", 0.80)

# ── Search / knowledge patterns ────────────────────────────────────────────────
_add(r"\bsearch\s+(the\s+)?(knowledge|vault|obsidian|notion)\b", "search", "knowledge", 0.95)
_add(r"\blook\s+up\b",                               "search", None,      0.80)
_add(r"\bfind\s+(me\s+)?(information|info|details)\s+about\b",  "search", None, 0.85)
_add(r"\bwhat\s+(is|are)\s+.{0,40}\?$",             "research", None,    0.70)

# ── Coding patterns (from hermes_keywords in _offline_router) ─────────────────
_add(r"\bhermes\b",                                  "coding", None,     0.95)
_add(r"\bhey\s+hermes\b",                            "coding", None,     0.98)
_add(r"\bwrite\s+(me\s+)?(some\s+)?code\b",          "coding", None,     0.90)
_add(r"\bfix\s+(the\s+)?bug\b",                      "coding", None,     0.88)
_add(r"\bdebug\s+(this|the)\b",                      "coding", None,     0.85)
_add(r"\brefactor\b",                                "coding", None,     0.85)
_add(r"\bpull\s+request\b",                          "coding", None,     0.82)
_add(r"\bgithub\b",                                  "coding", None,     0.75)

# ── Automation patterns (from openclaw_keywords) ───────────────────────────────
_add(r"\bopenclaw\b",                                "automation", None, 0.95)
_add(r"\bopen\s+claw\b",                             "automation", None, 0.95)
_add(r"\bautomate\b",                                "automation", None, 0.82)

# ── Meeting patterns ───────────────────────────────────────────────────────────
_add(r"\bschedule\s+(a\s+)?meeting\b",               "meeting", "schedule", 0.95)
_add(r"\bjoin\s+(the\s+)?meeting\b",                  "meeting", "find",     0.90)
_add(r"\bmeeting\s+(summary|notes|recap)\b",          "meeting", "summarize",0.90)

# ── Creative writing patterns ──────────────────────────────────────────────────
_add(r"\bwrite\s+(a\s+)?(post|article|essay|blog|story|caption|tweet)\b", "creative_writing", None, 0.90)
_add(r"\bdraft\s+(a\s+)?(post|article|linkedin)\b",   "creative_writing", None, 0.88)
_add(r"\bcreative\s+writing\b",                       "creative_writing", None, 0.95)

# ── Social media patterns ──────────────────────────────────────────────────────
_add(r"\blinkedin\s+post\b",                          "social_media", None, 0.92)
_add(r"\btweet\b",                                    "social_media", None, 0.88)
_add(r"\binstagram\s+caption\b",                      "social_media", None, 0.90)
_add(r"\bpost\s+(on|to)\s+(linkedin|twitter|instagram)\b", "social_media", None, 0.92)

# ── Research patterns ──────────────────────────────────────────────────────────
_add(r"\bresearch\b",                                 "research", None, 0.85)
_add(r"\bsummarize\b",                               "research", None, 0.78)
_add(r"\bexplain\b",                                 "research", None, 0.72)
_add(r"\bwhat\s+(is|are|was|were)\b",                "research", None, 0.65)
_add(r"\bhow\s+(do|does|did|can)\b",                 "research", None, 0.65)

# ── Tool group mapping ─────────────────────────────────────────────────────────

INTENT_TOOL_GROUPS: dict[str, list[str]] = {
    "email":          ["google_gmail_read", "google_gmail_draft", "google_gmail_send", "google_list_accounts"],
    "calendar":       ["google_calendar_read", "google_calendar_create"],
    "document":       ["google_docs_create", "google_docs_read", "google_docs_edit", "google_drive_search", "obsidian_search", "obsidian_write_note", "notion_search", "notion_create_page"],
    "spreadsheet":    ["google_sheets_create", "google_sheets_read", "google_sheets_update", "google_sheets_append"],
    "memory":         ["remember", "forget", "update_memory", "list_memories", "remember_entity", "get_person", "get_project"],
    "search":         ["knowledge_search", "notion_search", "obsidian_search"],
    "reminder":       ["set_reminder", "list_reminders", "dismiss_reminder"],
    "task_management":["add_task", "complete_task"],
    "coding":         ["hermes_ask"],
    "automation":     ["openclaw_ask"],
    "research":       ["knowledge_search", "obsidian_search", "notion_search"],
    "meeting":        ["google_calendar_read", "google_calendar_create"],
    "social_media":   ["draft_message"],
    "creative_writing": ["draft_message"],
    "conversation":   [],    # Pure conversation — no tools needed
    "unknown":        None,  # None = expose all (fallback behavior)
}


# ── Classifier ─────────────────────────────────────────────────────────────────

class IntentClassifier:
    """Rule-based intent classifier.

    Evaluates all rules in priority order and returns the first match.
    Falls back to "conversation" for clear natural language, or "unknown"
    for truly ambiguous input.

    Never calls the LLM. Never makes network requests.
    """

    def classify(
        self,
        text: str,
        workspace: "BrainStateSnapshot | None" = None,
    ) -> IntentResult:
        """Classify the intent of user input.

        Args:
            text:      Raw user input text.
            workspace: Optional BrainState snapshot for context hints.
                       If the user is in an active email context, ambiguous
                       inputs may be treated as email sub-intents.

        Returns:
            IntentResult with the best matching intent.
        """
        if not text or not text.strip():
            return IntentResult(
                intent="conversation",
                confidence=1.0,
                sub_intent=None,
                raw_text=text or "",
                requires_tool_groups=[],
            )

        cleaned = text.strip()

        # ── Rule matching ──────────────────────────────────────────────────
        best_intent: str = "unknown"
        best_confidence: float = 0.0
        best_sub_intent: str | None = None

        for pattern, intent, sub_intent, confidence in _RULES:
            if pattern.search(cleaned):
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_intent = intent
                    best_sub_intent = sub_intent

        # ── Workspace context boost ────────────────────────────────────────
        # If the workspace has an active project and the query is ambiguous,
        # boost any intent that overlaps with the active context.
        if workspace and best_confidence < 0.7:
            boosted = self._workspace_boost(cleaned, workspace, best_intent, best_confidence)
            if boosted:
                best_intent, best_sub_intent, best_confidence = boosted

        # ── Fallback heuristics ────────────────────────────────────────────
        if best_intent == "unknown":
            word_count = len(cleaned.split())
            lower = cleaned.lower()

            # Social/greeting patterns → always conversation, never research
            _social_starters = (
                "hello", "hi ", "hey", "how are", "how's it", "good morning",
                "good evening", "good afternoon", "what's up", "wassup",
                "thanks", "thank you", "ok ", "okay", "sure", "got it",
                "sounds good", "makes sense", "alright", "great", "nice",
                "tell me about yourself", "who are you", "what can you do",
            )
            is_social = any(lower.startswith(s) or lower == s.strip() for s in _social_starters)

            if is_social or (word_count <= 6 and not lower.startswith(("what", "who", "when", "where", "why", "how"))):
                # Short non-research message or social opener → conversation
                best_intent = "conversation"
                best_confidence = 0.75
            elif word_count <= 8 and "?" in cleaned and not any(
                kw in lower for kw in ("is", "are", "was", "were", "does", "do",
                                        "did", "can", "could", "should", "would",
                                        "explain", "summarize", "research", "find",
                                        "tell me about", "what is", "who is")
            ):
                # Short question without research keywords → still conversation
                best_intent = "conversation"
                best_confidence = 0.70
            elif "?" in cleaned or lower.startswith(("what", "who", "when", "where", "why", "how")):
                # Substantive question → research (triggers knowledge pre-fetch)
                best_intent = "research"
                best_confidence = 0.65

        tool_groups = INTENT_TOOL_GROUPS.get(best_intent, []) or []

        result = IntentResult(
            intent=best_intent,
            confidence=round(best_confidence, 3),
            sub_intent=best_sub_intent,
            raw_text=cleaned,
            requires_tool_groups=tool_groups if tool_groups is not None else [],
        )

        logger.debug(
            "IntentClassifier: '%s...' → intent=%s (%.2f) sub=%s",
            cleaned[:60],
            result.intent,
            result.confidence,
            result.sub_intent,
        )

        return result

    def _workspace_boost(
        self,
        text: str,
        snapshot: "BrainStateSnapshot",
        current_intent: str,
        current_confidence: float,
    ) -> tuple[str, str | None, float] | None:
        """Apply workspace context to boost weak classification signals."""
        ws = snapshot.workspace

        # If active project is known and user mentions it by name
        if ws.current_project:
            proj_name = ws.current_project.get("name", "").lower()
            if proj_name and proj_name in text.lower():
                # User is likely talking about an active project context
                return None  # No specific intent boost, just leave as-is

        # If active people are in context and user refers to them
        if ws.current_people:
            for person in ws.current_people:
                person_name = person.get("name", "").lower()
                if person_name and person_name in text.lower():
                    return None  # Known person in context, no specific boost

        return None
