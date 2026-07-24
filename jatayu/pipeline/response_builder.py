"""Response Builder — post-processes LLM output and extracts learnable signals.

Scans the model's response + conversation context for:
- New entity mentions (people, projects)
- Learnable facts
- Workspace state updates

Returns candidates back to the caller — never writes to EntityMemory or
FlatMemory directly (Brain Contract rule).

Design rules (from Brain Contract v1):
- Returns candidates; caller decides what to store.
- May read from EntityMemory (to avoid duplicate candidates).
- Never writes to EntityMemory, FlatMemory, or ConversationService.
- Never calls the LLM.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.pipeline.intent_classifier import IntentResult
    from jatayu.pipeline.task_extractor import Task
    from jatayu.pipeline.brain_state import Workspace

logger = logging.getLogger(__name__)


# ── Confidence tiers (Brain Contract v1: Q3 answer) ───────────────────────────

class Confidence:
    INFERRED        = 0.5   # Detected in response, no user explicit statement
    AUTO_LEARNED    = 0.7   # User said it, system stored automatically
    TOOL_VERIFIED   = 0.9   # Confirmed via Google/Notion/Calendar API
    USER_CONFIRMED  = 1.0   # User explicitly said "remember this"


# ── Output models ──────────────────────────────────────────────────────────────

@dataclass
class EntityCandidate:
    """A potential entity to store, suggested by the response scan."""
    type: str               # "person" | "project" | ...
    name: str               # canonical name
    raw_text: str           # original mention in text
    confidence: float       # Confidence.* tier
    fields: dict = field(default_factory=dict)  # any extra fields to merge


@dataclass
class FactCandidate:
    """A potential fact to store in flat memory."""
    fact: str
    category: str           # "identity" | "preference" | "work" | "project" | "stated"
    domain: str             # "personal" | "projects" | "work" | "knowledge"
    confidence: float       # Confidence.* tier


@dataclass
class ProcessedResponse:
    """The fully processed response ready for the caller to act on."""
    text: str                                               # cleaned response text
    entity_candidates: list[EntityCandidate] = field(default_factory=list)
    fact_candidates: list[FactCandidate] = field(default_factory=list)
    workspace_updates: dict = field(default_factory=dict)  # fields for BrainState

    def has_learnable_content(self) -> bool:
        return bool(self.entity_candidates or self.fact_candidates)


# ── Patterns ───────────────────────────────────────────────────────────────────

# "remember that" / "I'll remember" triggers — high confidence, user-stated
_EXPLICIT_REMEMBER = re.compile(
    r"\b(remember\s+that|got\s+it[,.]|noted[,.]|i'll\s+remember|i\s+have\s+stored|stored\s+that)\b",
    re.I
)

# Name + relation patterns: "Sarah, your sister"
_RELATION_MENTIONS = re.compile(
    r'\b([A-Z][a-z]{1,20})[,\s]+(?:your|his|her|their|my)\s+'
    r'(sister|brother|mother|father|wife|husband|partner|friend|colleague|boss|intern|doctor)',
    re.I
)

# Project name patterns: "AI Gurukula project", "Captain's Code platform"
_PROJECT_MENTIONS = re.compile(
    r'\b([A-Z][A-Za-z\']+(?:\s+[A-Z][A-Za-z\']+)+)\s+'
    r'(?:project|initiative|platform|campaign|product|app|system|tool)\b',
    re.I
)

# Fact patterns — "Your X is Y" / "I know that your X is Y"
_FACT_PATTERNS = [
    re.compile(r'\b(?:your|sujay\'?s?)\s+(\w+(?:\s+\w+)?)\s+is\s+([^.!?\n]{5,60})', re.I),
    re.compile(r'\bi\'?ve?\s+stored?\s+(?:that\s+)?(.{10,120})', re.I),
    re.compile(r'\bi\s+now\s+know\s+(?:that\s+)?(.{10,120})', re.I),
]


# ── Builder ────────────────────────────────────────────────────────────────────

class ResponseBuilder:
    """Processes a raw LLM response and extracts learnable signals.

    Args:
        entity_memory: Optional EntityMemoryService to check for existing records.
    """

    def __init__(self, entity_memory=None) -> None:
        self._entity_memory = entity_memory

    def process(
        self,
        raw_response: str,
        conversation_text: str,
        intent: "IntentResult",
        task: "Task",
        workspace: "Workspace | None" = None,
    ) -> ProcessedResponse:
        """Process the raw LLM response.

        Args:
            raw_response:      The text produced by the LLM.
            conversation_text: The user's input that triggered this response.
            intent:            Classified intent for this turn.
            task:              Extracted task with entities.
            workspace:         Current workspace for context.

        Returns:
            ProcessedResponse with text, entity candidates, fact candidates,
            and workspace update suggestions.
        """
        text = raw_response.strip()

        entity_candidates: list[EntityCandidate] = []
        fact_candidates: list[FactCandidate] = []
        workspace_updates: dict = {}

        # ── 1. Check if the LLM acknowledged a store operation ────────────
        explicit_store = bool(_EXPLICIT_REMEMBER.search(text))

        # ── 2. Scan for entity candidates in the response ──────────────────
        entity_candidates.extend(
            self._extract_entity_candidates(
                text, conversation_text, explicit_store
            )
        )

        # ── 3. Scan for fact candidates ────────────────────────────────────
        fact_candidates.extend(
            self._extract_fact_candidates(text, conversation_text, explicit_store)
        )

        # ── 4. Inherit entities from the task (already resolved) ──────────
        # Task entities are high-confidence since they were resolved from memory
        for extracted in task.entities:
            if extracted.entity_type in ("person", "project") and extracted.resolved_id:
                # Entity was successfully resolved — mark as used (times_used++)
                workspace_updates[f"touch_entity_{extracted.resolved_id}"] = True

        # ── 5. Workspace update suggestions ───────────────────────────────
        # If response mentions a project being discussed, suggest activating it
        for candidate in entity_candidates:
            if candidate.type == "project" and candidate.confidence >= Confidence.AUTO_LEARNED:
                workspace_updates["current_task"] = task.goal

        result = ProcessedResponse(
            text=text,
            entity_candidates=entity_candidates,
            fact_candidates=fact_candidates,
            workspace_updates=workspace_updates,
        )

        if result.has_learnable_content():
            logger.info(
                "ResponseBuilder: found %d entity candidates, %d fact candidates",
                len(entity_candidates), len(fact_candidates)
            )

        return result

    # ── Entity extraction ──────────────────────────────────────────────────────

    def _extract_entity_candidates(
        self,
        response: str,
        user_input: str,
        explicit_store: bool,
    ) -> list[EntityCandidate]:
        """Scan text for new entity candidates."""
        candidates = []
        confidence = Confidence.USER_CONFIRMED if explicit_store else Confidence.AUTO_LEARNED

        # "Name, your sister" / "Sarah, your colleague"
        for match in _RELATION_MENTIONS.finditer(response + " " + user_input):
            name = match.group(1).strip()
            relation = match.group(2).lower()

            if self._already_known("person", name):
                continue

            candidates.append(EntityCandidate(
                type="person",
                name=name,
                raw_text=match.group(0),
                confidence=confidence,
                fields={"relation": relation},
            ))

        # "AI Gurukula project" mentions
        for match in _PROJECT_MENTIONS.finditer(response + " " + user_input):
            name = match.group(1).strip()

            if self._already_known("project", name):
                continue

            candidates.append(EntityCandidate(
                type="project",
                name=name,
                raw_text=match.group(0),
                confidence=Confidence.INFERRED,  # Just seen in conversation, not user-stated
                fields={},
            ))

        return candidates

    # ── Fact extraction ────────────────────────────────────────────────────────

    def _extract_fact_candidates(
        self,
        response: str,
        user_input: str,
        explicit_store: bool,
    ) -> list[FactCandidate]:
        """Scan text for learnable facts."""
        candidates = []
        confidence = Confidence.USER_CONFIRMED if explicit_store else Confidence.AUTO_LEARNED

        for pattern in _FACT_PATTERNS:
            for match in pattern.finditer(response):
                fact_text = match.group(0).strip()
                if len(fact_text) < 10 or len(fact_text) > 200:
                    continue

                # Basic dedup — avoid adding the same fact twice
                if any(c.fact == fact_text for c in candidates):
                    continue

                candidates.append(FactCandidate(
                    fact=fact_text,
                    category="stated",
                    domain="personal",
                    confidence=confidence,
                ))

        return candidates

    # ── Dedup helpers ──────────────────────────────────────────────────────────

    def _already_known(self, entity_type: str, name: str) -> bool:
        """Check if an entity already exists in EntityMemory."""
        if self._entity_memory is None:
            return False
        try:
            if entity_type == "person":
                return self._entity_memory.get_person(name) is not None
            elif entity_type == "project":
                return self._entity_memory.get_project(name) is not None
        except Exception:
            pass
        return False
