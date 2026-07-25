import asyncio
import time
from typing import Dict, Any, Optional
from jatayu.core.events import EventBus

class BrowserSession:
    """Manages a persistent browser session."""
    
    def __init__(self, session_id: str, events: EventBus, settings: Dict[str, Any]):
        self.session_id = session_id
        self.events = events
        self.settings = settings
        self.is_running = False
        self.current_url: Optional[str] = None
        self.tabs = []
        
        # In a real implementation, this would hold the Playwright browser instance
        self._browser = None
        
    def start(self):
        """Initializes the browser."""
        if self.is_running:
            return
            
        self.is_running = True
        time.sleep(0.5)
        
        self.tabs = ["tab_1"]
        
        # Publish event
        if self.events:
            self.events.publish("browser_started", {
                "session_id": self.session_id,
                "timestamp": time.time()
            })
        
    def stop(self):
        """Closes the browser session."""
        if not self.is_running:
            return
            
        self.is_running = False
        self.tabs = []
        self.current_url = None
        
        if self.events:
            self.events.publish("browser_closed", {
                "session_id": self.session_id
            })
        
    def navigate(self, url: str) -> bool:
        """Navigates the active tab to a URL."""
        if not self.is_running:
            self.start()
            
        time.sleep(1.0)
        self.current_url = url
        
        if self.events:
            self.events.publish("page_loaded", {
                "session_id": self.session_id,
                "url": url
            })
        
        return True

class SessionManager:
    """Manages multiple persistent browser sessions."""
    
    def __init__(self, events: EventBus):
        self.events = events
        self.sessions: Dict[str, BrowserSession] = {}
        self.settings: Dict[str, Any] = {
            "headless": True,
            "timeout_ms": 30000,
            "max_tabs": 10
        }
        
    def configure(self, settings: Dict[str, Any]):
        """Updates global browser settings."""
        self.settings.update(settings)
        
    def get_or_create_session(self, session_id: str = "default") -> BrowserSession:
        """Retrieves an existing session or creates a new one."""
        if session_id not in self.sessions:
            session = BrowserSession(session_id, self.events, self.settings)
            self.sessions[session_id] = session
            session.start()
        return self.sessions[session_id]
        
    def shutdown_all(self):
        """Gracefully shuts down all active sessions."""
        for session in self.sessions.values():
            session.stop()
        self.sessions.clear()
