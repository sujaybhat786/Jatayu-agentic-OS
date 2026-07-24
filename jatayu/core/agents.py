"""Agent Registry — metadata registry for all connected AI systems.

Agents register their capabilities, health status, and connection details here.
This allows the orchestrator to dynamically discover and route tasks to
available agents.
"""

from __future__ import annotations

import httpx
from dataclasses import dataclass, field


@dataclass
class AgentInfo:
    """Metadata for a connected AI agent or integration."""
    name: str                           # e.g., "hermes"
    display_name: str                   # e.g., "Hermes Agent"
    purpose: str                        # What this agent does
    capabilities: list[str]             # Capability names it can fulfill
    status: str                         # "connected" | "disconnected" | "error"
    version: str                        # e.g., "1.0.0"
    url: str                            # Connection endpoint
    auth_type: str                      # "bearer" | "api_key" | "none"
    health_endpoint: str                # For health checks
    priority: int = 1                   # Higher = preferred
    dependencies: list[str] = field(default_factory=list)
    # ── Model routing fields (Brain Contract v1: Agent owns model preference) ──
    preferred_model: str = "gemini-3.5-flash"     # Primary model this agent requests
    backup_model: str = "gemini-3.5-flash"        # Fallback if primary unavailable
    preferred_tools: list[str] = field(default_factory=list)  # Tool subset this agent uses
    latency_target_ms: int = 3000                 # Expected response time budget
    estimated_cost_per_call: float = 0.0          # Cost hint for budget-aware routing

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "purpose": self.purpose,
            "capabilities": self.capabilities,
            "status": self.status,
            "version": self.version,
            "url": self.url,
            "auth_type": self.auth_type,
            "health_endpoint": self.health_endpoint,
            "priority": self.priority,
            "dependencies": self.dependencies,
            "preferred_model": self.preferred_model,
            "backup_model": self.backup_model,
            "preferred_tools": self.preferred_tools,
            "latency_target_ms": self.latency_target_ms,
        }


class AgentRegistry:
    """Central registry of all available agents."""

    def __init__(self):
        self._agents: dict[str, AgentInfo] = {}

        # ── Pre-register known agents (Default: connected via local fallback) ──
        self.register(AgentInfo(
            name="hermes",
            display_name="Hermes Agent",
            purpose="Desktop Execution and Coding",
            capabilities=["delegate_coding", "control_desktop"],
            status="connected",
            version="1.0",
            url="http://127.0.0.1:8642",
            auth_type="none",
            health_endpoint="/v1/models",
            preferred_model="gemini-3.1-pro-preview",
            backup_model="gemini-3.5-flash",
            latency_target_ms=5000,
        ))
        self.register(AgentInfo(
            name="openclaw",
            display_name="OpenClaw Agent",
            purpose="Conversation Interface and Actions",
            capabilities=["delegate_action"],
            status="connected",
            version="1.0",
            url="http://127.0.0.1:8643",
            auth_type="none",
            health_endpoint="/api/status",
            preferred_model="gemini-3.5-flash",
            backup_model="gemini-3.5-flash",
            latency_target_ms=3000,
        ))
        self.register(AgentInfo(
            name="obsidian",
            display_name="Obsidian Integration",
            purpose="Knowledge Vault & Memory Repository",
            capabilities=["create_note", "read_note", "search_knowledge"],
            status="connected",
            version="1.0",
            url="http://127.0.0.1:27123",
            auth_type="bearer",
            health_endpoint="/",
            preferred_model="gemini-3.5-flash",
            backup_model="gemini-3.5-flash",
        ))
        self.register(AgentInfo(
            name="notion",
            display_name="Notion Integration",
            purpose="Documentation and Wiki",
            capabilities=["create_note", "read_note", "search_knowledge"],
            status="connected",
            version="1.0",
            url="https://api.notion.com/v1",
            auth_type="bearer",
            health_endpoint="",
            preferred_model="gemini-3.5-flash",
            backup_model="gemini-3.5-flash",
        ))
        self.register(AgentInfo(
            name="telegram",
            display_name="Telegram Comms",
            purpose="Messaging and Remote Dispatch",
            capabilities=["messaging", "remote_dispatch"],
            status="connected",
            version="1.0",
            url="https://api.telegram.org",
            auth_type="bearer",
            health_endpoint="",
            preferred_model="gemini-3.5-flash",
            backup_model="gemini-3.5-flash",
        ))
        self.register(AgentInfo(
            name="gemini",
            display_name="Gemini Core",
            purpose="Reasoning and Conversation",
            capabilities=["conversation", "reasoning", "email", "calendar", "memory",
                          "reminder", "research", "creative_writing", "document",
                          "spreadsheet", "meeting", "social_media", "task_management"],
            status="connected",
            version="3.5-flash",
            url="via SDK",
            auth_type="api_key",
            health_endpoint="",
            preferred_model="gemini-3.5-flash",
            backup_model="gemini-3.5-flash",
            latency_target_ms=3000,
        ))

    def register(self, agent: AgentInfo) -> None:
        """Register or update an agent."""
        self._agents[agent.name] = agent

    def get(self, name: str) -> AgentInfo | None:
        """Look up an agent by name."""
        return self._agents.get(name)

    def list_agents(self) -> list[AgentInfo]:
        """Return all registered agents."""
        return list(self._agents.values())

    def get_by_capability(self, capability: str) -> list[AgentInfo]:
        """Find agents that support a specific capability."""
        return sorted(
            [a for a in self._agents.values() if capability in a.capabilities],
            key=lambda x: x.priority,
            reverse=True
        )

    def check_health(self, name: str) -> bool:
        """Ping an agent's health endpoint to check status.
        Falls back to local operational readiness if HTTP endpoint is offline.
        """
        agent = self.get(name)
        if not agent:
            return False

        if not agent.health_endpoint or not agent.url.startswith("http"):
            agent.status = "connected"
            return True

        url = f"{agent.url.rstrip('/')}{agent.health_endpoint}"
        try:
            with httpx.Client(timeout=1.0) as client:
                resp = client.get(url)
                if resp.status_code in (200, 401, 403):
                    agent.status = "connected"
                    return True
        except Exception:
            pass

        agent.status = "disconnected"
        return False

    def check_all_health(self) -> dict[str, bool]:
        """Ping all agents to update statuses."""
        results = {}
        for name in self._agents:
            results[name] = self.check_health(name)
        return results

    def to_dict(self) -> dict:
        """Serialize for API responses."""
        return {name: agent.to_dict() for name, agent in self._agents.items()}
