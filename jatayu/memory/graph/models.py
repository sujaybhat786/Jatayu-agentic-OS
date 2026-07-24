"""Graph data models for JATAYU Knowledge Graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def _new_id() -> str:
    return uuid.uuid4().hex[:8]

@dataclass
class EdgeType:
    """Schema for a registered relationship edge type."""
    name: str
    description: str
    symmetric: bool = False
    inverse_name: str | None = None
    allowed_source_types: list[str] | None = None  # None = any
    allowed_target_types: list[str] | None = None  # None = any

@dataclass
class Edge:
    """A typed relationship between two entities."""
    source_id: str
    target_id: str
    edge_type: str
    confidence: float = 1.0
    source_name: str = ""  # cached for readability
    target_name: str = ""  # cached for readability
    version: int = 1
    history: list[dict] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "target_id": self.target_id,
            "edge_type": self.edge_type,
            "confidence": self.confidence,
            "source_name": self.source_name,
            "target_name": self.target_name,
            "version": self.version,
            "history": self.history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Edge:
        return cls(
            source_id=data["source_id"],
            target_id=data["target_id"],
            edge_type=data["edge_type"],
            confidence=data.get("confidence", 1.0),
            source_name=data.get("source_name", ""),
            target_name=data.get("target_name", ""),
            version=data.get("version", 1),
            history=data.get("history", []),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )

@dataclass
class ConfidenceRecord:
    """Tracks confidence, verification, and decay for a flat fact."""
    memory_id: str
    confidence: float = 0.5            # 0.0 to 1.0
    times_used: int = 0
    last_used_at: str | None = None
    verified: bool = False             # user explicitly confirmed
    source: str = "inferred"           # 'inferred', 'explicit_user', 'tool'
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return {
            "memory_id": self.memory_id,
            "confidence": self.confidence,
            "times_used": self.times_used,
            "last_used_at": self.last_used_at,
            "verified": self.verified,
            "source": self.source,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> ConfidenceRecord:
        return cls(
            memory_id=data["memory_id"],
            confidence=data.get("confidence", 0.5),
            times_used=data.get("times_used", 0),
            last_used_at=data.get("last_used_at"),
            verified=data.get("verified", False),
            source=data.get("source", "inferred"),
            created_at=data.get("created_at", _now()),
            updated_at=data.get("updated_at", _now()),
        )

@dataclass
class GraphContext:
    """The expanded context object returned by GraphContextRetriever."""
    primary_entities: list[dict]
    related_entities: list[dict]
    edges: list[Edge]
    memory_facts: list[dict]
    
    def to_dict(self) -> dict:
        return {
            "primary_entities": self.primary_entities,
            "related_entities": self.related_entities,
            "edges": [e.to_dict() for e in self.edges],
            "memory_facts": self.memory_facts,
        }
