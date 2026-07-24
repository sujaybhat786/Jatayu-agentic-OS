"""Relationship Registry for Edge Types."""

import logging
from jatayu.memory.graph.models import EdgeType

logger = logging.getLogger(__name__)

class RelationshipRegistry:
    """Registry of relationship edge types."""
    
    def __init__(self):
        self._types: dict[str, EdgeType] = {}
        self._register_builtins()

    def _register_builtins(self):
        builtins = [
            EdgeType(
                name="works_on",
                description="Person works on a project",
                allowed_source_types=["person"],
                allowed_target_types=["project"],
                inverse_name="has_member",
            ),
            EdgeType(
                name="owns",
                description="Person owns or leads a project",
                allowed_source_types=["person"],
                allowed_target_types=["project"],
                inverse_name="owned_by",
            ),
            EdgeType(
                name="reports_to",
                description="Person reports to another person",
                allowed_source_types=["person"],
                allowed_target_types=["person"],
                inverse_name="manages",
            ),
            EdgeType(
                name="related_to",
                description="Generic relation between two entities",
                symmetric=True,
            ),
            EdgeType(
                name="meeting_with",
                description="Person had a meeting with another person",
                allowed_source_types=["person"],
                allowed_target_types=["person"],
                symmetric=True,
            ),
            EdgeType(
                name="depends_on",
                description="Task or Project depends on another",
                allowed_source_types=["task", "project"],
                allowed_target_types=["task", "project"],
                inverse_name="blocks",
            ),
            EdgeType(
                name="mentioned_in",
                description="Entity is mentioned in a document or note",
                allowed_target_types=["document"],
                inverse_name="mentions",
            ),
        ]
        
        for t in builtins:
            self._types[t.name] = t
            
    def register(self, edge_type: EdgeType):
        self._types[edge_type.name] = edge_type
        logger.debug("RelationshipRegistry: registered '%s'", edge_type.name)
        
    def get(self, name: str) -> EdgeType | None:
        return self._types.get(name)
        
    def list_types(self) -> list[str]:
        return list(self._types.keys())
        
    def is_valid(self, name: str) -> bool:
        return name in self._types
        
    def get_inverse(self, name: str) -> str | None:
        t = self.get(name)
        if not t: return None
        if t.symmetric: return name
        return t.inverse_name

relationship_registry = RelationshipRegistry()
