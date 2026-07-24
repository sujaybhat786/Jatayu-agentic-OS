"""Capability Registry — maps abstract capabilities to concrete tools.

JATAYU thinks in capabilities (e.g., "browse_web", "store_memory") rather
than specific agents. This layer determines which tool is best suited
for a requested capability.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Capability:
    """A high-level capability the OS can perform."""
    name: str                           # e.g., "browse_web"
    description: str                    # Human-readable description
    category: str                       # e.g., "research", "execution"
    tool_names: list[str]               # Ordered list of tools that can fulfill this
    required: bool = False              # Is this capability mandatory for core OS function?

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "tool_names": self.tool_names,
            "required": self.required,
        }


class CapabilityRegistry:
    """Registry mapping capabilities to tools."""

    def __init__(self):
        self._capabilities: dict[str, Capability] = {}

        # ── Pre-register core OS capabilities ──
        self.register(Capability(
            name="store_memory",
            description="Store long-term knowledge",
            category="memory",
            tool_names=["remember"],
            required=True
        ))
        self.register(Capability(
            name="retrieve_memory",
            description="Fetch stored knowledge",
            category="memory",
            tool_names=["list_memories"],
            required=True
        ))
        self.register(Capability(
            name="search_knowledge",
            description="Search external knowledge bases",
            category="knowledge",
            tool_names=["notion_search", "obsidian_search"]
        ))
        self.register(Capability(
            name="create_note",
            description="Create a new document or note",
            category="knowledge",
            tool_names=["obsidian_write_note", "notion_create_page"]
        ))
        self.register(Capability(
            name="read_note",
            description="Read a document or note",
            category="knowledge",
            tool_names=["obsidian_read_note", "notion_read_page"]
        ))
        self.register(Capability(
            name="create_task",
            description="Create a new task",
            category="productivity",
            tool_names=["add_task"]
        ))
        self.register(Capability(
            name="update_task",
            description="Complete or update a task",
            category="productivity",
            tool_names=["complete_task"]
        ))
        self.register(Capability(
            name="draft_email",
            description="Draft a message or email",
            category="communication",
            tool_names=["draft_message"]
        ))
        self.register(Capability(
            name="set_reminder",
            description="Set a time-based reminder",
            category="productivity",
            tool_names=["set_reminder"]
        ))
        self.register(Capability(
            name="delegate_coding",
            description="Delegate software engineering tasks",
            category="engineering",
            tool_names=["hermes_ask"]
        ))
        self.register(Capability(
            name="control_desktop",
            description="Automate desktop applications",
            category="execution",
            tool_names=["hermes_ask"]
        ))
        self.register(Capability(
            name="delegate_action",
            description="Delegate general real-world actions",
            category="execution",
            tool_names=["openclaw_ask"]
        ))

    def register(self, capability: Capability) -> None:
        """Register or update a capability."""
        self._capabilities[capability.name] = capability

    def get(self, name: str) -> Capability | None:
        """Look up a capability by name."""
        return self._capabilities.get(name)

    def resolve(self, name: str) -> str | None:
        """Find the highest-priority available tool for a capability."""
        cap = self.get(name)
        if not cap or not cap.tool_names:
            return None
        
        # In the future, this would check tool/agent health.
        # For now, it returns the first registered tool.
        return cap.tool_names[0]

    def list_capabilities(self) -> list[Capability]:
        """Return all registered capabilities."""
        return list(self._capabilities.values())

    def list_by_category(self, category: str) -> list[Capability]:
        """Return capabilities filtered by category."""
        return [c for c in self._capabilities.values() if c.category == category]

    def to_dict(self) -> dict:
        """Serialize for API responses."""
        return {name: cap.to_dict() for name, cap in self._capabilities.items()}
