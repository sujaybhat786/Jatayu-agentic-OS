"""Entity Memory Layer — structured records for People and Projects.

Delegates to MemoryStore (SQLite + FTS5).
"""

from __future__ import annotations

from typing import Optional
from jatayu.memory.store import get_store


def get_person(name_or_alias: str) -> dict | None:
    return get_store().get_person(name_or_alias)


def get_project(name_or_alias: str) -> dict | None:
    return get_store().get_project(name_or_alias)


def list_entities(entity_type: str | None = None, include_deleted: bool = False) -> list[dict]:
    return get_store().list_entities(type=entity_type)


def upsert_person(
    name: str,
    relation: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    profession: str | None = None,
    aliases: list[str] | None = None,
    notes: str | None = None,
) -> tuple[dict, bool]:
    store = get_store()
    existing = store.get_person(name)
    was_created = existing is None
    eid = store.remember_entity(
        type="person",
        name=name,
        aliases=aliases,
        relation=relation,
        email=email,
        phone=phone,
        profession=profession,
        notes=notes,
    )
    return store.get_person(name) or {}, was_created


def upsert_project(
    name: str,
    aliases: list[str] | None = None,
    status: str = "active",
    notes: str | None = None,
) -> tuple[dict, bool]:
    store = get_store()
    existing = store.get_project(name)
    was_created = existing is None
    eid = store.remember_entity(
        type="project",
        name=name,
        aliases=aliases,
        status=status,
        notes=notes,
    )
    return store.get_project(name) or {}, was_created


def detect_entities_in_text(text: str) -> list[dict]:
    entities = get_store().list_entities()
    matched = []
    text_lower = text.lower()
    for e in entities:
        if e["name"].lower() in text_lower:
            matched.append(e)
            continue
        for a in e.get("aliases", []):
            if a.lower() in text_lower:
                matched.append(e)
                break
    return matched
