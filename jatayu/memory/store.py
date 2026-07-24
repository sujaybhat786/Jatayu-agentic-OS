"""Long-term memory store — durable facts that survive restarts.

Facts are stored in data/memory.json as plain, human-readable entries.
Each fact is a single clear statement (not a command). The store is
loaded into the system prompt at startup so the model walks into every
conversation already knowing them.

The assistant can manage its own memory via tools: remember, update,
and forget. The user can also open memory.json and edit it directly.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry
from jatayu.memory.domains import map_legacy_category
from jatayu.memory import entities as entity_store


def _memory_path() -> Path:
    return Path(get_config()["data_dir"]) / "memory.json"


def _load() -> list[dict]:
    path = _memory_path()
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            # Auto-migrate legacy data
            migrated = False
            for entry in data:
                if "domain" not in entry:
                    entry["domain"] = map_legacy_category(entry.get("category", "general"))
                    migrated = True
            if migrated:
                _save(data)
            return data
    return []


def _save(facts: list[dict]) -> None:
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(facts, f, indent=2, default=str)


# ------------------------------------------------------------------ #
#  Public API — used by the brain at startup                          #
# ------------------------------------------------------------------ #

def load_memory_for_prompt() -> str:
    """Load all stored facts as a formatted block for the system prompt.

    Returns:
        A string ready to append to the system prompt, or empty string
        if no facts are stored.
    """
    from jatayu.memory.retriever import ContextRetriever
    return ContextRetriever().retrieve_for_prompt()


# ------------------------------------------------------------------ #
#  Tool handlers                                                      #
# ------------------------------------------------------------------ #

def remember(fact: str, category: str = "general") -> str:
    """Store a new fact about the user or their preferences.

    Args:
        fact: A single, clear statement — e.g. "Prefers morning meetings."
        category: Optional grouping — e.g. "preference", "identity", "work".
    """
    facts = _load()

    # Check for near-duplicates
    for existing in facts:
        if existing["fact"].lower().strip() == fact.lower().strip():
            return f"I already have that noted: \"{existing['fact']}\""

    entry = {
        "id": uuid.uuid4().hex[:8],
        "fact": fact,
        "category": category,
        "domain": map_legacy_category(category),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    facts.append(entry)
    _save(facts)
    return f"✅ Remembered: \"{fact}\""


def list_memories() -> str:
    """Show all stored facts."""
    facts = _load()
    if not facts:
        return "No memories stored yet."

    lines = []
    for f in facts:
        lines.append(f"• [{f['id']}] ({f.get('category', 'general')}) {f['fact']}")
    return "\n".join(lines)


def update_memory(memory_id: str, new_fact: str) -> str:
    """Update an existing fact.

    Args:
        memory_id: The id of the fact to update.
        new_fact: The corrected or updated statement.
    """
    facts = _load()
    for f in facts:
        if f["id"] == memory_id:
            old = f["fact"]
            f["fact"] = new_fact
            f["updated_at"] = datetime.now().isoformat(timespec="seconds")
            _save(facts)
            return f"✅ Updated: \"{old}\" → \"{new_fact}\""
    return f"No memory found with id '{memory_id}'."


def forget(memory_id: str) -> str:
    """Remove a stored fact.

    Args:
        memory_id: The id of the fact to remove.
    """
    facts = _load()
    for i, f in enumerate(facts):
        if f["id"] == memory_id:
            removed = facts.pop(i)
            _save(facts)
            return f"✅ Forgot: \"{removed['fact']}\""
    return f"No memory found with id '{memory_id}'."


# ------------------------------------------------------------------ #
#  Entity Memory Tool Handlers                                        #
# ------------------------------------------------------------------ #

def _tool_remember_entity(
    type: str,
    name: str,
    relation: str = "",
    email: str = "",
    phone: str = "",
    profession: str = "",
    aliases: str = "",  # comma-separated string for Gemini tool compat
    notes: str = "",
    status: str = "active",
) -> str:
    """Create or update a Person or Project entity record."""
    aliases_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
    
    if type.lower() == "person":
        entity, was_created = entity_store.upsert_person(
            name=name,
            relation=relation or None,
            email=email or None,
            phone=phone or None,
            profession=profession or None,
            aliases=aliases_list or None,
            notes=notes or None,
        )
        action = "created a record" if was_created else "updated the record"
        return f"✅ Got it — I've {action} for {entity['name']}."
    elif type.lower() == "project":
        entity, was_created = entity_store.upsert_project(
            name=name,
            aliases=aliases_list or None,
            status=status or "active",
            notes=notes or None,
        )
        action = "added" if was_created else "updated"
        return f"✅ Got it — I've {action} {entity['name']} as a project."
    else:
        return f"Unknown entity type '{type}'. Use 'person' or 'project'."


def _tool_get_person(name: str) -> str:
    """Look up a stored person by name, alias, or relation."""
    entity = entity_store.get_person(name)
    if not entity:
        return f"No person record found matching '{name}'."
    parts = [f"Name: {entity.get('name','?')}"]
    if entity.get("relation"): parts.append(f"Relation: {entity['relation']}")
    if entity.get("email"): parts.append(f"Email: {entity['email']}")
    if entity.get("phone"): parts.append(f"Phone: {entity['phone']}")
    if entity.get("profession"): parts.append(f"Profession: {entity['profession']}")
    if entity.get("notes"): parts.append(f"Notes: {entity['notes']}")
    if entity.get("aliases"): parts.append(f"Also known as: {', '.join(entity['aliases'])}")
    return "\n".join(parts)


def _tool_get_project(name: str) -> str:
    """Look up a stored project by name or alias."""
    entity = entity_store.get_project(name)
    if not entity:
        return f"No project record found matching '{name}'."
    parts = [f"Project: {entity.get('name','?')}"]
    if entity.get("status"): parts.append(f"Status: {entity['status']}")
    if entity.get("notes"): parts.append(f"Notes: {entity['notes']}")
    if entity.get("aliases"): parts.append(f"Also known as: {', '.join(entity['aliases'])}")
    return "\n".join(parts)


def link_entities(source_name: str, target_name: str, relationship_type: str) -> str:
    """Create a relationship edge between two entities in the knowledge graph."""
    from jatayu.memory.graph.store import RelationshipGraph
    from jatayu.memory.graph.registry import relationship_registry
    
    src_rec = entity_store.get_person(source_name) or entity_store.get_project(source_name)
    tgt_rec = entity_store.get_person(target_name) or entity_store.get_project(target_name)
    
    if not src_rec:
        return f"Could not find source entity '{source_name}'. Call remember_entity first."
    if not tgt_rec:
        return f"Could not find target entity '{target_name}'. Call remember_entity first."
        
    if not relationship_registry.is_valid(relationship_type):
        valid = ", ".join(relationship_registry.list_types())
        return f"Invalid relationship '{relationship_type}'. Valid types: {valid}"
        
    graph = RelationshipGraph()
    graph.add_edge(
        src_rec["id"], tgt_rec["id"], relationship_type, 
        source_name=src_rec.get("name", source_name), 
        target_name=tgt_rec.get("name", target_name)
    )
    return f"✅ Linked: {src_rec.get('name', source_name)} -> {relationship_type} -> {tgt_rec.get('name', target_name)}"

# ------------------------------------------------------------------ #
#  Registration                                                       #
# ------------------------------------------------------------------ #

def register(registry: ToolRegistry) -> None:
    """Register memory tools."""
    registry.register(Tool(
        name="remember",
        description="Store a durable fact about the user or their world. Use when the user shares a preference, identity detail, or asks you to remember something. Store one clear fact per call, not lengthy notes.",
        handler=remember,
        params=[
            ToolParam(name="fact", type="string", description="A single clear statement to remember"),
            ToolParam(name="category", type="string", description="Category: 'preference', 'identity', 'work', or 'general'", required=False),
        ],
    ))

    registry.register(Tool(
        name="list_memories",
        description="Show all stored memories/facts. Use when the user asks what you know about them.",
        handler=list_memories,
        params=[],
    ))

    registry.register(Tool(
        name="update_memory",
        description="Correct or update an existing stored fact. Use when the user corrects something you had wrong.",
        handler=update_memory,
        params=[
            ToolParam(name="memory_id", type="string", description="The id of the fact to update"),
            ToolParam(name="new_fact", type="string", description="The corrected statement"),
        ],
    ))

    registry.register(Tool(
        name="forget",
        description="Remove a stored fact. Use when the user asks you to forget something.",
        handler=forget,
        requires_confirmation=True,  # deletes data
        params=[
            ToolParam(name="memory_id", type="string", description="The id of the fact to remove"),
        ],
    ))

    # ── Entity Memory Tools ──
    registry.register(Tool(
        name="remember_entity",
        description=(
            "Create or update a structured record for a Person or Project. "
            "Use when the user introduces someone new (gives a name, email, phone, relationship, or role), "
            "or mentions a new project/client. "
            "Always call get_person or get_project first to avoid duplicates. "
            "type must be 'person' or 'project'."
        ),
        handler=_tool_remember_entity,
        params=[
            ToolParam(name="type", type="string", description="'person' or 'project'"),
            ToolParam(name="name", type="string", description="Full canonical name"),
            ToolParam(name="relation", type="string", description="Relationship to user (e.g. sister, intern, client)", required=False),
            ToolParam(name="email", type="string", description="Email address", required=False),
            ToolParam(name="phone", type="string", description="Phone number", required=False),
            ToolParam(name="profession", type="string", description="Profession or role (people only)", required=False),
            ToolParam(name="aliases", type="string", description="Comma-separated nicknames or alternate names", required=False),
            ToolParam(name="notes", type="string", description="Any extra notes to store", required=False),
            ToolParam(name="status", type="string", description="Project status: active, paused, or completed (projects only)", required=False),
        ],
    ))

    registry.register(Tool(
        name="get_person",
        description=(
            "Look up a stored person by name, nickname, alias, or relation (e.g. 'sister', 'intern'). "
            "Call this before using any name-based contact info (email, phone) to resolve it correctly."
        ),
        handler=_tool_get_person,
        params=[
            ToolParam(name="name", type="string", description="Name, alias, or relation to search for"),
        ],
    ))

    registry.register(Tool(
        name="get_project",
        description=(
            "Look up a stored project by name or alias. "
            "Call this when the user refers to a project by a nickname or abbreviation."
        ),
        handler=_tool_get_project,
        params=[
            ToolParam(name="name", type="string", description="Project name or alias to search for"),
        ],
    ))
    
    registry.register(Tool(
        name="link_entities",
        description=(
            "Connect two entities (people or projects) in the knowledge graph. "
            "Use this when the user mentions how entities relate (e.g. Ekansh works on AI Gurukula, Sujaya reports to someone)."
            "Valid relationship types: works_on, owns, reports_to, related_to, meeting_with, depends_on."
        ),
        handler=link_entities,
        params=[
            ToolParam(name="source_name", type="string", description="Name of the source entity (e.g. 'Ekansh')"),
            ToolParam(name="target_name", type="string", description="Name of the target entity (e.g. 'AI Gurukula')"),
            ToolParam(name="relationship_type", type="string", description="Type of relationship (e.g. 'works_on')"),
        ],
    ))

