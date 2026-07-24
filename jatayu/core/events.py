"""Internal Event Bus for loose coupling between plugins."""

import asyncio
import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Callback can be sync or async
Callback = Callable[[Any], Awaitable[None] | None]

class EventBus:
    """A lightweight pub/sub event bus."""
    
    def __init__(self):
        self._subscribers: dict[str, list[Callback]] = {}
        
    def subscribe(self, event_type: str, callback: Callback):
        """Subscribe to a specific event type."""
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(callback)
        logger.debug(f"Subscribed to event: {event_type}")
        
    def publish(self, event_type: str, data: Any = None):
        """Publish an event to all subscribers asynchronously."""
        logger.debug(f"Publishing event: {event_type}")
        if event_type in self._subscribers:
            for callback in self._subscribers[event_type]:
                # We use asyncio.create_task to run without blocking the publisher
                # If callback is sync, we wrap it
                if asyncio.iscoroutinefunction(callback):
                    asyncio.create_task(callback(data))
                else:
                    try:
                        callback(data)
                    except Exception as e:
                        logger.error(f"Error in sync event callback for {event_type}: {e}")
