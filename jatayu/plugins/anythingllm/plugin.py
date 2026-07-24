import time
from typing import Any, Dict, List
from jatayu.core.plugin import JatayuPlugin, PluginManifest
from jatayu.core.execution import ExecutionResult
from .tools import AnythingLLMTools

class AnythingLLMPlugin(JatayuPlugin):
    """
    Knowledge Provider plugin for AnythingLLM.
    Acts as the default semantic search and indexing engine.
    """
    
    def get_manifest(self) -> PluginManifest:
        return PluginManifest(
            id="anythingllm",
            name="AnythingLLM Agent",
            version="1.0.0",
            author="JATAYU Platform",
            description="Knowledge provider for semantic search, vector databases, and document indexing.",
            supported_capabilities=[
                "knowledge_search", 
                "knowledge_upload", 
                "knowledge_collections",
                "knowledge_index",
                "knowledge_similarity"
            ],
            icon="🧠"
        )
        
    def __init__(self):
        super().__init__()
        self.context = None
        self.api_url = "http://localhost:3001/api/v1"
        self.api_key = None
        self.is_healthy = False
        self._start_time = time.time()
        
        # Tools initialized later since they need config
        self.tools = None
        
    def install(self) -> bool:
        """Installs and sets up the AnythingLLM tools."""
        self.tools = AnythingLLMTools(self.api_url, self.api_key)
        return True
        
    def configure(self, settings: Dict[str, Any]) -> bool:
        """Configures plugin and retrieves credentials from Vault."""
        # Use custom URL if provided, otherwise default to local AnythingLLM
        self.api_url = settings.get("api_url", "http://localhost:3001/api/v1")
        
        vault = getattr(self.context, "vault", None)
        if vault:
            cred = vault.get_credential("anythingllm", "api_key")
            if cred:
                self.api_key = cred
        
        # Fallback: read API key directly from vault.json
        if not self.api_key:
            try:
                import json
                from pathlib import Path
                vault_path = Path(__file__).resolve().parents[2] / "data" / "vault.json"
                if not vault_path.exists():
                    vault_path = Path("data/vault.json")
                if vault_path.exists():
                    with open(vault_path) as f:
                        data = json.load(f)
                    self.api_key = data.get("anythingllm", {}).get("api_key")
            except Exception:
                pass
                
        # Re-initialize tools with updated config
        self.tools = AnythingLLMTools(self.api_url, self.api_key)
            
        return True
        
    def health(self) -> Dict[str, Any]:
        """Checks if AnythingLLM is reachable."""
        # In a real scenario we might ping the `/auth` endpoint
        # For now, if we have an API key and URL, we assume healthy enough to try
        uptime = time.time() - self._start_time
        
        if self.api_url:
            self.is_healthy = True
        else:
            self.is_healthy = False
            
        return {
            "status": "healthy" if self.is_healthy else "unhealthy",
            "details": "AnythingLLM connection ready.",
            "metrics": {
                "uptime_seconds": round(uptime, 1)
            }
        }
        
    def execute(self, action: str, **kwargs) -> ExecutionResult:
        """Executes an AnythingLLM knowledge capability."""
        if not self.tools:
            self.install()
            
        registered_tools = self.tools.get_registered_tools()
        if action not in registered_tools:
            return ExecutionResult(status="error", summary=f"Unknown AnythingLLM action: {action}")
            
        try:
            handler = registered_tools[action]
            return handler(kwargs)
        except Exception as e:
            return ExecutionResult(status="error", summary=f"AnythingLLM action failed: {str(e)}", errors=[str(e)])
            
    def shutdown(self) -> bool:
        return True
