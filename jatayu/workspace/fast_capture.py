"""FastCapture — intent-gated message classifier.

Only activates when the user's message explicitly indicates they want
to save something. Normal conversation is NOT captured.

Trigger vocabulary (per user design spec):
    "store this", "remember this", "add this to <project>",
    "ideas for <project>", "note this", "create tasks",
    "remind me", "todo", "action items", "meeting notes",
    "note:", "task:", "idea:", "decision:"

Once triggered, each bullet point or sentence is classified into:
    task | reminder | note | meeting | decision | idea | deadline

If the destination workspace is ambiguous, asks a clarifying question
before saving. If confidence < 0.65, returns requires_clarification=True.

Design: NEVER calls the LLM. NEVER makes network requests. Pure regex rules.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from jatayu.workspace.models import (
    CaptureItem,
    CaptureResult,
    CaptureType,
    NoteType,
    WorkspaceNote,
    WorkspaceTask,
    TaskStatus,
    _now,
    _new_id,
)

if TYPE_CHECKING:
    from jatayu.workspace.service import WorkspaceService

logger = logging.getLogger(__name__)

# ── Minimum confidence to auto-save without clarifying ────────────────────────
MIN_CONFIDENCE = 0.65

# ── Explicit trigger patterns — message MUST match one of these ───────────────
_TRIGGER_PATTERNS = [
    re.compile(r"\bstore\s+this\b", re.I),
    re.compile(r"\bremember\s+this\b", re.I),
    re.compile(r"\badd\s+this\s+to\b", re.I),
    re.compile(r"\bideas?\s+for\b", re.I),
    re.compile(r"\bnote\s+this\b", re.I),
    re.compile(r"\bcreate\s+tasks?\b", re.I),
    re.compile(r"\bremind\s+me\b", re.I),
    re.compile(r"\btodo\b", re.I),
    re.compile(r"\bto.do\b", re.I),
    re.compile(r"\baction\s+items?\b", re.I),
    re.compile(r"\bmeeting\s+notes?\b", re.I),
    re.compile(r"^note\s*:", re.I | re.MULTILINE),
    re.compile(r"^task\s*:", re.I | re.MULTILINE),
    re.compile(r"^idea\s*:", re.I | re.MULTILINE),
    re.compile(r"^decision\s*:", re.I | re.MULTILINE),
    re.compile(r"^reminder\s*:", re.I | re.MULTILINE),
    re.compile(r"^deadline\s*:", re.I | re.MULTILINE),
    re.compile(r"^-\s+", re.MULTILINE),          # Bullet lists
    re.compile(r"^\d+\.\s+", re.MULTILINE),      # Numbered lists
]

# ── Per-type classification rules ─────────────────────────────────────────────
_TYPE_RULES: list[tuple[re.Pattern, str, float]] = []

def _add(pattern: str, capture_type: str, confidence: float = 0.85) -> None:
    _TYPE_RULES.append((re.compile(pattern, re.I), capture_type, confidence))

# Task patterns
_add(r"^task\s*:\s*",                            CaptureType.TASK,     0.97)
_add(r"\bneed\s+to\b",                           CaptureType.TASK,     0.88)
_add(r"\bshould\b",                              CaptureType.TASK,     0.75)
_add(r"\bmust\b",                                CaptureType.TASK,     0.85)
_add(r"\bfinish\b",                              CaptureType.TASK,     0.88)
_add(r"\bcomplete\b",                            CaptureType.TASK,     0.85)
_add(r"\bbuild\b",                               CaptureType.TASK,     0.82)
_add(r"\bcreate\b",                              CaptureType.TASK,     0.78)
_add(r"\bdo\b",                                  CaptureType.TASK,     0.72)
_add(r"\bsend\b",                                CaptureType.TASK,     0.78)
_add(r"\bfollow\s+up\b",                         CaptureType.TASK,     0.88)
_add(r"\bwrite\b",                               CaptureType.TASK,     0.78)
_add(r"\bfix\b",                                 CaptureType.TASK,     0.85)
_add(r"\bprepare\b",                             CaptureType.TASK,     0.82)
_add(r"\breview\b",                              CaptureType.TASK,     0.78)
_add(r"\bschedule\b",                            CaptureType.TASK,     0.82)
_add(r"\bupdate\b",                              CaptureType.TASK,     0.75)
_add(r"\bcheck\b",                               CaptureType.TASK,     0.72)
_add(r"\bimplement\b",                           CaptureType.TASK,     0.88)
_add(r"\blaunch\b",                              CaptureType.TASK,     0.85)
_add(r"\btest\b",                                CaptureType.TASK,     0.78)
_add(r"\bdeploy\b",                              CaptureType.TASK,     0.85)

# Reminder patterns (override task if more specific)
_add(r"^reminder\s*:\s*",                        CaptureType.REMINDER, 0.97)
_add(r"\bremind\s+me\b",                         CaptureType.REMINDER, 0.97)
_add(r"\bdon'?t\s+forget\b",                     CaptureType.REMINDER, 0.93)
_add(r"\bremember\s+to\b",                       CaptureType.REMINDER, 0.90)
_add(r"\bby\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|tomorrow|tonight|eod|end\s+of\s+day)\b", CaptureType.REMINDER, 0.80)

# Deadline patterns
_add(r"^deadline\s*:\s*",                        CaptureType.DEADLINE, 0.97)
_add(r"\bdue\s+(?:by|on)\b",                     CaptureType.DEADLINE, 0.95)
_add(r"\bdeadline\b",                            CaptureType.DEADLINE, 0.92)
_add(r"\bsubmit\s+by\b",                         CaptureType.DEADLINE, 0.92)
_add(r"\blaunch\s+(?:by|on)\b",                  CaptureType.DEADLINE, 0.88)

# Meeting patterns
_add(r"\bmeeting\s+notes?\b",                    CaptureType.MEETING,  0.97)
_add(r"\bcall\s+(?:with|to)\b",                  CaptureType.MEETING,  0.85)
_add(r"\bsync\s+with\b",                         CaptureType.MEETING,  0.88)
_add(r"\bstandup\b",                             CaptureType.MEETING,  0.90)
_add(r"\bdiscussion\s+with\b",                   CaptureType.MEETING,  0.85)
_add(r"\bmet\s+with\b",                          CaptureType.MEETING,  0.88)
_add(r"\bmeeting\s+with\b",                      CaptureType.MEETING,  0.90)

# Decision patterns
_add(r"^decision\s*:\s*",                        CaptureType.DECISION, 0.97)
_add(r"\bwe\s+decided\b",                        CaptureType.DECISION, 0.95)
_add(r"\bdecided\s+to\b",                        CaptureType.DECISION, 0.93)
_add(r"\bagreed\s+to\b",                         CaptureType.DECISION, 0.92)
_add(r"\bwill\s+go\s+with\b",                    CaptureType.DECISION, 0.90)
_add(r"\bfinal\s+decision\b",                    CaptureType.DECISION, 0.92)
_add(r"\bgoing\s+with\b",                        CaptureType.DECISION, 0.82)

# Idea patterns
_add(r"^idea\s*:\s*",                            CaptureType.IDEA,     0.97)
_add(r"\bidea\s*:",                              CaptureType.IDEA,     0.95)
_add(r"\bwhat\s+if\b",                           CaptureType.IDEA,     0.82)
_add(r"\bmaybe\s+we\b",                          CaptureType.IDEA,     0.78)
_add(r"\bcould\s+we\b",                          CaptureType.IDEA,     0.75)
_add(r"\bthinking\s+(?:about|of)\b",             CaptureType.IDEA,     0.78)
_add(r"\bwhat\s+about\b",                        CaptureType.IDEA,     0.72)
_add(r"\bconsidering\b",                         CaptureType.IDEA,     0.75)

# Note/FYI patterns (catch-all if no stronger signal)
_add(r"^note\s*:\s*",                            CaptureType.NOTE,     0.97)
_add(r"\bfyi\b",                                 CaptureType.NOTE,     0.90)
_add(r"\bfor\s+reference\b",                     CaptureType.NOTE,     0.88)
_add(r"\bjust\s+(?:noted?|noting)\b",            CaptureType.NOTE,     0.85)
_add(r"\binfo\s*:",                              CaptureType.NOTE,     0.88)
_add(r"\bcontext\s*:",                           CaptureType.NOTE,     0.85)

# ── Date extraction patterns ───────────────────────────────────────────────────
_DATE_PATTERNS = [
    (re.compile(r"\btoday\b", re.I),       "today"),
    (re.compile(r"\btomorrow\b", re.I),    "tomorrow"),
    (re.compile(r"\bnext\s+week\b", re.I), "next_week"),
    (re.compile(r"\bmonday\b", re.I),      "monday"),
    (re.compile(r"\btuesday\b", re.I),     "tuesday"),
    (re.compile(r"\bwednesday\b", re.I),   "wednesday"),
    (re.compile(r"\bthursday\b", re.I),    "thursday"),
    (re.compile(r"\bfriday\b", re.I),      "friday"),
    (re.compile(r"\beod\b", re.I),         "today"),
    (re.compile(r"\bend\s+of\s+(?:the\s+)?day\b", re.I), "today"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}\b"), None),      # ISO date
    (re.compile(r"\bin\s+\d+\s+days?\b", re.I), None), # relative
]

# ── Project mention patterns ───────────────────────────────────────────────────
_PROJECT_FOR = re.compile(
    r"\b(?:for|to|in|on|about|regarding)\s+([A-Z][A-Za-z\s\']{2,30}?)(?:\s+project)?\b"
)
_ADD_TO = re.compile(r"\badd\s+this\s+to\s+([A-Z][A-Za-z\s\']{2,30})\b", re.I)


# ── FastCapture ────────────────────────────────────────────────────────────────

class FastCapture:
    """Intent-gated message classifier and workspace attacher.

    Args:
        workspace_service: WorkspaceService for workspace resolution and saving.
    """

    def __init__(self, workspace_service: "WorkspaceService | None" = None) -> None:
        self._ws_service = workspace_service

    def should_capture(self, text: str) -> bool:
        """Return True if this message contains a capture trigger phrase."""
        for pattern in _TRIGGER_PATTERNS:
            if pattern.search(text):
                return True
        return False

    def capture(self, text: str, session_context: dict | None = None) -> CaptureResult:
        """Classify a message into workspace items.

        Args:
            text:            Raw user message.
            session_context: Optional dict with 'active_project' entity_id hint.

        Returns:
            CaptureResult with classified items and workspace assignment.
        """
        if not self.should_capture(text):
            return CaptureResult(
                raw_text=text,
                requires_clarification=False,
            )

        # ── 1. Detect target workspace ──────────────────────────────────────
        workspace_id, workspace_name, requires_clarification, clarify_q = \
            self._resolve_workspace(text, session_context)

        # If ambiguous and we can't resolve → ask before capturing anything
        if requires_clarification and not workspace_id:
            return CaptureResult(
                raw_text=text,
                requires_clarification=True,
                clarification_question=clarify_q,
            )

        # ── 2. Detect entity refs ──────────────────────────────────────────
        detected_entities = self._detect_entities(text)
        entity_refs = [e.get("id", "") for e in detected_entities if e.get("id")]

        # ── 3. Split into sentences / bullets ─────────────────────────────
        segments = self._split_segments(text)

        # ── 4. Classify each segment ───────────────────────────────────────
        items: list[CaptureItem] = []
        for segment in segments:
            if not segment.strip() or len(segment.strip()) < 4:
                continue
            item = self._classify_segment(segment, entity_refs, workspace_id)
            if item:
                items.append(item)

        # ── 5. Auto-save to workspace if we have one ───────────────────────
        if workspace_id and self._ws_service and items:
            self._attach_to_workspace(workspace_id, items)

        return CaptureResult(
            items=items,
            detected_workspace_id=workspace_id,
            detected_workspace_name=workspace_name,
            detected_entities=detected_entities,
            requires_clarification=False,
            raw_text=text,
        )

    def _resolve_workspace(
        self,
        text: str,
        session_context: dict | None,
    ) -> tuple[str | None, str | None, bool, str | None]:
        """Try to identify the target workspace from text + session context.

        Returns: (workspace_id, workspace_name, requires_clarification, clarify_q)
        """
        if not self._ws_service:
            return None, None, False, None

        # Try "add this to <Project>" pattern
        m = _ADD_TO.search(text)
        if m:
            project_name = m.group(1).strip()
            ws = self._find_workspace_by_name(project_name)
            if ws:
                return ws.id, ws.name, False, None
            # Name found but no workspace — ask to create
            return None, project_name, True, (
                f"I see you want to add this to '{project_name}', but I don't have a workspace "
                f"for that project yet. Should I create one?"
            )

        # Try "for <Project>" pattern
        m = _PROJECT_FOR.search(text)
        if m:
            project_name = m.group(1).strip()
            ws = self._find_workspace_by_name(project_name)
            if ws:
                return ws.id, ws.name, False, None

        # Use session context (active_project from BrainState)
        if session_context:
            active_entity_id = session_context.get("active_project_entity_id")
            if active_entity_id:
                ws = self._ws_service.find_by_entity(active_entity_id)
                if ws:
                    return ws.id, ws.name, False, None

        # Multiple workspaces → ask which one
        all_workspaces = self._ws_service.list_summaries()
        if len(all_workspaces) == 0:
            return None, None, True, (
                "Which project should I attach this to? (You haven't set up any workspaces yet.)"
            )
        elif len(all_workspaces) == 1:
            # Only one workspace — use it without asking
            ws_id = all_workspaces[0]["id"]
            ws_name = all_workspaces[0]["name"]
            return ws_id, ws_name, False, None
        else:
            names = ", ".join(f"'{w['name']}'" for w in all_workspaces[:5])
            return None, None, True, (
                f"Which project should I attach this to? Active workspaces: {names}"
            )

    def _find_workspace_by_name(self, name: str) -> "Workspace | None":
        """Find a workspace by fuzzy name match."""
        if not self._ws_service:
            return None
        from difflib import SequenceMatcher
        best, best_score = None, 0.0
        for ws in self._ws_service.list_all():
            score = SequenceMatcher(None, name.lower(), ws.name.lower()).ratio()
            if score > best_score and score > 0.6:
                best_score = score
                best = ws
        return best

    def _detect_entities(self, text: str) -> list[dict]:
        """Detect known entities in the text."""
        try:
            from jatayu.memory.entities import detect_entities_in_text
            return detect_entities_in_text(text)
        except Exception:
            return []

    def _split_segments(self, text: str) -> list[str]:
        """Split text into classifiable segments (bullets, sentences, lines)."""
        segments = []

        # Try bullet/numbered list parsing first
        bullet_pattern = re.compile(r"^[-•*]\s+(.+)$|^\d+\.\s+(.+)$", re.MULTILINE)
        bullets = bullet_pattern.findall(text)
        if bullets:
            for g1, g2 in bullets:
                segment = (g1 or g2).strip()
                if segment:
                    segments.append(segment)
            if segments:
                return segments

        # Fall back to line-by-line splitting
        for line in text.splitlines():
            line = line.strip()
            # Remove common prefixes
            line = re.sub(r"^(?:note|task|idea|decision|reminder|deadline)\s*:\s*", "", line, flags=re.I)
            if line and len(line) > 4:
                segments.append(line)

        # If single-line message, keep as one segment
        if not segments and text.strip():
            segments = [text.strip()]

        return segments

    def _classify_segment(
        self,
        segment: str,
        entity_refs: list[str],
        workspace_id: str | None,
    ) -> CaptureItem | None:
        """Classify a single segment into a CaptureItem."""
        best_type = CaptureType.NOTE
        best_confidence = 0.0

        for pattern, capture_type, confidence in _TYPE_RULES:
            if pattern.search(segment):
                if confidence > best_confidence:
                    best_confidence = confidence
                    best_type = capture_type

        # Default: everything is a note with low confidence
        if best_confidence == 0.0:
            best_type = CaptureType.NOTE
            best_confidence = 0.6

        # Extract due date
        due_date = None
        for pattern, label in _DATE_PATTERNS:
            m = pattern.search(segment)
            if m:
                due_date = label or m.group(0)
                break

        return CaptureItem(
            type=best_type,
            content=segment.strip(),
            confidence=round(best_confidence, 2),
            entity_refs=entity_refs,
            workspace_id=workspace_id,
            due_date=due_date,
            source_text=segment,
        )

    def _attach_to_workspace(
        self, workspace_id: str, items: list[CaptureItem]
    ) -> None:
        """Persist classified items to the workspace."""
        if not self._ws_service:
            return

        for item in items:
            if item.confidence < MIN_CONFIDENCE:
                logger.debug(
                    "FastCapture: skipping low-confidence item (%.2f): %s",
                    item.confidence, item.content[:60]
                )
                continue

            try:
                if item.type in (CaptureType.TASK, CaptureType.DEADLINE):
                    task = WorkspaceTask.new(
                        title=item.content[:120],
                        due_date=item.due_date,
                        entity_refs=item.entity_refs,
                        workspace_id=workspace_id,
                        source="fast_capture",
                        priority=2 if item.type == CaptureType.DEADLINE else 3,
                    )
                    self._ws_service.add_task(workspace_id, task)

                elif item.type == CaptureType.REMINDER:
                    note = WorkspaceNote.new(
                        content=item.content,
                        note_type=NoteType.REMINDER,
                        entity_refs=item.entity_refs,
                        workspace_id=workspace_id,
                        source="fast_capture",
                    )
                    self._ws_service.add_note(workspace_id, note)

                elif item.type == CaptureType.DECISION:
                    note = WorkspaceNote.new(
                        content=item.content,
                        note_type=NoteType.DECISION,
                        entity_refs=item.entity_refs,
                        workspace_id=workspace_id,
                        source="fast_capture",
                    )
                    self._ws_service.add_note(workspace_id, note)

                elif item.type == CaptureType.IDEA:
                    note = WorkspaceNote.new(
                        content=item.content,
                        note_type=NoteType.IDEA,
                        entity_refs=item.entity_refs,
                        workspace_id=workspace_id,
                        source="fast_capture",
                    )
                    self._ws_service.add_note(workspace_id, note)

                elif item.type == CaptureType.MEETING:
                    note = WorkspaceNote.new(
                        content=item.content,
                        note_type=NoteType.MEETING_NOTE,
                        entity_refs=item.entity_refs,
                        workspace_id=workspace_id,
                        source="fast_capture",
                    )
                    self._ws_service.add_note(workspace_id, note)

                else:  # NOTE fallback
                    note = WorkspaceNote.new(
                        content=item.content,
                        note_type=NoteType.NOTE,
                        entity_refs=item.entity_refs,
                        workspace_id=workspace_id,
                        source="fast_capture",
                    )
                    self._ws_service.add_note(workspace_id, note)

            except Exception as exc:
                logger.error("FastCapture: failed to save item to workspace: %s", exc)
