"""Plugin Discovery & Management Engine."""

import importlib
import logging
import os
import sys
from pathlib import Path

from jatayu.core.plugin import JatayuPlugin
from jatayu.tools import ToolRegistry
from jatayu.core.capabilities import CapabilityRegistry

logger = logging.getLogger(__name__)

class PluginManager:
    """Discovers, loads, and manages lifecycle of plugins."""
    
    def __init__(self, capability_registry: CapabilityRegistry, tool_registry: ToolRegistry):
        self.plugins: dict[str, JatayuPlugin] = {}
        self.capabilities = capability_registry
        self.tools = tool_registry
        
        # Determine the absolute path to the plugins directory
        # which is jatayu/plugins
        base_dir = Path(__file__).parent.parent
        self.plugins_dir = base_dir / "plugins"
        
        if not self.plugins_dir.exists():
            self.plugins_dir.mkdir(parents=True, exist_ok=True)
            
    def discover_and_load(self):
        """Scan the plugins directory and load all valid plugins."""
        logger.info(f"Scanning for plugins in {self.plugins_dir}")
        
        # Ensure plugins dir is in sys.path for importing
        parent_dir = str(self.plugins_dir.parent.parent)
        if parent_dir not in sys.path:
            sys.path.insert(0, parent_dir)
            
        for entry in os.scandir(self.plugins_dir):
            if entry.is_dir() and not entry.name.startswith((".", "__")):
                self._load_plugin(entry.name)
                
    def _load_plugin(self, plugin_name: str):
        """Attempt to load a specific plugin by folder name."""
        try:
            from jatayu.config import get_config
            cfg = get_config()
            integrations = cfg.get("integrations", {})
            plugin_cfg = integrations.get(plugin_name, {})
            if isinstance(plugin_cfg, dict) and plugin_cfg.get("enabled") is False:
                logger.info(f"Plugin {plugin_name} is disabled in config.yaml — skipping load.")
                return
        except Exception:
            pass

        module_path = f"jatayu.plugins.{plugin_name}.plugin"
        try:
            # Import the module dynamically
            module = importlib.import_module(module_path)
            
            # Find the JatayuPlugin subclass
            plugin_class = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if isinstance(attr, type) and issubclass(attr, JatayuPlugin) and attr is not JatayuPlugin:
                    plugin_class = attr
                    break
                    
            if not plugin_class:
                logger.warning(f"No JatayuPlugin subclass found in {module_path}")
                return
                
            # Instantiate and register
            plugin = plugin_class()
            manifest = plugin.manifest
            
            # Health check before enabling
            health = plugin.health()
            if health.get("status") != "healthy":
                logger.warning(f"Plugin {manifest.name} loaded but reported unhealthy: {health}")
                # We still load it, but maybe flag it.
                
            self.plugins[manifest.id] = plugin
            
            # Register capabilities
            for cap in plugin.get_capabilities():
                self.capabilities.register(cap)
                
            # Register tools
            for tool in plugin.get_tools():
                self.tools.register(tool)
                
            logger.info(f"Loaded plugin: {manifest.name} v{manifest.version}")
            
        except Exception as e:
            logger.error(f"Failed to load plugin {plugin_name}: {e}")

    def get(self, plugin_id: str) -> JatayuPlugin | None:
        """Retrieve a loaded plugin by its ID."""
        return self.plugins.get(plugin_id)

    def to_dict(self) -> dict:

        """Return a dictionary representation of loaded plugins."""
        return {
            pid: {
                "id": p.manifest.id,
                "name": p.manifest.name,
                "version": p.manifest.version,
                "description": p.manifest.description,
                "status": p.status(),
                "health": p.health(),
            } for pid, p in self.plugins.items()
        }
