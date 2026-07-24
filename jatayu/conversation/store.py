import sqlite3
import json
import logging
from pathlib import Path
from jatayu.conversation.models import Conversation, Message

logger = logging.getLogger(__name__)

class ConversationStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id              TEXT PRIMARY KEY,
                title           TEXT,
                session_id      TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                last_provider   TEXT,
                last_model      TEXT,
                summary         TEXT,
                token_count     INTEGER DEFAULT 0,
                metadata        TEXT DEFAULT '{}'
            )
            ''')
            
            cursor.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id                TEXT PRIMARY KEY,
                conversation_id   TEXT NOT NULL,
                parent_message_id TEXT,
                role              TEXT NOT NULL,
                content           TEXT NOT NULL,
                status            TEXT NOT NULL,
                timestamp         TEXT NOT NULL,
                provider          TEXT DEFAULT 'dashboard',
                context_tag       TEXT,
                attachments       TEXT DEFAULT '[]',
                metadata          TEXT DEFAULT '{}',
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            )
            ''')
            
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_messages_timestamp ON messages(timestamp)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_conversations_updated ON conversations(updated_at)')
            conn.commit()
            
    def insert_conversation(self, conv: Conversation) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO conversations (id, title, session_id, created_at, updated_at, last_provider, last_model, summary, token_count, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                conv.id, conv.title, conv.session_id, conv.created_at, conv.updated_at,
                conv.last_provider, conv.last_model, conv.summary, conv.token_count,
                json.dumps(conv.metadata)
            ))
            conn.commit()
            
    def get_conversation(self, conv_id: str) -> Conversation | None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM conversations WHERE id = ?', (conv_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return Conversation(
                id=row['id'],
                title=row['title'],
                session_id=row['session_id'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                last_provider=row['last_provider'],
                last_model=row['last_model'],
                summary=row['summary'],
                token_count=row['token_count'],
                metadata=json.loads(row['metadata'])
            )

    def insert_message(self, msg: Message) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO messages (id, conversation_id, parent_message_id, role, content, status, timestamp, provider, context_tag, attachments, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                msg.id, msg.conversation_id, msg.parent_message_id, msg.role, msg.content,
                msg.status, msg.timestamp, msg.provider, msg.context_tag,
                json.dumps(msg.attachments), json.dumps(msg.metadata)
            ))
            # Also bump updated_at on the conversation
            cursor.execute('''
            UPDATE conversations SET updated_at = ?, last_provider = ? WHERE id = ?
            ''', (msg.timestamp, msg.provider, msg.conversation_id))
            conn.commit()

    def update_message_status(self, msg_id: str, status: str, content: str | None = None) -> None:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            if content is not None:
                cursor.execute('UPDATE messages SET status = ?, content = ? WHERE id = ?', (status, content, msg_id))
            else:
                cursor.execute('UPDATE messages SET status = ? WHERE id = ?', (status, msg_id))
            conn.commit()

    def get_messages(self, conv_id: str, limit: int = 50) -> list[Message]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM messages WHERE conversation_id = ? ORDER BY timestamp ASC LIMIT ?', (conv_id, limit))
            rows = cursor.fetchall()
            
            messages = []
            for row in rows:
                messages.append(Message(
                    id=row['id'],
                    conversation_id=row['conversation_id'],
                    parent_message_id=row['parent_message_id'],
                    role=row['role'],
                    content=row['content'],
                    status=row['status'],
                    timestamp=row['timestamp'],
                    provider=row['provider'],
                    context_tag=row['context_tag'],
                    attachments=json.loads(row['attachments']),
                    metadata=json.loads(row['metadata'])
                ))
            return messages

    def list_conversations(self, limit: int = 50, offset: int = 0) -> list[Conversation]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ? OFFSET ?', (limit, offset))
            rows = cursor.fetchall()
            
            conversations = []
            for row in rows:
                conversations.append(Conversation(
                    id=row['id'],
                    title=row['title'],
                    session_id=row['session_id'],
                    created_at=row['created_at'],
                    updated_at=row['updated_at'],
                    last_provider=row['last_provider'],
                    last_model=row['last_model'],
                    summary=row['summary'],
                    token_count=row['token_count'],
                    metadata=json.loads(row['metadata'])
                ))
            return conversations

    def delete_conversation(self, conv_id: str) -> bool:
        with self._get_conn() as conn:
            # PRAGMA foreign_keys = ON is required for ON DELETE CASCADE to work
            conn.execute('PRAGMA foreign_keys = ON')
            cursor = conn.cursor()
            cursor.execute('DELETE FROM conversations WHERE id = ?', (conv_id,))
            deleted = cursor.rowcount > 0
            conn.commit()
            return deleted

    def keyword_search(self, query: str, limit: int = 20) -> list[Message]:
        with self._get_conn() as conn:
            cursor = conn.cursor()
            search_pattern = f"%{query}%"
            cursor.execute('''
                SELECT * FROM messages 
                WHERE content LIKE ? 
                ORDER BY timestamp DESC 
                LIMIT ?
            ''', (search_pattern, limit))
            rows = cursor.fetchall()
            
            messages = []
            for row in rows:
                messages.append(Message(
                    id=row['id'],
                    conversation_id=row['conversation_id'],
                    parent_message_id=row['parent_message_id'],
                    role=row['role'],
                    content=row['content'],
                    status=row['status'],
                    timestamp=row['timestamp'],
                    provider=row['provider'],
                    context_tag=row['context_tag'],
                    attachments=json.loads(row['attachments']),
                    metadata=json.loads(row['metadata'])
                ))
            return messages
