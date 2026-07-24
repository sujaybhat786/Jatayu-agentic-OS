from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

@dataclass
class Conversation:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    title: str | None = None
    session_id: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_provider: str | None = None
    last_model: str | None = None
    summary: str | None = None
    token_count: int = 0
    metadata: dict = field(default_factory=dict)

@dataclass
class Message:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    conversation_id: str = ""
    parent_message_id: str | None = None
    role: str = "" # user, assistant, system, tool
    content: str = ""
    status: str = "complete" # pending, streaming, complete, failed
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    provider: str = "dashboard"
    context_tag: str | None = None
    attachments: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
