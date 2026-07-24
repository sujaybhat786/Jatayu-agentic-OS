"""Graph Context Retriever.

Expands context through graph neighbors instead of simple entity lookup.
Integrates with the existing Entity Registry to fetch full records for nodes.
"""

import logging
from jatayu.memory.graph.models import GraphContext, Edge
from jatayu.memory.graph.store import RelationshipGraph

logger = logging.getLogger(__name__)

class GraphContextRetriever:
    """Retrieves related context by expanding graph neighbors."""
    
    def __init__(self, graph: RelationshipGraph, entity_store=None):
        self.graph = graph
        self.entity_store = entity_store
        
    def retrieve(self, primary_entity_ids: list[str], max_depth: int = 1) -> GraphContext:
        """Fetch primary entities, their immediate neighbors, and connecting edges."""
        
        edges: list[Edge] = []
        visited_nodes = set(primary_entity_ids)
        frontier = set(primary_entity_ids)
        
        # Traverse up to max_depth
        for _ in range(max_depth):
            next_frontier = set()
            for node_id in frontier:
                node_edges = self.graph.get_edges(node_id)
                edges.extend(node_edges)
                
                for e in node_edges:
                    neighbor = e.target_id if e.source_id == node_id else e.source_id
                    if neighbor not in visited_nodes:
                        visited_nodes.add(neighbor)
                        next_frontier.add(neighbor)
            frontier = next_frontier
            
        # Deduplicate edges
        unique_edges = { (e.source_id, e.target_id, e.edge_type): e for e in edges }.values()
        
        primary_entities = []
        related_entities = []
        
        if self.entity_store:
            # We don't have direct get_by_id in entity_store currently, it searches by name.
            # But the underlying list_entities can be filtered.
            try:
                all_records = self.entity_store.list_entities()
                record_map = {r.get("id"): r for r in all_records if r.get("id")}
                
                for eid in primary_entity_ids:
                    if eid in record_map:
                        primary_entities.append(record_map[eid])
                        
                related_ids = visited_nodes - set(primary_entity_ids)
                for eid in related_ids:
                    if eid in record_map:
                        related_entities.append(record_map[eid])
            except Exception as e:
                logger.error("Failed to fetch entity records for graph context: %s", e)
                
        return GraphContext(
            primary_entities=primary_entities,
            related_entities=related_entities,
            edges=list(unique_edges),
            memory_facts=[]  # Will be populated by higher layer if needed
        )
