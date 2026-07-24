from typing import Dict, Any, List
import time

from jatayu.core.plugin import JatayuPlugin
from jatayu.core.execution import ExecutionResult
from .session import SessionManager
from .tools import BrowserTools

class BrowserUsePlugin(JatayuPlugin):
    """
    Browser-use Plugin for JATAYU.
    Provides persistent browser automation capabilities.
    """
    
    def get_manifest(self) -> Any:
        from jatayu.core.plugin import PluginManifest
        return PluginManifest(
            id="browser_use",
            name="Browser-use Agent",
            version="1.0.0",
            author="JATAYU Platform",
            description="Browser automation and web interaction capabilities.",
            supported_capabilities=["browser_search", "browser_open", "browser_extract", "browser_screenshot"],
            icon="🌐"
        )
        
    def __init__(self):
        super().__init__()
        self.context = None # Will be set by PluginManager
        self.session_manager = SessionManager(events=None)
        self.tools = BrowserTools(self.session_manager)
        self.is_healthy = False
        self._start_time = time.time()
        
    def install(self) -> bool:
        """Installs necessary browser dependencies."""
        # Setup event bus from context
        events = getattr(self.context, "events", None)
        self.session_manager = SessionManager(events)
        self.tools = BrowserTools(self.session_manager)
        return True
        
    def configure(self, settings: Dict[str, Any]) -> bool:
        """Configures the plugin settings and retrieves credentials."""
        if self.session_manager:
            self.session_manager.configure(settings)
            
        # Example: Fetching optional proxy auth from vault
        vault = getattr(self.context, "vault", None)
        if vault:
            proxy_cred = vault.get_credential("browser_use", "proxy")
            if proxy_cred:
                self.session_manager.settings["proxy"] = proxy_cred.get("value")
                
        return True
        
    def health(self) -> Dict[str, Any]:
        """Returns the health status of the browser integration."""
        uptime = time.time() - self._start_time
        active_sessions = len(self.session_manager.sessions) if self.session_manager else 0
        
        self.is_healthy = True
        
        return {
            "status": "healthy" if self.is_healthy else "unhealthy",
            "details": "Browser sessions active and ready.",
            "metrics": {
                "uptime_seconds": round(uptime, 1),
                "active_sessions": active_sessions
            }
        }
        
    def execute(self, action: str, **kwargs) -> ExecutionResult:
        """Executes a browser tool/capability."""
        if not self.tools:
            return ExecutionResult(status="error", summary="Plugin not initialized.")
            
        registered_tools = self.tools.get_registered_tools()
        if action not in registered_tools:
            return ExecutionResult(status="error", summary=f"Unknown browser action: {action}")
            
        try:
            handler = registered_tools[action]
            return handler(kwargs)
        except Exception as e:
            return ExecutionResult(status="error", summary=f"Browser action failed: {str(e)}", errors=[str(e)])
            
    def shutdown(self) -> bool:
        """Gracefully closes all browser sessions."""
        if self.session_manager:
            self.session_manager.shutdown_all()
        return True
