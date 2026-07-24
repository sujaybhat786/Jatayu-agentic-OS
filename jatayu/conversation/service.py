import logging
from jatayu.core.events import EventBus
from jatayu.conversation.models import Conversation, Message
from jatayu.conversation.store import ConversationStore

logger = logging.getLogger(__name__)

class ConversationService:
    """Core service for managing persistent conversation history."""
    
    def __init__(self, db_path: str, event_bus: EventBus):
        self._store = ConversationStore(db_path)
        self._events = event_bus

    def create_conversation(self, title: str | None = None, session_id: str | None = None, provider: str = "dashboard", model: str | None = None) -> str:
        """Create a new conversation."""
        conv = Conversation(
            title=title,
            session_id=session_id,
            last_provider=provider,
            last_model=model
        )
        self._store.insert_conversation(conv)
        self._events.publish("ConversationCreated", {"conversation_id": conv.id})
        return conv.id

    def append_message(
        self, 
        conversation_id: str, 
        role: str, 
        content: str, 
        status: str = "complete",
        provider: str = "dashboard",
        parent_message_id: str | None = None,
        context_tag: str | None = None
    ) -> str:
        """Append a message to a conversation."""
        msg = Message(
            conversation_id=conversation_id,
            role=role,
            content=content,
            status=status,
            provider=provider,
            parent_message_id=parent_message_id,
            context_tag=context_tag
        )
        self._store.insert_message(msg)
        self._events.publish("MessageCreated", {"message_id": msg.id, "conversation_id": conversation_id, "role": role})
        return msg.id

    def update_message_status(self, message_id: str, status: str, content: str | None = None) -> None:
        """Update the status (and optionally content) of an existing message."""
        self._store.update_message_status(message_id, status, content)

    def get_conversation(self, conversation_id: str) -> dict | None:
        """Get full conversation details including recent messages."""
        conv = self._store.get_conversation(conversation_id)
        if not conv:
            return None
            
        messages = self._store.get_messages(conversation_id)
        
        return {
            "conversation": conv,
            "messages": messages
        }

    def get_recent_messages(self, conversation_id: str, limit: int = 50) -> list[Message]:
        """Get recent messages for a conversation."""
        return self._store.get_messages(conversation_id, limit=limit)

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        """List all conversations ordered by recent activity."""
        return self._store.list_conversations(limit, offset)

    def delete_conversation(self, conversation_id: str) -> bool:
        """Delete a conversation and all its messages."""
        deleted = self._store.delete_conversation(conversation_id)
        if deleted:
            self._events.publish("ConversationDeleted", {"conversation_id": conversation_id})
        return deleted

    def keyword_search(self, query: str, limit: int = 20) -> list[Message]:
        """Search across all message history."""
        return self._store.keyword_search(query, limit)
