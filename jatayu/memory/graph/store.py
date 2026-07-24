"""Relationship Graph Store."""

import json
import logging
from pathlib import Path
from jatayu.config import get_config
from jatayu.memory.graph.models import Edge, _now
from jatayu.memory.graph.registry import relationship_registry

logger = logging.getLogger(__name__)

class RelationshipGraph:
    """Store and traverse typed relationship edges."""
    
    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir or get_config()["data_dir"])
        self.path = self.data_dir / "memory_graph.json"
        self._edges: list[Edge] = []
        self._load()

    def _load(self):
        if self.path.exists():
            try:
                with open(self.path, "r") as f:
                    data = json.load(f)
                    self._edges = [Edge.from_dict(d) for d in data]
            except Exception as e:
                logger.error("Failed to load graph: %s", e)
                self._edges = []
                
    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(self.path, "w") as f:
                json.dump([e.to_dict() for e in self._edges], f, indent=2)
        except Exception as e:
            logger.error("Failed to save graph: %s", e)

    def add_edge(self, source_id: str, target_id: str, edge_type: str, 
                 source_name: str = "", target_name: str = "", 
                 confidence: float = 1.0) -> Edge | None:
        if not relationship_registry.is_valid(edge_type):
            logger.warning("Graph: unknown edge type '%s'", edge_type)
            return None
            
        # Check if exists to update
        for e in self._edges:
            if e.source_id == source_id and e.target_id == target_id and e.edge_type == edge_type:
                # Conflict Resolution
                snapshot = {
                    "confidence": e.confidence,
                    "source_name": e.source_name,
                    "target_name": e.target_name,
                    "timestamp": _now()
                }
                e.history.append(snapshot)
                
                # Update logic (prefer user-confirmed information - in this simplistic model, latest write with higher/equal confidence wins)
                if confidence >= e.confidence:
                    e.confidence = confidence
                    if source_name: e.source_name = source_name
                    if target_name: e.target_name = target_name
                
                e.version += 1
                e.updated_at = _now()
                self._save()
                return e
                
        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            edge_type=edge_type,
            source_name=source_name,
            target_name=target_name,
            confidence=confidence
        )
        self._edges.append(edge)
        self._save()
        return edge

    def remove_edge(self, source_id: str, target_id: str, edge_type: str) -> bool:
        initial = len(self._edges)
        self._edges = [e for e in self._edges if not (
            e.source_id == source_id and 
            e.target_id == target_id and 
            e.edge_type == edge_type
        )]
        if len(self._edges) < initial:
            self._save()
            return True
        return False

    def get_edges(self, entity_id: str) -> list[Edge]:
        """Get all edges where entity is source or target."""
        return [e for e in self._edges if e.source_id == entity_id or e.target_id == entity_id]
        
    def get_neighbors(self, entity_id: str) -> dict[str, list[Edge]]:
        """Return dict of neighbor_id -> list of edges connecting them."""
        neighbors = {}
        for e in self.get_edges(entity_id):
            n_id = e.target_id if e.source_id == entity_id else e.source_id
            if n_id not in neighbors:
                neighbors[n_id] = []
            neighbors[n_id].append(e)
        return neighbors

    def get_outgoing(self, source_id: str, edge_type: str | None = None) -> list[Edge]:
        return [e for e in self._edges if e.source_id == source_id and (edge_type is None or e.edge_type == edge_type)]
        
    def get_incoming(self, target_id: str, edge_type: str | None = None) -> list[Edge]:
        return [e for e in self._edges if e.target_id == target_id and (edge_type is None or e.edge_type == edge_type)]
