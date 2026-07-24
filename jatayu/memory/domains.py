"""Memory Domains — standard classifications for stored knowledge."""

MEMORY_DOMAINS = [
    "personal",    # User identity, preferences
    "projects",    # Active projects and their context
    "clients",     # Client information
    "meetings",    # Meeting notes and decisions
    "research",    # Research findings
    "content",     # Content ideas and plans
    "tasks",       # Task history (beyond daily schedule)
    "sops",        # Standard operating procedures
    "knowledge",   # General organizational knowledge
    "ideas",       # Raw ideas and brainstorms
]

def map_legacy_category(category: str) -> str:
    """Map legacy memory categories to new domains."""
    mapping = {
        "identity": "personal",
        "preference": "personal",
        "work": "projects",
        "general": "knowledge"
    }
    return mapping.get(category.lower(), "knowledge")
