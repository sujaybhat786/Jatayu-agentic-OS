import os
import sys
from pathlib import Path

# Add project root to sys.path
sys.path.insert(0, str(Path(__file__).parent))

from jatayu.conversation.service import ConversationService
from jatayu.core.events import EventBus

def test_conversation_service():
    db_path = "/tmp/test_jatayu.db"
    if os.path.exists(db_path):
        os.remove(db_path)

    events = EventBus()
    svc = ConversationService(db_path, events)

    # 1. Create conversation
    cid = svc.create_conversation(provider="test")
    print(f"Created conversation: {cid}")

    # 2. Add messages
    m1 = svc.append_message(cid, "user", "Hello!")
    m2 = svc.append_message(cid, "assistant", "Hi there!")
    print(f"Added messages: {m1}, {m2}")

    # 3. Get recent
    msgs = svc.get_recent_messages(cid)
    assert len(msgs) == 2, f"Expected 2 messages, got {len(msgs)}"
    assert msgs[0].content == "Hello!"
    assert msgs[1].content == "Hi there!"

    # 4. List conversations
    convos = svc.list_conversations()
    assert len(convos) == 1, f"Expected 1 conversation, got {len(convos)}"
    assert convos[0].id == cid

    # 5. Search
    results = svc.keyword_search("there")
    assert len(results) == 1
    assert results[0].content == "Hi there!"

    print("✅ All assertions passed")

if __name__ == "__main__":
    test_conversation_service()
