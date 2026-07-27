"""Regression test for the 2026-07-26 fix to Gemini 503/transient-error
handling: previously only 1 retry with a fixed 0.5s wait, and a raw
exception string shown to the user on failure. Now: real exponential
backoff with more attempts, and a clean user-facing message on exhaustion.
"""

import os
import unittest
from unittest.mock import patch

os.environ.setdefault("GEMINI_API_KEY", "dummy-key-for-offline-testing-only")

from jatayu.brain import Brain


class FakeTransientError(Exception):
    pass


class TestTransientErrorRetry(unittest.TestCase):

    def _make_brain_with_failing_stream(self, error_message="503 UNAVAILABLE. The model is overloaded."):
        brain = Brain()
        call_count = {"n": 0}

        def fake_stream(*args, **kwargs):
            call_count["n"] += 1
            raise FakeTransientError(error_message)

        brain.client.models.generate_content_stream = fake_stream
        return brain, call_count

    def test_retries_multiple_times_with_backoff_then_gives_clean_message(self):
        brain, call_count = self._make_brain_with_failing_stream()
        sleep_calls = []

        with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            result = brain.send(
                user_input="hello",
                on_chunk=lambda t: None,
                on_status=lambda t: None,
                tools_to_expose=[],
                session_id="test-503-retry",
                memory_block="",  # skip real memory DB entirely for this test
            )

        # Should have tried 4 times total (1 initial + 3 retries) in normal (non-demo) mode.
        self.assertEqual(call_count["n"], 4,
                          f"expected 4 attempts, got {call_count['n']} — retry count regressed")

        # Should have slept 3 times (between the 4 attempts) with real, increasing backoff —
        # not the old fixed 0.5s every time.
        self.assertEqual(len(sleep_calls), 3, "expected 3 backoff sleeps between 4 attempts")
        self.assertEqual(sleep_calls, [1.0, 2.0, 4.0],
                          f"expected exponential backoff [1.0, 2.0, 4.0], got {sleep_calls}")

        # The user-facing message must be the clean, honest one — not a raw
        # exception dump like the old 'Couldn't reach the model: 503 UNAVAILABLE...'
        self.assertIn("temporarily overloaded", result.lower())
        self.assertNotIn("unavailable", result.lower(),
                         "raw exception text leaked into the user-facing message")

    def test_non_transient_error_still_shows_detail(self):
        """A genuine (non-transient) bug should NOT be masked by the friendly
        message — it should still surface real detail for debugging."""
        brain, call_count = self._make_brain_with_failing_stream(
            error_message="ValueError: something is actually broken in our own code"
        )

        with patch("time.sleep"):
            result = brain.send(
                user_input="hello",
                on_chunk=lambda t: None,
                on_status=lambda t: None,
                tools_to_expose=[],
                session_id="test-non-transient",
                memory_block="",
            )

        # Non-transient errors should NOT retry repeatedly — fails fast.
        self.assertEqual(call_count["n"], 1,
                          "non-transient error should not be retried")
        self.assertIn("something is actually broken", result)


if __name__ == "__main__":
    unittest.main()
