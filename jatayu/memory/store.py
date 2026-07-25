"""
JATAYU OS — Layer 1 Memory Store
=================================

Unified replacement for the old split memory.json + entities.json.
Backed by SQLite + FTS5. Provides high-performance, single-store access
for both semantic facts and structured entities.
"""

from __future__ import annotations

import difflib
import json
import logging
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from jatayu.config import get_config
from jatayu.tools import Tool, ToolParam, ToolRegistry

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex[:8]


PROTECTED_CATEGORIES = {"identity", "preference"}


@dataclass
class EmbeddingProvider:
    """Seam for future semantic search. No-op until a real backend is set."""
    enabled: bool = False

    def embed(self, text: str) -> Optional[list[float]]:
        if not self.enabled:
            return None
        raise NotImplementedError("Wire a real embedding backend here (e.g. Gemini text-embedding-004).")


class MemoryStore:
    def __init__(self, db_path: str | None = None, schema_path: str | None = None,
                 embedder: Optional[EmbeddingProvider] = None):
        data_dir = get_config().get("data_dir", "data")
        if db_path is None:
            db_path = str(Path(data_dir) / "memory.db")
        if schema_path is None:
            schema_path = str(Path(__file__).parent / "schema.sql")

        self.db_path = db_path
        self.schema_path = schema_path
        self.embedder = embedder or EmbeddingProvider(enabled=False)

        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._con = sqlite3.connect(db_path, check_same_thread=False)
        self._con.row_factory = sqlite3.Row
        self._con.execute("PRAGMA foreign_keys = ON")

        if Path(schema_path).exists():
            with open(schema_path, "r") as f:
                self._con.executescript(f.read())
            self._con.commit()

        self._protected_cache: Optional[list[dict]] = None

    @contextmanager
    def _cursor(self):
        cur = self._con.cursor()
        try:
            yield cur
            self._con.commit()
        except Exception:
            self._con.rollback()
            raise
        finally:
            cur.close()

    # ───────────────────────── FACTS ─────────────────────────

    def remember(self, fact: str, category: str = "general",
                 importance: float = 0.5, protected: Optional[bool] = None) -> str:
        fid = _new_id()
        now = _now()
        if protected is None:
            protected = category in PROTECTED_CATEGORIES
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO facts (id, fact, category, protected, importance,
                                       created_at, updated_at, access_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
                (fid, fact, category, int(protected), importance, now, now),
            )
        if protected:
            self._protected_cache = None  # invalidate cache on write
        return fid

    def forget(self, fact_id: str) -> bool:
        with self._cursor() as cur:
            cur.execute("DELETE FROM facts WHERE id = ?", (fact_id,))
            deleted = cur.rowcount > 0
        self._protected_cache = None
        return deleted

    def update_memory(self, fact_id: str, new_fact: str) -> bool:
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                "UPDATE facts SET fact = ?, updated_at = ? WHERE id = ?",
                (new_fact, now, fact_id),
            )
            updated = cur.rowcount > 0
        self._protected_cache = None
        return updated

    def list_memories(self, category: Optional[str] = None) -> list[dict]:
        with self._cursor() as cur:
            if category:
                cur.execute("SELECT * FROM facts WHERE category = ? ORDER BY created_at", (category,))
            else:
                cur.execute("SELECT * FROM facts ORDER BY category, created_at")
            return [dict(r) for r in cur.fetchall()]

    def _protected_facts(self) -> list[dict]:
        if self._protected_cache is None:
            with self._cursor() as cur:
                cur.execute("SELECT * FROM facts WHERE protected = 1 ORDER BY importance DESC")
                self._protected_cache = [dict(r) for r in cur.fetchall()]
        return self._protected_cache

    def _fts_query(self, text: str) -> str:
        tokens = [t for t in "".join(c if c.isalnum() else " " for c in text).split() if len(t) > 1]
        if not tokens:
            return ""
        return " OR ".join(f'"{t}"' for t in tokens)

    def search_facts(self, query: str, top_k: int = 5) -> list[dict]:
        q = self._fts_query(query)
        if not q:
            return []
        with self._cursor() as cur:
            cur.execute(
                """SELECT f.*, bm25(facts_fts) AS rank
                   FROM facts_fts
                   JOIN facts f ON f.rowid = facts_fts.rowid
                   WHERE facts_fts MATCH ?
                   ORDER BY rank LIMIT ?""",
                (q, top_k),
            )
            rows = [dict(r) for r in cur.fetchall()]
        if rows:
            now = _now()
            ids = [r["id"] for r in rows]
            with self._cursor() as cur:
                cur.executemany(
                    "UPDATE facts SET access_count = access_count + 1, last_accessed = ? WHERE id = ?",
                    [(now, i) for i in ids],
                )
        return rows

    def retrieve_for_prompt(self, user_text: str = "", top_k: int = 5) -> str:
        """Always includes protected facts, people, and projects, plus top-K matching facts."""
        protected = self._protected_facts()
        matched = self.search_facts(user_text, top_k=top_k) if user_text else []
        matched = [m for m in matched if m["id"] not in {p["id"] for p in protected}]

        lines = ["## Internal Context (Retrieved from Brain Memory):"]
        
        # Protected facts
        lines.append("\n### Protected Facts & Preferences:")
        for f in protected:
            lines.append(f"- [{f['category']}] {f['fact']}")
            
        for f in matched:
            lines.append(f"- [{f['category']}] {f['fact']}")

        # People Entities
        people = self.list_entities("person")
        if people:
            lines.append("\n### Known People:")
            for p in people:
                fields = p.get("fields", {})
                role = fields.get("role") or fields.get("profession") or p.get("relation") or ""
                aliases_str = f" (Aliases: {', '.join(p['aliases'])})" if p.get("aliases") else ""
                contact_info = []
                if fields.get("email"): contact_info.append(f"Email: {fields['email']}")
                if fields.get("phone"): contact_info.append(f"Phone: {fields['phone']}")
                contact_str = f" [{', '.join(contact_info)}]" if contact_info else ""
                lines.append(f"- **{p['name']}**{aliases_str}: {role}{contact_str}")

        # Project Entities
        projects = self.list_entities("project")
        if projects:
            lines.append("\n### Known Projects & Contracts:")
            for prj in projects:
                fields = prj.get("fields", {})
                desc = fields.get("description") or fields.get("role") or ""
                aliases_str = f" (Aliases: {', '.join(prj['aliases'])})" if prj.get("aliases") else ""
                contract = fields.get("contract")
                contract_str = f" [Contract: {json.dumps(contract)}]" if contract else ""
                lines.append(f"- **{prj['name']}**{aliases_str}: {desc}{contract_str}")

        return "\n".join(lines)

    # ─────────────────────── ENTITIES ────────────────────────

    def remember_entity(self, type: str, name: str, aliases: Optional[list[str]] = None,
                         **fields: Any) -> str:
        """Upsert by (type, name_lower) — re-saving the same entity updates it
        in place instead of creating a duplicate row."""
        now = _now()
        name_lower = name.strip().lower()
        aliases = aliases or []

        with self._cursor() as cur:
            cur.execute(
                "SELECT id, json_blob FROM entities WHERE type = ? AND name_lower = ?",
                (type, name_lower),
            )
            existing = cur.fetchone()

            if existing:
                eid = existing["id"]
                blob = json.loads(existing["json_blob"])
                blob.update({k: v for k, v in fields.items() if v is not None})
                cur.execute(
                    "UPDATE entities SET json_blob = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(blob), now, eid),
                )
            else:
                eid = _new_id()
                cur.execute(
                    """INSERT INTO entities (id, type, name, name_lower, json_blob, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (eid, type, name, name_lower, json.dumps(fields), now, now),
                )

            for alias in aliases:
                cur.execute(
                    """INSERT OR IGNORE INTO entity_aliases (entity_id, alias, alias_lower)
                       VALUES (?, ?, ?)""",
                    (eid, alias, alias.strip().lower()),
                )
            cur.execute(
                "INSERT OR IGNORE INTO entity_aliases (entity_id, alias, alias_lower) VALUES (?, ?, ?)",
                (eid, name, name_lower),
            )
        return eid

    def _entity_row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        blob = json.loads(d.pop("json_blob"))
        d.update(blob)
        d["fields"] = blob
        with self._cursor() as cur:
            cur.execute("SELECT alias FROM entity_aliases WHERE entity_id = ?", (d["id"],))
            d["aliases"] = sorted({r["alias"] for r in cur.fetchall()} - {d["name"]})
        return d

    def get_entity(self, type: str, name: str) -> Optional[dict]:
        needle = name.strip().lower()
        with self._cursor() as cur:
            # tier 1: exact alias hit (indexed, O(log n))
            cur.execute(
                """SELECT e.* FROM entities e
                   JOIN entity_aliases a ON a.entity_id = e.id
                   WHERE e.type = ? AND a.alias_lower = ?""",
                (type, needle),
            )
            row = cur.fetchone()
            if row:
                return self._entity_row_to_dict(row)

            # tier 2: bounded fuzzy match over this entity type's aliases
            cur.execute(
                """SELECT e.id, a.alias FROM entities e
                   JOIN entity_aliases a ON a.entity_id = e.id
                   WHERE e.type = ?""",
                (type,),
            )
            universe = cur.fetchall()
        if not universe:
            return None
        alias_pool = [r["alias"] for r in universe]
        close = difflib.get_close_matches(name, alias_pool, n=1, cutoff=0.65)
        if not close:
            return None
        match_id = next(r["id"] for r in universe if r["alias"] == close[0])
        with self._cursor() as cur:
            cur.execute("SELECT * FROM entities WHERE id = ?", (match_id,))
            row = cur.fetchone()
        return self._entity_row_to_dict(row) if row else None

    def get_person(self, name: str) -> Optional[dict]:
        return self.get_entity("person", name)

    def get_project(self, name: str) -> Optional[dict]:
        return self.get_entity("project", name)

    def list_entities(self, type: Optional[str] = None) -> list[dict]:
        with self._cursor() as cur:
            if type:
                cur.execute("SELECT * FROM entities WHERE type = ? ORDER BY name", (type,))
            else:
                cur.execute("SELECT * FROM entities ORDER BY type, name")
            rows = cur.fetchall()
        return [self._entity_row_to_dict(r) for r in rows]

    def close(self):
        self._con.close()


# ─────────────────────────────────────────────────────────────
# Global Singleton Accessor & Legacy Seams
# ─────────────────────────────────────────────────────────────

_GLOBAL_STORE: MemoryStore | None = None


def get_store() -> MemoryStore:
    global _GLOBAL_STORE
    if _GLOBAL_STORE is None:
        _GLOBAL_STORE = MemoryStore()
    return _GLOBAL_STORE


def load_memory_for_prompt(user_text: str = "") -> str:
    """Public API called by brain/server for prompt context."""
    return get_store().retrieve_for_prompt(user_text=user_text)


def remember(fact: str, category: str = "general") -> str:
    store = get_store()
    # Check duplicate
    existing = store.search_facts(fact, top_k=5)
    for e in existing:
        if e["fact"].lower().strip() == fact.lower().strip():
            return f"I already have that noted: \"{e['fact']}\""
    store.remember(fact, category=category)
    return f"✅ Remembered: \"{fact}\""


def list_memories() -> str:
    facts = get_store().list_memories()
    if not facts:
        return "No memories stored yet."
    lines = []
    for f in facts:
        lines.append(f"• [{f['id']}] ({f.get('category', 'general')}) {f['fact']}")
    return "\n".join(lines)


def update_memory(memory_id: str, new_fact: str) -> str:
    success = get_store().update_memory(memory_id, new_fact)
    if success:
        return f"✅ Updated memory [{memory_id}] → \"{new_fact}\""
    return f"No memory found with id '{memory_id}'."


def forget(memory_id: str) -> str:
    success = get_store().forget(memory_id)
    if success:
        return f"✅ Forgot memory [{memory_id}]."
    return f"No memory found with id '{memory_id}'."


def _tool_remember_entity(
    type: str,
    name: str,
    relation: str = "",
    email: str = "",
    phone: str = "",
    profession: str = "",
    aliases: str = "",
    notes: str = "",
    status: str = "active",
) -> str:
    aliases_list = [a.strip() for a in aliases.split(",") if a.strip()] if aliases else []
    fields = {
        "relation": relation,
        "email": email,
        "phone": phone,
        "profession": profession,
        "notes": notes,
        "status": status,
    }
    eid = get_store().remember_entity(type=type, name=name, aliases=aliases_list, **fields)
    return f"✅ Recorded {type} '{name}' [{eid}]."


def _tool_get_person(name: str) -> str:
    entity = get_store().get_person(name)
    if not entity:
        return f"No person record found matching '{name}'."
    parts = [f"Name: {entity.get('name','?')}" ]
    if entity.get("relation"): parts.append(f"Relation: {entity['relation']}")
    if entity.get("role"): parts.append(f"Role: {entity['role']}")
    if entity.get("email"): parts.append(f"Email: {entity['email']}")
    if entity.get("phone"): parts.append(f"Phone: {entity['phone']}")
    if entity.get("profession"): parts.append(f"Profession: {entity['profession']}")
    if entity.get("notes"): parts.append(f"Notes: {entity['notes']}")
    if entity.get("aliases"): parts.append(f"Also known as: {', '.join(entity['aliases'])}")
    return "\n".join(parts)


def _tool_get_project(name: str) -> str:
    entity = get_store().get_project(name)
    if not entity:
        return f"No project record found matching '{name}'."
    parts = [f"Project: {entity.get('name','?')}"]
    if entity.get("role"): parts.append(f"Role/Description: {entity['role']}")
    if entity.get("status"): parts.append(f"Status: {entity['status']}")
    if entity.get("description"): parts.append(f"Description: {entity['description']}")
    if entity.get("contract"): parts.append(f"Contract: {json.dumps(entity['contract'])}")
    if entity.get("notes"): parts.append(f"Notes: {entity['notes']}")
    if entity.get("aliases"): parts.append(f"Also known as: {', '.join(entity['aliases'])}")
    return "\n".join(parts)


def link_entities(source_name: str, target_name: str, relationship_type: str) -> str:
    return (
        "❌ Knowledge graph relationships are not available in JATAYU Core. "
        "Use get_person or get_project to look up entities individually."
    )


# ─────────────────────────────────────────────────────────────
# Tool Registration
# ─────────────────────────────────────────────────────────────

def register(registry: ToolRegistry) -> None:
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
        requires_confirmation=True,
        params=[
            ToolParam(name="memory_id", type="string", description="The id of the fact to remove"),
        ],
    ))

    registry.register(Tool(
        name="remember_entity",
        description="Create or update a structured record for a Person or Project.",
        handler=_tool_remember_entity,
        params=[
            ToolParam(name="type", type="string", description="'person' or 'project'"),
            ToolParam(name="name", type="string", description="Full canonical name"),
            ToolParam(name="relation", type="string", description="Relationship to user", required=False),
            ToolParam(name="email", type="string", description="Email address", required=False),
            ToolParam(name="phone", type="string", description="Phone number", required=False),
            ToolParam(name="profession", type="string", description="Profession or role", required=False),
            ToolParam(name="aliases", type="string", description="Comma-separated nicknames", required=False),
            ToolParam(name="notes", type="string", description="Extra notes", required=False),
            ToolParam(name="status", type="string", description="Project status", required=False),
        ],
    ))

    registry.register(Tool(
        name="get_person",
        description="Look up a stored person by name, nickname, alias, or relation.",
        handler=_tool_get_person,
        params=[
            ToolParam(name="name", type="string", description="Name, alias, or relation to search for"),
        ],
    ))

    registry.register(Tool(
        name="get_project",
        description="Look up a stored project by name or alias.",
        handler=_tool_get_project,
        params=[
            ToolParam(name="name", type="string", description="Project name or alias to search for"),
        ],
    ))

    registry.register(Tool(
        name="link_entities",
        description="Connect two entities in the knowledge graph.",
        handler=link_entities,
        params=[
            ToolParam(name="source_name", type="string", description="Name of source entity"),
            ToolParam(name="target_name", type="string", description="Name of target entity"),
            ToolParam(name="relationship_type", type="string", description="Type of relationship"),
        ],
    ))
