"""Task Extractor — extracts the specific WHAT from the general intent.

Separates "Intent = email" from "Task = send project update to sister".
Resolves entity references from raw text using EntityMemoryService.

Design rules (from Brain Contract v1):
- Stateless: every call is independent.
- May read from EntityMemoryService to resolve entity IDs.
- NEVER writes to EntityMemoryService.
- NEVER calls the LLM.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from jatayu.pipeline.intent_classifier import IntentResult
    from jatayu.pipeline.brain_state import BrainStateSnapshot

logger = logging.getLogger(__name__)


# ── Date / time reference patterns ────────────────────────────────────────────

_DATE_PATTERNS = [
    (re.compile(r"\btoday\b",        re.I), "today"),
    (re.compile(r"\btomorrow\b",     re.I), "tomorrow"),
    (re.compile(r"\byesterday\b",    re.I), "yesterday"),
    (re.compile(r"\bthis\s+week\b",  re.I), "this_week"),
    (re.compile(r"\bnext\s+week\b",  re.I), "next_week"),
    (re.compile(r"\bthis\s+month\b", re.I), "this_month"),
    (re.compile(r"\bmonday\b",       re.I), "monday"),
    (re.compile(r"\btuesday\b",      re.I), "tuesday"),
    (re.compile(r"\bwednesday\b",    re.I), "wednesday"),
    (re.compile(r"\bthursday\b",     re.I), "thursday"),
    (re.compile(r"\bfriday\b",       re.I), "friday"),
    (re.compile(r"\bsaturday\b",     re.I), "saturday"),
    (re.compile(r"\bsunday\b",       re.I), "sunday"),
    # ISO date: 2026-07-20
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), None),
    # Relative: in 2 hours, in 3 days
    (re.compile(r"\bin\s+\d+\s+(hour|day|minute|week)s?\b", re.I), None),
    # Clock: at 3pm, at 15:00
    (re.compile(r"\bat\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b", re.I), None),
]

# Relation words that map to "person" type
_RELATION_WORDS = {
    "sister", "brother", "mother", "father", "mom", "dad", "wife", "husband",
    "partner", "friend", "colleague", "boss", "manager", "intern", "co-founder",
    "mentor", "student", "client", "customer", "vendor", "doctor", "teacher",
}

# Words that suggest a project entity
_PROJECT_INDICATORS = {
    "project", "initiative", "campaign", "product", "feature", "module",
    "sprint", "milestone", "launch", "platform", "system", "app", "tool",
}


# ── Data models ───────────────────────────────────────────────────────────────

@dataclass
class ExtractedEntity:
    """A single entity reference found in the user's text."""
    raw_text: str          # original text: "my sister", "AI Gurukula", "tomorrow"
    entity_type: str       # "person" | "project" | "date" | "company" | "unknown"
    resolved_id: str | None = None   # entity ID if found in EntityMemory
    resolved_name: str | None = None # canonical name if resolved
    confidence: float = 0.8


@dataclass
class Task:
    """The specific WHAT behind an intent.

    Where IntentResult says "email", Task says
    "send project update to Sumedha Bhat about AI Gurukula tomorrow".
    """
    goal: str                                          # human-readable task description
    entities: list[ExtractedEntity] = field(default_factory=list)
    deadline: str | None = None                        # date reference string
    parameters: dict = field(default_factory=dict)     # intent-specific extracted params

    def get_people(self) -> list[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "person"]

    def get_projects(self) -> list[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "project"]

    def get_dates(self) -> list[ExtractedEntity]:
        return [e for e in self.entities if e.entity_type == "date"]

    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "entities": [
                {
                    "raw_text": e.raw_text,
                    "entity_type": e.entity_type,
                    "resolved_id": e.resolved_id,
                    "resolved_name": e.resolved_name,
                }
                for e in self.entities
            ],
            "deadline": self.deadline,
            "parameters": self.parameters,
        }


# ── Extractor ─────────────────────────────────────────────────────────────────

