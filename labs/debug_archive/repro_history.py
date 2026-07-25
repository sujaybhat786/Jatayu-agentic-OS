import time
from jatayu.brain import Brain

def run_test():
    brain = Brain()
    print("1. Sending first request that will be 'cancelled'")
    session = brain._get_or_create_session("test_session")
    
    # We simulate an in-flight cancellation during tool execution by hacking it
    # We need the model to actually emit a function call.
    # We will ask a tool to run, and the tool will set session.is_cancelled = True
    
    # Actually, if we just set it before send(), what happens?
    session.is_cancelled = True
    
    reply = brain.send("Check my upcoming reminders.", session_id="test_session")
    print(f"Reply 1: {reply}")
    print(f"History len: {len(session.history)}")

    print("\n2. Sending second request (should fail with INVALID_ARGUMENT if poisoned)")
    try:
        reply2 = brain.send("Who is Tejaswini?", session_id="test_session")
        print(f"Reply 2: {reply2}")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    run_test()
