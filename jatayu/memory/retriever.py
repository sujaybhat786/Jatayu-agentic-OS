"""Context Retrieval — relevance-filtered memory for the Brain.

Delegates to MemoryStore (SQLite + FTS5).
"""

from __future__ import annotations

from jatayu.memory.store import get_store

DEFAULT_TOP_K = 15


class ContextRetriever:
    """Retrieves and formats relevant memories using MemoryStore."""

    def retrieve_for_prompt(
        self,
        user_input: str = "",
        top_k: int = DEFAULT_TOP_K,
    ) -> str:
        return get_store().retrieve_for_prompt(user_text=user_input, top_k=top_k)