class TaskExtractor:
    """Extracts structured task information from raw text + intent.

    Resolves entity references from the EntityMemoryService when possible.
    If entity memory is not injected, extraction still works — entities
    will have resolved_id=None.

    Args:
        entity_memory: Optional EntityMemoryService for entity resolution.
    """

    def __init__(self, entity_memory=None) -> None:
        self._entity_memory = entity_memory

    def extract(
        self,
        text: str,
        intent: "IntentResult",
        workspace: "BrainStateSnapshot | None" = None,
    ) -> Task:
        """Extract a Task from user text given a classified intent.

        Args:
            text:      Raw user input (same as IntentResult.raw_text).
            intent:    Classified intent from IntentClassifier.
            workspace: Optional BrainState snapshot for context.

        Returns:
            Task with goal, entities, deadline, and parameters.
        """
        entities: list[ExtractedEntity] = []
        deadline: str | None = None
        parameters: dict = {}

        # ── 1. Extract date references ─────────────────────────────────────
        for pattern, label in _DATE_PATTERNS:
            m = pattern.search(text)
            if m:
                raw = m.group(0)
                ref = label or raw
                deadline = ref
                entities.append(ExtractedEntity(
                    raw_text=raw,
                    entity_type="date",
                    resolved_id=None,
                    resolved_name=ref,
                    confidence=0.95,
                ))
                break  # Only take first date reference

        # ── 2. Extract person references ───────────────────────────────────
        person_mentions = self._find_person_mentions(text)
        for raw_mention in person_mentions:
            resolved = self._resolve_person(raw_mention)
            entities.append(resolved)

        # ── 3. Extract project references ──────────────────────────────────
        project_mentions = self._find_project_mentions(text)
        for raw_mention in project_mentions:
            resolved = self._resolve_project(raw_mention)
            entities.append(resolved)

        # ── 4. Extract intent-specific parameters ──────────────────────────
        parameters = self._extract_parameters(text, intent.intent, intent.sub_intent)

        # ── 5. Build goal string ───────────────────────────────────────────
        goal = self._build_goal(text, intent.intent, intent.sub_intent, entities)

        # ── 6. Workspace entity inheritance ───────────────────────────────
        if workspace:
            entities = self._inherit_workspace_context(entities, workspace)

        task = Task(
            goal=goal,
            entities=entities,
            deadline=deadline,
            parameters=parameters,
        )

        logger.debug(
            "TaskExtractor: intent=%s → goal='%s' entities=%d deadline=%s",
            intent.intent,
            goal[:80],
            len(entities),
            deadline,
        )

        return task

    # ── Person detection ───────────────────────────────────────────────────────

    def _find_person_mentions(self, text: str) -> list[str]:
        """Find person references in text."""
        mentions = []

        # "my [relation]" pattern: my sister, my boss, my friend
        my_rel = re.findall(r'\bmy\s+(\w+)\b', text, re.I)
        for rel in my_rel:
            if rel.lower() in _RELATION_WORDS:
                mentions.append(f"my {rel}")

        # Relation words without "my": "tell sister", "email boss"
        lone_rel = re.findall(
            r'\b(' + '|'.join(_RELATION_WORDS) + r')\b', text, re.I
        )
        for rel in lone_rel:
            if f"my {rel.lower()}" not in " ".join(mentions).lower():
                mentions.append(rel.lower())

        # Capitalized names that aren't at sentence start (heuristic)
        # e.g. "email Ekansh", "message Sumedha"
        cap_names = re.findall(r'(?<!\.\s)(?<!\?\s)(?<!!\s)(?<!\n)\b([A-Z][a-z]{2,})\b', text)
        common_words = {
            "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
            "January", "February", "March", "April", "June", "July", "August",
            "September", "October", "November", "December",
            "Gmail", "Google", "Drive", "Notion", "Obsidian", "Gemini",
            "Email", "Calendar", "Sheets", "Docs", "Drive", "JATAYU",
        }
        for name in cap_names:
            if name not in common_words and len(name) > 2:
                # Only add if not already captured as a relation
                if not any(name.lower() in m.lower() for m in mentions):
                    mentions.append(name)

        return list(dict.fromkeys(mentions))  # dedup, preserve order

    def _resolve_person(self, raw_mention: str) -> ExtractedEntity:
        """Attempt to resolve a person mention to a known entity."""
        if self._entity_memory is not None:
            try:
                person = self._entity_memory.get_person(raw_mention)
                if person:
                    return ExtractedEntity(
                        raw_text=raw_mention,
                        entity_type="person",
                        resolved_id=person.get("id"),
                        resolved_name=person.get("name"),
                        confidence=0.9,
                    )
            except Exception as exc:
                logger.debug("Person resolution failed for '%s': %s", raw_mention, exc)

        return ExtractedEntity(
            raw_text=raw_mention,
            entity_type="person",
            resolved_id=None,
            resolved_name=None,
            confidence=0.7,
        )

    # ── Project detection ──────────────────────────────────────────────────────

    def _find_project_mentions(self, text: str) -> list[str]:
        """Find project/initiative references in text."""
        mentions = []

        # Multi-word capitalized phrases (likely proper nouns / project names)
        # e.g. "AI Gurukula", "Captain's Code", "Fifth Veda"
        multiword = re.findall(r'\b([A-Z][a-z\']+(?:\s+[A-Z][a-z\']+)+)\b', text)
        for phrase in multiword:
            # Skip known date/day phrases
            skip = {"Monday Morning", "Tuesday Evening"}
            if phrase not in skip:
                mentions.append(phrase)

        # "project X" pattern
        proj_pattern = re.findall(
            r'\b(?:project|initiative|campaign|platform)\s+([A-Z][A-Za-z0-9\s\']{2,30})',
            text, re.I
        )
        for match in proj_pattern:
            if match.strip() not in mentions:
                mentions.append(match.strip())

        return list(dict.fromkeys(mentions))

    def _resolve_project(self, raw_mention: str) -> ExtractedEntity:
        """Attempt to resolve a project mention to a known entity."""
        if self._entity_memory is not None:
            try:
                project = self._entity_memory.get_project(raw_mention)
                if project:
                    return ExtractedEntity(
                        raw_text=raw_mention,
                        entity_type="project",
                        resolved_id=project.get("id"),
                        resolved_name=project.get("name"),
                        confidence=0.9,
                    )
            except Exception as exc:
                logger.debug("Project resolution failed for '%s': %s", raw_mention, exc)

        return ExtractedEntity(
            raw_text=raw_mention,
            entity_type="project",
            resolved_id=None,
            resolved_name=None,
            confidence=0.65,
        )

    # ── Parameter extraction ───────────────────────────────────────────────────

    def _extract_parameters(
        self, text: str, intent: str, sub_intent: str | None
    ) -> dict:
        """Extract intent-specific structured parameters."""
        params: dict = {}

        if intent == "email":
            # Extract subject hints from "about X" patterns
            about = re.search(r'\babout\s+(.{3,60}?)(?:\s+(?:to|for|by|on)|[,\.]|$)', text, re.I)
            if about:
                params["subject_hint"] = about.group(1).strip()

            # Extract "to [person]" for recipient hints
            to_match = re.search(r'\bto\s+(?:my\s+)?([A-Za-z\s]{2,30}?)(?:\s+about|\s+regarding|\s+on\b|$)', text, re.I)
            if to_match:
                params["recipient_hint"] = to_match.group(1).strip()

        elif intent == "calendar":
            # Duration: "for 30 minutes", "for 1 hour"
            dur = re.search(r'\bfor\s+(\d+)\s+(minute|hour|day)s?\b', text, re.I)
            if dur:
                params["duration"] = f"{dur.group(1)} {dur.group(2)}s"

            # Title: "meeting with X about Y" or "call about Z"
            title_match = re.search(r'\b(?:meeting|call|event)\s+(?:with\s+\w+\s+)?(?:about|regarding|on)\s+(.{3,60}?)(?:[,\.]|$)', text, re.I)
            if title_match:
                params["title_hint"] = title_match.group(1).strip()

        elif intent == "reminder":
            # Extract the reminder text (what to be reminded about)
            remind_match = re.search(r'\bremind\s+me\s+(?:to\s+|about\s+)?(.{3,80}?)(?:\s+(?:at|on|by|in\s+\d)|[,\.]|$)', text, re.I)
            if remind_match:
                params["reminder_text"] = remind_match.group(1).strip()

        elif intent == "document":
            # Document title hints
            title_match = re.search(r'\b(?:called|titled|named)\s+["\']?(.{2,60}?)["\']?(?:\s|$)', text, re.I)
            if title_match:
                params["document_title"] = title_match.group(1).strip()

        return params

    # ── Goal building ──────────────────────────────────────────────────────────

    def _build_goal(
        self,
        text: str,
        intent: str,
        sub_intent: str | None,
        entities: list[ExtractedEntity],
    ) -> str:
        """Build a concise human-readable goal description."""
        if sub_intent:
            base = f"{sub_intent.title()} ({intent})"
        else:
            base = intent.replace("_", " ").title()

        people = [e.resolved_name or e.raw_text for e in entities if e.entity_type == "person"]
        projects = [e.resolved_name or e.raw_text for e in entities if e.entity_type == "project"]
        dates = [e.resolved_name or e.raw_text for e in entities if e.entity_type == "date"]

        parts = [base]
        if people:
            parts.append(f"with {', '.join(people)}")
        if projects:
            parts.append(f"about {', '.join(projects)}")
        if dates:
            parts.append(f"by {dates[0]}")

        return " ".join(parts)

    # ── Workspace context inheritance ──────────────────────────────────────────

    def _inherit_workspace_context(
        self,
        entities: list[ExtractedEntity],
        snapshot: "BrainStateSnapshot",
    ) -> list[ExtractedEntity]:
        """Add workspace context entities if not already present."""
        ws = snapshot.workspace
        existing_ids = {e.resolved_id for e in entities if e.resolved_id}

        # Inherit active project if none extracted and workspace has one
        if ws.current_project:
            proj_id = ws.current_project.get("id")
            if proj_id and proj_id not in existing_ids:
                # Only inherit if the project is explicitly mentioned or query is ambiguous
                proj_name = ws.current_project.get("name", "").lower()
                if proj_name in snapshot.workspace.current_task or "" and False:
                    # Intentionally conservative — don't auto-inject project
                    pass

        return entities
