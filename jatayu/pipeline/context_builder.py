"""Context Builder — assembles a bounded, filtered context window before any LLM call.

Reads from BrainState and ConversationService only.
Produces a ContextPacket with filtered tools — never exposes all 40+ tools.

Design rules (from Brain Contract v1):
- Reads from: BrainState, ConversationService, EntityMemory, FlatMemory, ToolRegistry
- Writes to: nothing
- Never calls the LLM
- Never exposes more tools than INTENT_TOOL_GROUPS[intent] specifies
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jatayu.pipeline.intent_classifier import IntentResult, INTENT_TOOL_GROUPS
    from jatayu.pipeline.task_extractor import Task
    from jatayu.pipeline.brain_state import BrainStateSnapshot

logger = logging.getLogger(__name__)

# Max conversation turns to inject (keeps context window bounded)
MAX_HISTORY_TURNS = 20


# ── Output model ───────────────────────────────────────────────────────────────

@dataclass
class ContextPacket:
    """The fully assembled context handed to the Brain for an LLM call.

    This is the only thing the Brain needs to generate a response.
    It contains everything relevant and nothing irrelevant.
    """
    system_prompt: str                               # complete system instruction
    conversation_history: list = field(default_factory=list)  # last N turns from DB
    workspace_summary: str = ""                      # current Workspace as text
    relevant_entities: list[dict] = field(default_factory=list)  # only task-relevant
    relevant_memories: str = ""                      # filtered memory block
    tools_to_expose: list[str] | None = None         # None = all, [] = none, [...] = filtered
    model_hint: str | None = None                    # suggested model
    intent: str = "unknown"
    task_goal: str = ""

    def to_dict(self) -> dict:
        return {
            "intent": self.intent,
            "task_goal": self.task_goal,
            "workspace_summary": self.workspace_summary,
            "relevant_entity_count": len(self.relevant_entities),
            "tools_exposed": (
                len(self.tools_to_expose) if self.tools_to_expose is not None else "all"
            ),
            "history_turns": len(self.conversation_history),
        }


# ── Builder ────────────────────────────────────────────────────────────────────

class ContextBuilder:
    """Assembles a ContextPacket from all available sources.

    Args:
        base_system_prompt: The base system_prompt from config.yaml.
        entity_memory:      EntityMemoryService instance (optional).
        flat_memory:        ContextRetriever instance (optional).
        tool_registry:      ToolRegistry instance (for validating tool names).
        conv_service:       ConversationService for conversation history.
        graph_retriever:    GraphContextRetriever instance (optional).
    """

    def __init__(
        self,
        base_system_prompt: str,
        entity_memory=None,
        flat_memory=None,
        tool_registry=None,
        conv_service=None,
        graph_retriever=None,
    ) -> None:
        self._base_prompt = base_system_prompt
        self._entity_memory = entity_memory
        self._flat_memory = flat_memory
        self._tool_registry = tool_registry
        self._conv_service = conv_service
        self._graph_retriever = graph_retriever

    def build(
        self,
        intent: "IntentResult",
        task: "Task",
        snapshot: "BrainStateSnapshot",
        conversation_id: str | None = None,
    ) -> ContextPacket:
        """Build a complete ContextPacket for the given intent and task.

        Args:
            intent:          Classified intent.
            task:            Extracted task with entities.
            snapshot:        Current BrainState snapshot.
            conversation_id: Active conversation ID for history lookup.

        Returns:
            ContextPacket ready to pass to Brain.
        """
        # ── 1. Workspace summary ───────────────────────────────────────────
        workspace_summary = snapshot.workspace.to_summary()

        # ── 2. Relevant entities and Graph Context ─────────────────────────
        primary_entities, graph_ctx = self._get_relevant_entities_and_graph(task)

        # ── 3. Memory block (filtered if possible) ─────────────────────────
        relevant_memories = self._get_relevant_memories(intent)

        # ── 4. Conversation history (last N turns) ─────────────────────────
        history = self._get_conversation_history(conversation_id)

        # ── 5. Tool filtering ──────────────────────────────────────────────
        tools_to_expose = self._get_filtered_tools(intent)

        # ── 6. System prompt assembly ──────────────────────────────────────
        system_prompt = self._build_system_prompt(
            workspace_summary, primary_entities, graph_ctx, relevant_memories, intent
        )

        packet = ContextPacket(
            system_prompt=system_prompt,
            conversation_history=history,
            workspace_summary=workspace_summary,
            relevant_entities=primary_entities,
            relevant_memories=relevant_memories,
            tools_to_expose=tools_to_expose,
            model_hint=None,  # set by ModelRouter later
            intent=intent.intent,
            task_goal=task.goal,
        )

        logger.debug(
            "ContextBuilder: intent=%s tools=%s entities=%d history=%d turns",
            intent.intent,
            len(tools_to_expose) if tools_to_expose is not None else "all",
            len(primary_entities),
            len(history),
        )

        return packet

    # ── Entity & Graph retrieval ───────────────────────────────────────────────

    def _get_relevant_entities_and_graph(self, task: "Task") -> tuple[list[dict], "GraphContext | None"]:
        """Fetch entity records and expanded graph context."""
        entities = []
        if self._entity_memory is None:
            return entities, None

        seen_ids: set[str] = set()
        primary_ids: list[str] = []

        for extracted in task.entities:
            if extracted.resolved_id and extracted.resolved_id not in seen_ids:
                try:
                    record = None
                    if extracted.entity_type == "person":
                        record = self._entity_memory.get_person(extracted.resolved_name or extracted.raw_text)
                    elif extracted.entity_type == "project":
                        record = self._entity_memory.get_project(extracted.resolved_name or extracted.raw_text)

                    if record:
                        entities.append(record)
                        seen_ids.add(extracted.resolved_id)
                        primary_ids.append(record.get("id"))
                except Exception as exc:
                    logger.debug("Entity fetch failed for '%s': %s", extracted.raw_text, exc)

            elif not extracted.resolved_id:
                try:
                    record = None
                    if extracted.entity_type == "person":
                        record = self._entity_memory.get_person(extracted.raw_text)
                    elif extracted.entity_type == "project":
                        record = self._entity_memory.get_project(extracted.raw_text)

                    if record and record.get("id") not in seen_ids:
                        entities.append(record)
                        seen_ids.add(record.get("id", ""))
                        primary_ids.append(record.get("id"))
                except Exception:
                    pass
                    
        graph_ctx = None
        if self._graph_retriever and primary_ids:
            graph_ctx = self._graph_retriever.retrieve(primary_ids, max_depth=1)

        return entities, graph_ctx

    # ── Memory retrieval ───────────────────────────────────────────────────────

    def _get_relevant_memories(self, intent: "IntentResult") -> str:
        """Retrieve relevant memory facts for this intent."""
        if self._flat_memory is None:
            return ""
        try:
            # For now: full retrieval (same as current behavior).
            # Phase 3 will add intent-based filtering.
            return self._flat_memory.retrieve_for_prompt(intent.raw_text)
        except Exception as exc:
            logger.warning("Memory retrieval failed: %s", exc)
            return ""

    # ── Conversation history ───────────────────────────────────────────────────

    def _get_conversation_history(self, conversation_id: str | None) -> list:
        """Fetch recent conversation turns from ConversationService."""
        if self._conv_service is None or not conversation_id:
            return []
        try:
            messages = self._conv_service.get_recent_messages(
                conversation_id, limit=MAX_HISTORY_TURNS
            )
            # Return as simple dicts for compatibility with Brain
            return [
                {"role": m.role, "content": m.content}
                for m in messages
            ]
        except Exception as exc:
            logger.warning("History retrieval failed: %s", exc)
            return []

    # ── Tool filtering ─────────────────────────────────────────────────────────

    def _get_filtered_tools(self, intent: "IntentResult") -> list[str] | None:
        """Return the set of tools to expose for this intent.

        Returns:
            None  = expose all tools (fallback / unknown intent)
            []    = expose no tools (pure conversation)
            [...] = filtered list of tool names
        """
        # Import here to avoid circular at module level
        from jatayu.pipeline.intent_classifier import INTENT_TOOL_GROUPS

        tool_group = INTENT_TOOL_GROUPS.get(intent.intent)

        # None = unknown intent → expose all (preserve current fallback behavior)
        if tool_group is None:
            return None

        # Empty list → conversation intent, no tools needed
        if not tool_group:
            return []

        # If no ToolRegistry, return the group as-is
        if self._tool_registry is None:
            return tool_group

        # Validate against registered tools (only expose tools that actually exist)
        registered = {t.name for t in self._tool_registry.list_tools()}
        valid = [t for t in tool_group if t in registered]

        if len(valid) < len(tool_group):
            missing = set(tool_group) - set(valid)
            logger.debug("ContextBuilder: tools not registered (will skip): %s", missing)

        return valid

    # ── System prompt ──────────────────────────────────────────────────────────

    def _build_system_prompt(
        self,
        workspace_summary: str,
        primary_entities: list[dict],
        graph_ctx: "GraphContext | None",
        memory_block: str,
        intent: "IntentResult",
    ) -> str:
        """Assemble the full system prompt for this turn."""
        parts = [self._base_prompt]

        # Workspace context injection
        if workspace_summary:
            parts.append(
                "\n\n## Current Workspace\n"
                + workspace_summary
            )

        # Entity and Graph context injection
        if primary_entities or (graph_ctx and graph_ctx.related_entities):
            entity_lines = ["## Relevant Knowledge Graph"]
            
            def _format_entity(e):
                etype = e.get("type", "entity")
                name = e.get("name", "Unknown")
                if etype == "person":
                    email = e.get("email", "")
                    phone = e.get("phone", "")
                    relation = e.get("relation", "")
                    line = f"- {name}"
                    if relation:
                        line += f" ({relation})"
                    if email:
                        line += f" | Email: {email}"
                    if phone:
                        line += f" | Phone: {phone}"
                    return line
                elif etype == "project":
                    status = e.get("status", "")
                    line = f"- Project: {name}"
                    if status:
                        line += f" [{status}]"
                    return line
                else:
                    return f"- {name} [{etype}]"
                    
            if primary_entities:
                entity_lines.append("### Primary Entities Mentions")
                for e in primary_entities:
                    entity_lines.append(_format_entity(e))
                    
            if graph_ctx:
                if graph_ctx.related_entities:
                    entity_lines.append("\n### Related Entities (Graph Neighbors)")
                    for e in graph_ctx.related_entities:
                        entity_lines.append(_format_entity(e))
                        
                if graph_ctx.edges:
                    entity_lines.append("\n### Known Relationships")
                    # Need a quick way to map id to name
                    # We can use the cached names from edges
                    for edge in graph_ctx.edges:
                        s_name = edge.source_name or edge.source_id
                        t_name = edge.target_name or edge.target_id
                        entity_lines.append(f"- {s_name} [{edge.edge_type}] {t_name}")

            parts.append("\n\n" + "\n".join(entity_lines))

        # Flat memory block
        if memory_block:
            parts.append("\n" + memory_block)

        return "".join(parts)
