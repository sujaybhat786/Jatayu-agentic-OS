import logging
from typing import Any, Dict, List, Optional
from jatayu.core.events import EventBus
from jatayu.core.plugin_manager import PluginManager
from jatayu.core.vault import Vault

logger = logging.getLogger(__name__)

class KnowledgeManager:
    """Central routing and management layer for all Knowledge operations.
    Acts as the intelligence layer between the Brain and Knowledge Providers.
    """
    
    def __init__(self, events: EventBus, plugin_manager: PluginManager, vault: Vault):
        self.events = events
        self.plugin_manager = plugin_manager
        self.vault = vault
        
        # Subscribe to Event Bus for automatic indexing
        self.events.subscribe("DocumentCreated", self._on_document_created)
        self.events.subscribe("FileDownloaded", self._on_document_created)
        
    def _get_active_provider(self, capability: str) -> Optional[Any]:
        """Returns the first plugin that supports the given capability."""
        for plugin in self.plugin_manager.plugins.values():
            if capability in plugin.manifest.supported_capabilities:
                return plugin
        return None
        
    def search(self, query: str, collection: str = "default") -> Dict[str, Any]:
        """Searches the active knowledge provider."""
        provider = self._get_active_provider("knowledge_search")
        if not provider:
            return {"status": "error", "summary": "No active knowledge provider found for searching."}
            
        result = provider.execute("knowledge_search", {"query": query, "collection": collection})
        return {
            "status": result.status,
            "summary": result.summary,
            "artifacts": result.artifacts,
            "errors": result.errors
        }
        
    def upload(self, content: str, title: str, collection: str = "default") -> Dict[str, Any]:
        """Uploads and indexes a document in the active knowledge provider."""
        provider = self._get_active_provider("knowledge_upload")
        if not provider:
            return {"status": "error", "summary": "No active knowledge provider found for uploading."}
            
        result = provider.execute("knowledge_upload", {"content": content, "title": title, "collection": collection})
        
        if result.status == "success":
            self.events.publish("KnowledgeIndexed", {"title": title, "collection": collection})
            
        return {
            "status": result.status,
            "summary": result.summary,
            "artifacts": result.artifacts,
            "errors": result.errors
        }
        
    def list_collections(self) -> Dict[str, Any]:
        """Lists available knowledge collections."""
        provider = self._get_active_provider("knowledge_collections")
        if not provider:
            return {"status": "error", "summary": "No active knowledge provider found for collections."}
            
        result = provider.execute("knowledge_collections", {})
        return {
            "status": result.status,
            "summary": result.summary,
            "artifacts": result.artifacts,
            "errors": result.errors
        }
        
    def _on_document_created(self, event_type: str, data: Dict[str, Any]):
        """Event handler for automatic indexing."""
        logger.info(f"KnowledgeManager received {event_type} event: {data}")
        # When a document is created (e.g. by Browser-use), we extract its text and upload it.
        content = data.get("content", "")
        title = data.get("title", f"Auto-indexed document from {event_type}")
        collection = data.get("collection", "default")
        
        if content:
            logger.info(f"Auto-indexing document: {title}")
            self.upload(content, title, collection)
