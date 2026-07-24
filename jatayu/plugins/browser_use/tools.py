from typing import Dict, Any, List
import asyncio
from jatayu.core.execution import ExecutionResult
from .session import SessionManager

class BrowserTools:
    """Tool handlers for browser-use capabilities."""
    
    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        
    def browser_search(self, args: Dict[str, Any]) -> ExecutionResult:
        query = args.get("query", "")
        if not query:
            return ExecutionResult(status="error", summary="Query is required.", errors=["Missing query parameter"])
            
        session = self.session_manager.get_or_create_session()
        session.navigate(f"https://google.com/search?q={query}")
        
        return ExecutionResult(
            status="success",
            summary=f"Searched for '{query}'",
            artifacts={"current_url": session.current_url}
        )
        
    def browser_open(self, args: Dict[str, Any]) -> ExecutionResult:
        url = args.get("url", "")
        if not url:
            return ExecutionResult(status="error", summary="URL is required.", errors=["Missing url parameter"])
            
        session = self.session_manager.get_or_create_session()
        session.navigate(url)
        
        return ExecutionResult(
            status="success",
            summary=f"Opened {url}",
            data={"current_url": session.current_url}
        )
        
    def browser_extract(self, args: Dict[str, Any]) -> ExecutionResult:
        session = self.session_manager.get_or_create_session()
        if not session.current_url:
            return ExecutionResult(status="error", summary="No active page to extract from.")
            
        content = f"This is simulated extracted content from the browser for {session.current_url}."
        
        # Publish event so KnowledgeManager can auto-index it
        if self.session_manager.events:
            self.session_manager.events.publish("DocumentCreated", {
                "title": f"Web Extract: {session.current_url}",
                "content": content,
                "collection": "research"
            })
            
        return ExecutionResult(
            status="success",
            summary=f"Extracted content from {session.current_url}",
            data={
                "content": content
            }
        )
        
    def browser_screenshot(self, args: Dict[str, Any]) -> ExecutionResult:
        session = self.session_manager.get_or_create_session()
        if not session.current_url:
            return ExecutionResult(status="error", summary="No active page to screenshot.")
            
        # Simulate screenshot taking
        import time
        time.sleep(0.5)
        
        return ExecutionResult(
            status="success",
            summary=f"Took screenshot of {session.current_url}",
            artifacts={
                "image_path": f"/tmp/screenshot_{session.session_id}.png"
            }
        )
        
    def get_registered_tools(self) -> Dict[str, Any]:
        """Returns the mapping of capability names to their handlers."""
        return {
            "browser_search": self.browser_search,
            "browser_open": self.browser_open,
            "browser_extract": self.browser_extract,
            "browser_screenshot": self.browser_screenshot
        }
