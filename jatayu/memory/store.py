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

    def search_entities(self, user_text: str, type: Optional[str] = None, top_k: int = 5) -> list[dict]:
        """Relevance search over entities via FTS5 (name+aliases+role/description),
        ranked by bm25. Scales to large entity counts without a rewrite —
        same pattern as search_facts()."""
        q = self._fts_query(user_text)
        if not q:
            return []
        with self._cursor() as cur:
            if type:
                cur.execute(
                    """SELECT e.*, bm25(entities_search_fts) AS rank
                       FROM entities_search_fts f JOIN entities e ON e.id = f.entity_id
                       WHERE entities_search_fts MATCH ? AND f.type = ?
                       ORDER BY rank LIMIT ?""",
                    (q, type, top_k),
                )
            else:
                cur.execute(
                    """SELECT e.*, bm25(entities_search_fts) AS rank
                       FROM entities_search_fts f JOIN entities e ON e.id = f.entity_id
                       WHERE entities_search_fts MATCH ?
                       ORDER BY rank LIMIT ?""",
                    (q, top_k),
                )
            rows = cur.fetchall()
        return [self._entity_row_to_dict(r) for r in rows]

    def _format_entity_full(self, e: dict) -> str:
        fields = e.get("fields", {})
        aliases_str = f" (aka {', '.join(e['aliases'])})" if e.get("aliases") else ""
        if e["type"] == "person":
            role = fields.get("role") or fields.get("profession") or fields.get("relation") or ""
            contact = [v for v in (
                f"Email: {fields['email']}" if fields.get("email") else None,
                f"Phone: {fields['phone']}" if fields.get("phone") else None,
            ) if v]
            contact_str = f" [{', '.join(contact)}]" if contact else ""
            return f"- **{e['name']}**{aliases_str}: {role}{contact_str}"
        else:
            desc = fields.get("description") or fields.get("role") or ""
            contract = fields.get("contract")
            contract_str = f" [Contract: {json.dumps(contract)}]" if contract else ""
            return f"- **{e['name']}**{aliases_str}: {desc}{contract_str}"

    def retrieve_for_prompt(self, user_text: str = "", top_k: int = 5) -> str:
        """Token-bounded context block for the system prompt:
          - protected facts: always included in full (small, fixed-size, O(1) cache)
          - top-K facts relevant to user_text: full text
          - top-K people/projects relevant to user_text: FULL details (email/phone/contract)
          - everyone/everything else: name only, in a compact roster line

        This keeps the injected block roughly constant-size as facts/entities grow
        into the hundreds or thousands, instead of linearly dumping every known
        person and project (with full contact/contract info) into every single
        request regardless of relevance.
        """
        protected = self._protected_facts()
        fact_matches = self.search_facts(user_text, top_k=top_k) if user_text else []
        fact_matches = [m for m in fact_matches if m["id"] not in {p["id"] for p in protected}]

        entity_matches = self.search_entities(user_text, top_k=top_k) if user_text else []
        matched_ids = {e["id"] for e in entity_matches}

        lines = ["## Internal Context (Retrieved from Brain Memory):"]

        lines.append("\n### Protected Facts & Preferences:")
        for f in protected:
            lines.append(f"- [{f['category']}] {f['fact']}")

        if fact_matches:
            lines.append("\n### Relevant Facts:")
            for f in fact_matches:
                lines.append(f"- [{f['category']}] {f['fact']}")

        if entity_matches:
            lines.append("\n### Relevant People / Projects (full detail):")
            for e in entity_matches:
                lines.append(self._format_entity_full(e))

        # Compact roster of everything NOT already shown in full — cheap
        # (names only), and lets the model reason about who exists so it can
        # call get_person()/get_project() explicitly when relevance search
        # misses (e.g. "him", "the client").
        ROSTER_CAP = 40  # above this, listing every name stops being "cheap" — switch to a count
        all_people = self.list_entities("person")
        all_projects = self.list_entities("project")
        other_people = [p["name"] for p in all_people if p["id"] not in matched_ids]
        other_projects = [p["name"] for p in all_projects if p["id"] not in matched_ids]
        if other_people or other_projects:
            lines.append("\n### Other Known Names (call get_person/get_project for details):")
            if other_people:
                if len(other_people) <= ROSTER_CAP:
                    lines.append(f"- People: {', '.join(other_people)}")
                else:
                    lines.append(f"- {len(other_people)} other known people not shown here — "
                                  f"use get_person(name) to look any of them up by name.")
            if other_projects:
                if len(other_projects) <= ROSTER_CAP:
                    lines.append(f"- Projects: {', '.join(other_projects)}")
                else:
                    lines.append(f"- {len(other_projects)} other known projects not shown here — "
                                  f"use get_project(name) to look any of them up by name.")

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

            # Keep the relevance-search index in sync. Composite blob (not a
            # single column) so this is maintained here rather than via a
            # SQL trigger. Delete+reinsert is cheap at this scale and avoids
            # any risk of stale/duplicate FTS rows on repeated upserts.
            final_blob = json.loads(cur.execute(
                "SELECT json_blob FROM entities WHERE id = ?", (eid,)
            ).fetchone()["json_blob"])
            all_aliases = {r["alias"] for r in cur.execute(
                "SELECT alias FROM entity_aliases WHERE entity_id = ?", (eid,)
            ).fetchall()}
            contract = final_blob.get("contract") or {}
            contract_text = " ".join(str(v) for v in contract.values()) if isinstance(contract, dict) else ""
            searchable_text = " ".join(str(v) for v in [
                name, " ".join(all_aliases),
                final_blob.get("role", ""), final_blob.get("relation", ""),
                final_blob.get("description", ""), final_blob.get("notes", "") or "",
                contract_text,
            ] if v)
            cur.execute("DELETE FROM entities_search_fts WHERE entity_id = ?", (eid,))
            cur.execute(
                "INSERT INTO entities_search_fts (entity_id, type, blob) VALUES (?, ?, ?)",
                (eid, type, searchable_text),
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

    # ─────────────────────────── NOTES (verbatim) ───────────────────────────

    def save_note(self, label: str, content: str) -> str:
        """Save exact text under a label. Saving to the same label again
        REPLACES the previous content (last one wins) — this is intentional
        for things like a weekly update that gets refreshed each week."""
        now = _now()
        with self._cursor() as cur:
            cur.execute(
                """INSERT INTO notes (label, content, created_at, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(label) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at""",
                (label, content, now, now),
            )
        return label

    def recall_note(self, label: str) -> Optional[str]:
        """Return the exact saved content for a label, or None if nothing's saved yet."""
        with self._cursor() as cur:
            cur.execute("SELECT content FROM notes WHERE label = ?", (label,))
            row = cur.fetchone()
        return row["content"] if row else None

    def list_notes(self) -> list[dict]:
        with self._cursor() as cur:
            cur.execute("SELECT label, content, updated_at FROM notes ORDER BY updated_at DESC")
            return [dict(r) for r in cur.fetchall()]


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
    relation: str = None,
    email: str = None,
    phone: str = None,
    profession: str = None,
    aliases: str = "",
    notes: str = None,
    status: str = None,
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
    # CRITICAL: only pass along fields the model actually specified this call.
    # These used to default to "" instead of None, and the upsert logic only
    # skips None — so "" was treated as "set this to blank" and silently
    # wiped out correct data (email/phone/etc.) on every partial update that
    # didn't happen to re-state every field. Filtering None here is what
    # makes updates additive instead of destructive.
    fields = {k: v for k, v in fields.items() if v is not None}
    eid = get_store().remember_entity(type=type, name=name, aliases=aliases_list, **fields)
    return f"✅ Recorded {type} '{name}' [{eid}]."


def _tool_save_note(label: str, content: str) -> str:
    get_store().save_note(label, content)
    return f"✅ Saved verbatim under label '{label}'. Will be recalled exactly as written when asked."


def _tool_recall_note(label: str) -> str:
    content = get_store().recall_note(label)
    if content is None:
        return f"No note saved under label '{label}' yet."
    return content


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
        name="save_note",
        description=(
            "Save text EXACTLY as given, under a label, for guaranteed word-for-word recall later "
            "(e.g. a weekly update the user dictates). Saving to the same label again REPLACES the "
            "previous content. Use this instead of `remember` when the user wants their exact wording "
            "preserved, not a fact you might paraphrase later."
        ),
        handler=_tool_save_note,
        params=[
            ToolParam(name="label", type="string", description="A short identifier, e.g. 'weekly_update'"),
            ToolParam(name="content", type="string", description="The exact text to save, verbatim"),
        ],
    ))

    registry.register(Tool(
        name="recall_note",
        description=(
            "Retrieve text previously saved with save_note, by label. IMPORTANT: when you get a result "
            "back from this tool, output it to the user EXACTLY as returned — verbatim, no paraphrasing, "
            "no summarizing, no reformatting, no added commentary mixed into it. A brief one-line intro "
            "before it (e.g. 'Here's what you told me:') is fine, but the saved content itself must be "
            "word-for-word identical to what's stored."
        ),
        handler=_tool_recall_note,
        params=[
            ToolParam(name="label", type="string", description="The label it was saved under"),
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
