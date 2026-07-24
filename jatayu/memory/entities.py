"""Entity Memory Layer — structured records for People and Projects.

This is additive to the flat memory.json facts. It provides:
- Stable entity records with IDs, aliases, and contact fields
- Fuzzy name/alias matching using difflib (stdlib, no extra deps)
- Lookup tools the Brain uses to resolve "email my sister" → entity record
- System prompt injection so the model always has entity context

Storage: data/entities.json (plain JSON, human-editable)
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

from jatayu.config import get_config


# ------------------------------------------------------------------ #
#  Storage helpers                                                     #
# ------------------------------------------------------------------ #

def _entities_path() -> Path:
    return Path(get_config()["data_dir"]) / "entities.json"


_CACHE = None
_CACHE_MTIME = 0.0

def _load() -> list[dict]:
    global _CACHE, _CACHE_MTIME
    path = _entities_path()
    if not path.exists():
        return []
    
    mtime = path.stat().st_mtime
    if _CACHE is not None and mtime == _CACHE_MTIME:
        return _CACHE
        
    with open(path) as f:
        _CACHE = json.load(f)
    _CACHE_MTIME = mtime
    return _CACHE


def _save(entities: list[dict]) -> None:
    global _CACHE, _CACHE_MTIME
    path = _entities_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(entities, f, indent=2, default=str)
    
    _CACHE = entities
    _CACHE_MTIME = path.stat().st_mtime


def _slugify(name: str) -> str:
    """Convert a name into a stable slug id."""
    slug = name.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    return slug.strip("-")


# ------------------------------------------------------------------ #
#  Fuzzy matching                                                      #
# ------------------------------------------------------------------ #

FUZZY_THRESHOLD = 0.75


def _fuzzy_score(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _entity_matches(entity: dict, query: str) -> bool:
    """Return True if query fuzzy-matches entity name or any alias."""
    query_lower = query.lower().strip()
    
    # Exact substring match first (fast path)
    if query_lower in entity.get("name", "").lower():
        return True
    for alias in entity.get("aliases", []):
        if query_lower in alias.lower() or alias.lower() in query_lower:
            return True
    
    # Fuzzy match
    if _fuzzy_score(query, entity.get("name", "")) >= FUZZY_THRESHOLD:
        return True
    for alias in entity.get("aliases", []):
        if _fuzzy_score(query, alias) >= FUZZY_THRESHOLD:
            return True
    
    # Relation match (e.g. "sister", "intern")
    if entity.get("relation") and query_lower == entity["relation"].lower():
        return True
    
    return False


def _best_match(entities: list[dict], query: str, entity_type: str | None = None) -> dict | None:
    """Return the entity with the best fuzzy score for query, or None."""
    candidates = [e for e in entities if entity_type is None or e.get("type") == entity_type]
    
    best = None
    best_score = 0.0
    query_lower = query.lower().strip()
    
    for entity in candidates:
        # Check exact substring first
        if query_lower in entity.get("name", "").lower():
            return entity
        for alias in entity.get("aliases", []):
            if query_lower in alias.lower() or alias.lower() in query_lower:
                return entity
        # Check relation
        if entity.get("relation") and query_lower == entity.get("relation", "").lower():
            return entity
        
        # Fuzzy scoring
        score = _fuzzy_score(query, entity.get("name", ""))
        for alias in entity.get("aliases", []):
            score = max(score, _fuzzy_score(query, alias))
        
        if score > best_score and score >= FUZZY_THRESHOLD:
            best_score = score
            best = entity
    
    return best


# ------------------------------------------------------------------ #
#  Public Lookup API — used by Brain tools                            #
# ------------------------------------------------------------------ #

def get_person(name_or_alias: str) -> dict | None:
    """Find a person entity by name, alias, or relation (e.g. 'sister')."""
    entities = _load()
    return _best_match(entities, name_or_alias, entity_type="person")


def get_project(name_or_alias: str) -> dict | None:
    """Find a project entity by name or alias."""
    entities = _load()
    return _best_match(entities, name_or_alias, entity_type="project")


def list_entities(entity_type: str | None = None, include_deleted: bool = False) -> list[dict]:
    """Return all entities, optionally filtered by type. Excludes soft-deleted entities by default."""
    entities = _load()
    if not include_deleted:
        entities = [e for e in entities if e.get("status") not in ("deleted", "archived")]
        
    if entity_type:
        return [e for e in entities if e.get("type") == entity_type]
    return entities


def detect_entities_in_text(text: str) -> list[dict]:
    """Scan text for any known entity names/aliases in linear time."""
    entities = _load()
    found = []
    seen_ids = set()
    text_lower = text.lower()
    
    for entity in entities:
        if entity["id"] in seen_ids:
            continue
            
        name = entity.get("name", "").lower()
        if name and name in text_lower:
            # Basic boundary check to avoid substring collision on short names
            # Though regex \b can be slow, simple `in` + regex check is fast
            if re.search(r'\b' + re.escape(name) + r'\b', text_lower):
                found.append(entity)
                seen_ids.add(entity["id"])
                continue
                
        alias_matched = False
        for alias in entity.get("aliases", []):
            alias_low = alias.lower()
            if alias_low and alias_low in text_lower:
                if re.search(r'\b' + re.escape(alias_low) + r'\b', text_lower):
                    found.append(entity)
                    seen_ids.add(entity["id"])
                    alias_matched = True
                    break
                    
        if alias_matched:
            continue
            
    return found


# ------------------------------------------------------------------ #
#  Upsert — create or update an entity                                #
# ------------------------------------------------------------------ #

def upsert_person(
    name: str,
    relation: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    profession: str | None = None,
    aliases: list[str] | None = None,
    notes: str | None = None,
) -> tuple[dict, bool]:
    """Create or update a Person entity.
    
    Returns (entity, was_created). Fuzzy-matches against existing records
    before creating a new one to avoid duplicates.
    """
    entities = _load()
    
    # Check for existing match
    existing = _best_match(entities, name, entity_type="person")
    
    if existing:
        # Conflict Resolution: Keep history of overwrites
        was_created = False
        snapshot = {k: v for k, v in existing.items() if k not in ("history", "updated_at")}
        
        # Assume user confirmation takes priority if we had a confirmed flag (mocking this logic by appending history safely)
        existing.setdefault("history", []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": snapshot
        })
        
        if relation: existing["relation"] = relation
        if email: existing["email"] = email
        if phone: existing["phone"] = phone
        if profession: existing["profession"] = profession
        if notes: existing["notes"] = notes
        if aliases:
            existing_aliases = set(a.lower() for a in existing.get("aliases", []))
            for a in aliases:
                if a.lower() not in existing_aliases:
                    existing.setdefault("aliases", []).append(a)
        
        # Versioning
        existing["version"] = existing.get("version", 1) + 1
        existing["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(entities)
        return existing, was_created
    else:
        # Create new entity
        was_created = True
        entity_id = _slugify(name)
        # Ensure unique id
        existing_ids = {e["id"] for e in entities}
        if entity_id in existing_ids:
            entity_id = entity_id + "-" + uuid.uuid4().hex[:4]
        
        entity = {
            "type": "person",
            "id": entity_id,
            "name": name,
            "relation": relation,
            "email": email,
            "phone": phone,
            "profession": profession,
            "notes": notes,
            "aliases": aliases or [],
            "status": "active",
            "version": 1,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        entities.append(entity)
        _save(entities)
        return entity, was_created


def upsert_project(
    name: str,
    aliases: list[str] | None = None,
    status: str = "active",
    notes: str | None = None,
) -> tuple[dict, bool]:
    """Create or update a Project entity.
    
    Returns (entity, was_created).
    """
    entities = _load()
    
    existing = _best_match(entities, name, entity_type="project")
    
    if existing:
        # Conflict Resolution
        was_created = False
        snapshot = {k: v for k, v in existing.items() if k not in ("history", "updated_at")}
        existing.setdefault("history", []).append({
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": snapshot
        })
        
        if status: existing["status"] = status
        if notes: existing["notes"] = notes
        if aliases:
            existing_aliases = set(a.lower() for a in existing.get("aliases", []))
            for a in aliases:
                if a.lower() not in existing_aliases:
                    existing.setdefault("aliases", []).append(a)
                    
        existing["version"] = existing.get("version", 1) + 1
        existing["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        _save(entities)
        return existing, was_created
    else:
        was_created = True
        entity_id = _slugify(name)
        existing_ids = {e["id"] for e in entities}
        if entity_id in existing_ids:
            entity_id = entity_id + "-" + uuid.uuid4().hex[:4]
        
        entity = {
            "type": "project",
            "id": entity_id,
            "name": name,
            "aliases": aliases or [],
            "status": status,
            "notes": notes,
            "version": 1,
            "history": [],
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        entities.append(entity)
        _save(entities)
        return entity, was_created


# ------------------------------------------------------------------ #
#  System Prompt Injection                                            #
# ------------------------------------------------------------------ #

def load_entities_for_prompt() -> str:
    """Format all entities as a readable block for the system prompt."""
    entities = _load()
    if not entities:
        return ""
    
    people = [e for e in entities if e.get("type") == "person"]
    projects = [e for e in entities if e.get("type") == "project"]
    
    lines = ["\n## People I Know:"]
    for p in people:
        name = p.get("name", "?")
        relation = p.get("relation", "")
        email = p.get("email", "")
        phone = p.get("phone", "")
        profession = p.get("profession", "")
        aliases = p.get("aliases", [])
        notes = p.get("notes", "")
        
        entry = f"- **{name}**"
        if relation: entry += f" — {relation}"
        if profession: entry += f" ({profession})"
        if email: entry += f" — email: {email}"
        if phone: entry += f" — phone: {phone}"
        if aliases: entry += f"\n  aliases: {', '.join(aliases)}"
        if notes: entry += f"\n  notes: {notes}"
        lines.append(entry)
    
    if projects:
        lines.append("\n## Projects / Clients:")
        for p in projects:
            name = p.get("name", "?")
            status = p.get("status", "active")
            aliases = p.get("aliases", [])
            notes = p.get("notes", "")
            
            entry = f"- **{name}** [{status}]"
            if aliases: entry += f" — also known as: {', '.join(aliases)}"
            if notes: entry += f"\n  notes: {notes}"
            lines.append(entry)
    
    lines.append("")
    return "\n".join(lines)
