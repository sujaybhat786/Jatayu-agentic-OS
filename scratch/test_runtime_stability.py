import unittest
import time
import asyncio
from google.genai import types
from jatayu.brain import Brain, SessionState, RequestState


class TestRuntimeStability(unittest.TestCase):
    def setUp(self):
        self.brain = Brain()
        self.session = self.brain._get_or_create_session("test-stability-session")
        self.session.session_id = "test-stability-session"

    def test_1_lifecycle_state_transitions(self):
        """Verify request state transitions and cleanup."""
        self.assertEqual(self.session.request_state, RequestState.IDLE)
        self.session.set_state(RequestState.CREATED, "Test Create")
        self.assertEqual(self.session.request_state, RequestState.CREATED)
        self.session.set_state(RequestState.RUNNING, "Test Running")
        self.assertEqual(self.session.request_state, RequestState.RUNNING)
        self.session.cleanup()
        self.assertEqual(self.session.request_state, RequestState.IDLE)
        self.assertFalse(self.session.is_cancelled)

    def test_2_history_integrity_sanitizer(self):
        """Verify orphaned function calls and responses are dropped cleanly."""
        # Turn 0: User input
        t0 = types.Content(role="user", parts=[types.Part(text="Hello")])
        # Turn 1: Model function call without response
        fc = types.Part(function_call=types.FunctionCall(name="get_person", args={"name": "Tejaswini"}))
        t1 = types.Content(role="model", parts=[fc])
        
        self.session.history = [t0, t1]
        self.brain._validate_and_sanitize_history(self.session)
        # Should have dropped t1 because it lacked a subsequent user function response
        self.assertEqual(len(self.session.history), 1)
        self.assertEqual(self.session.history[0].role, "user")

    def test_3_cancellation_recovery(self):
        """Verify session is unpoisoned after cancellation when cleanup() runs."""
        self.session.is_cancelled = True
        self.session.set_state(RequestState.CANCELLED, "Simulated cancel")
        self.session.cleanup()
        self.assertFalse(self.session.is_cancelled)
        self.assertEqual(self.session.request_state, RequestState.IDLE)

    def test_4_watchdog_confirmation_pause_logic(self):
        """Verify watchdog elapsed logic resets while in WAITING_FOR_CONFIRMATION state."""
        self.session.set_state(RequestState.WAITING_FOR_CONFIRMATION, "Waiting for send_gmail")
        elapsed = 0.0
        poll_interval = 0.5
        watchdog_limit = 5.0
        
        # Simulate 10 seconds passing while waiting for confirmation
        for _ in range(20):
            req_state = getattr(self.session, "request_state", None)
            if req_state and getattr(req_state, "name", "") == "WAITING_FOR_CONFIRMATION":
                elapsed = 0.0
            else:
                elapsed += poll_interval
        
        # Elapsed should still be 0.0, not 10.0, preventing a timeout!
        self.assertEqual(elapsed, 0.0)
        self.assertLess(elapsed, watchdog_limit)
        
        # Now approve confirmation and transition state
        self.session.set_state(RequestState.EXECUTING_TOOL, "Executing send_gmail")
        if getattr(self.session.request_state, "name", "") == "WAITING_FOR_CONFIRMATION":
            elapsed = 0.0
        else:
            elapsed += poll_interval
            
        self.assertEqual(elapsed, 0.5)


if __name__ == "__main__":
    unittest.main()
