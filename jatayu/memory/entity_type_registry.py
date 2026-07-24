"""Entity Type Registry — plugin-extensible entity type definitions.

Instead of a hardcoded ENTITY_TYPES list, types are registered here at startup.
Plugins can extend the registry with new types without modifying entities.py.

Design rules (from Brain Contract v1):
- Written to only at startup (registration phase).
- Never calls the LLM or any external API.
- No imports from pipeline services.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class FieldSchema:
    """Schema for a single field on an entity type."""
    name: str
    type: str           # "string" | "list" | "boolean" | "number"
    required: bool = False
    description: str = ""


@dataclass
class EntitySchema:
    """Schema definition for one entity type.

    Args:
        type_name:        Internal name, e.g. "person"
        display_name:     Human-readable name, e.g. "Person"
        fields:           List of FieldSchema definitions
        searchable_fields: Which fields are used in fuzzy matching
        default_aliases:  Alternative names / display aliases for this type
        description:      Short description of what this entity represents
    """
    type_name: str
    display_name: str
    fields: list[FieldSchema] = field(default_factory=list)
    searchable_fields: list[str] = field(default_factory=list)
    default_aliases: list[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "type_name": self.type_name,
            "display_name": self.display_name,
            "fields": [
                {
                    "name": f.name,
                    "type": f.type,
                    "required": f.required,
                    "description": f.description,
                }
                for f in self.fields
            ],
            "searchable_fields": self.searchable_fields,
            "default_aliases": self.default_aliases,
            "description": self.description,
        }


class EntityTypeRegistry:
    """Registry of entity type schemas.

    Types are registered once at startup. After startup is complete,
    no new types should be added. Plugins register types during their
    `discover_and_load()` phase.
    """

    def __init__(self) -> None:
        self._types: dict[str, EntitySchema] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        """Register all 10 built-in entity types."""
        builtins = [
            EntitySchema(
                type_name="person",
                display_name="Person",
                description="A person known to JATAYU",
                fields=[
                    FieldSchema("name",       "string",  required=True),
                    FieldSchema("relation",   "string"),
                    FieldSchema("email",      "string"),
                    FieldSchema("phone",      "string"),
                    FieldSchema("profession", "string"),
                    FieldSchema("aliases",    "list"),
                    FieldSchema("notes",      "string"),
                    # Phase 4 confidence fields
                    FieldSchema("confidence", "number"),
                    FieldSchema("source",     "string"),
                    FieldSchema("verified",   "boolean"),
                    FieldSchema("last_used",  "string"),
                    FieldSchema("times_used", "number"),
                ],
                searchable_fields=["name", "aliases", "relation", "email"],
            ),
            EntitySchema(
                type_name="project",
                display_name="Project",
                description="A project or initiative",
                fields=[
                    FieldSchema("name",       "string",  required=True),
                    FieldSchema("aliases",    "list"),
                    FieldSchema("status",     "string"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("confidence", "number"),
                    FieldSchema("source",     "string"),
                    FieldSchema("verified",   "boolean"),
                    FieldSchema("last_used",  "string"),
                    FieldSchema("times_used", "number"),
                ],
                searchable_fields=["name", "aliases"],
            ),
            EntitySchema(
                type_name="company",
                display_name="Company",
                description="An organization or company",
                fields=[
                    FieldSchema("name",       "string",  required=True),
                    FieldSchema("aliases",    "list"),
                    FieldSchema("industry",   "string"),
                    FieldSchema("website",    "string"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("confidence", "number"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["name", "aliases"],
            ),
            EntitySchema(
                type_name="document",
                display_name="Document",
                description="A document, file, or note",
                fields=[
                    FieldSchema("name",       "string",  required=True),
                    FieldSchema("location",   "string"),   # Obsidian / Notion / Drive path
                    FieldSchema("type",       "string"),   # "note" | "doc" | "sheet" | ...
                    FieldSchema("aliases",    "list"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["name", "aliases"],
            ),
            EntitySchema(
                type_name="task",
                display_name="Task",
                description="An actionable to-do item",
                fields=[
                    FieldSchema("name",       "string",  required=True),
                    FieldSchema("status",     "string"),   # "pending" | "done" | "blocked"
                    FieldSchema("due_date",   "string"),
                    FieldSchema("project_id", "string"),   # relationship to project entity
                    FieldSchema("notes",      "string"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["name"],
            ),
            EntitySchema(
                type_name="meeting",
                display_name="Meeting",
                description="A meeting or scheduled call",
                fields=[
                    FieldSchema("name",        "string", required=True),
                    FieldSchema("date",        "string"),
                    FieldSchema("participants", "list"),
                    FieldSchema("agenda",      "string"),
                    FieldSchema("notes",       "string"),
                    FieldSchema("source",      "string"),
                ],
                searchable_fields=["name", "participants"],
            ),
            EntitySchema(
                type_name="email",
                display_name="Email Thread",
                description="A tracked email conversation",
                fields=[
                    FieldSchema("subject",    "string", required=True),
                    FieldSchema("from_addr",  "string"),
                    FieldSchema("to_addrs",   "list"),
                    FieldSchema("date",       "string"),
                    FieldSchema("thread_id",  "string"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["subject", "from_addr"],
            ),
            EntitySchema(
                type_name="location",
                display_name="Location",
                description="A physical place or address",
                fields=[
                    FieldSchema("name",       "string", required=True),
                    FieldSchema("address",    "string"),
                    FieldSchema("city",       "string"),
                    FieldSchema("country",    "string"),
                    FieldSchema("aliases",    "list"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["name", "aliases", "city"],
            ),
            EntitySchema(
                type_name="account",
                display_name="Account",
                description="A service account or credential (no secrets stored)",
                fields=[
                    FieldSchema("name",       "string", required=True),
                    FieldSchema("service",    "string"),   # "Gmail", "Notion", "GitHub"
                    FieldSchema("identifier", "string"),   # email or username, not password
                    FieldSchema("aliases",    "list"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["name", "service", "identifier"],
            ),
            EntitySchema(
                type_name="knowledge_source",
                display_name="Knowledge Source",
                description="A knowledge base, wiki, or reference",
                fields=[
                    FieldSchema("name",       "string", required=True),
                    FieldSchema("type",       "string"),   # "obsidian" | "notion" | "anythingllm"
                    FieldSchema("url",        "string"),
                    FieldSchema("aliases",    "list"),
                    FieldSchema("notes",      "string"),
                    FieldSchema("source",     "string"),
                ],
                searchable_fields=["name", "aliases"],
            ),
        ]

        for schema in builtins:
            self._types[schema.type_name] = schema
            logger.debug("EntityTypeRegistry: registered built-in type '%s'", schema.type_name)

    # ── Public API ─────────────────────────────────────────────────────────────

    def register(self, schema: EntitySchema) -> None:
        """Register a new entity type.

        Plugins call this during discover_and_load(). Safe to call with
        an existing type name — logs a warning and overwrites.
        """
        if schema.type_name in self._types:
            logger.warning(
                "EntityTypeRegistry: overwriting existing type '%s'", schema.type_name
            )
        self._types[schema.type_name] = schema
        logger.info("EntityTypeRegistry: registered type '%s'", schema.type_name)

    def get(self, type_name: str) -> EntitySchema | None:
        """Look up a type schema by name."""
        return self._types.get(type_name)

    def list_types(self) -> list[str]:
        """Return all registered type names."""
        return list(self._types.keys())

    def is_valid_type(self, type_name: str) -> bool:
        """Check if a type name is registered."""
        return type_name in self._types

    def validate_entity(self, entity: dict) -> tuple[bool, list[str]]:
        """Validate an entity dict against its registered schema.

        Returns:
            (valid: bool, errors: list[str])
        """
        type_name = entity.get("type")
        schema = self._types.get(type_name)
        if schema is None:
            return False, [f"Unknown entity type: '{type_name}'"]

        errors = []
        for f in schema.fields:
            if f.required and not entity.get(f.name):
                errors.append(f"Missing required field: '{f.name}'")

        return len(errors) == 0, errors

    def to_dict(self) -> dict:
        """Serialize all schemas for API responses."""
        return {name: schema.to_dict() for name, schema in self._types.items()}


# ── Singleton ─────────────────────────────────────────────────────────────────
# Initialized once at server startup. Imported by other modules via:
#     from jatayu.memory.entity_type_registry import entity_type_registry
entity_type_registry = EntityTypeRegistry()
