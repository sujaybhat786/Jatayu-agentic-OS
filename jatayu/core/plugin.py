"""Plugin SDK — Base classes and manifest for JATAYU plugins."""

from dataclasses import dataclass, field
from typing import Any, Callable

from jatayu.tools import Tool
from jatayu.core.capabilities import Capability

@dataclass
class PluginManifest:
    """Metadata describing a plugin."""
    id: str
    name: str
    version: str
    author: str
    description: str
    supported_capabilities: list[str] = field(default_factory=list)
    required_permissions: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    min_jatayu_version: str = "1.0.0"
    icon: str = "🧩"
    status: str = "active"


class JatayuPlugin:
    """Base class that all JATAYU plugins must inherit from."""
    
    def __init__(self):
        self.manifest = self.get_manifest()

    def get_manifest(self) -> PluginManifest:
        """Return the plugin's manifest."""
        raise NotImplementedError
        
    def install(self) -> bool:
        """Called when the plugin is first installed."""
        return True
        
    def configure(self, config: dict[str, Any]) -> None:
        """Called to configure the plugin with settings."""
        pass
        
    def health(self) -> dict[str, Any]:
        """Return health status of the plugin."""
        return {"status": "healthy"}
        
    def execute(self, capability: str, **kwargs) -> Any:
        """Execute a specific capability."""
        raise NotImplementedError
        
    def shutdown(self) -> None:
        """Called when the plugin is disabled or OS shuts down."""
        pass
        
    def get_capabilities(self) -> list[Capability]:
        """Return the capabilities provided by this plugin."""
        return []
        
    def get_tools(self) -> list[Tool]:
        """Return the tools provided by this plugin."""
        return []
        
    def status(self) -> str:
        """Return a quick status string."""
        return "running"
        
    def version(self) -> str:
        """Return the plugin version."""
        return self.manifest.version
