"""Tests for the Friday-night shutdown ritual — a fully deterministic,
zero-LLM Command Center trigger. Greeting and sign-off are fixed in code
(guaranteed, never drift); only the middle content varies, sourced exactly
from whatever was last saved via save_note(label='weekly_update').
"""

import os
import unittest

from jatayu.memory.store import MemoryStore
import jatayu.memory.store as store_module
from jatayu.pipeline.command_center import CommandCenter, _is_friday_shutdown_briefing

DB_PATH = "data/test_friday_briefing.db"

TRIGGER_PHRASE = ("Jai Shri Ram Jatayu, Its Friday Night, Time to Shut down! "
                   "Before going, brief me the weekly update!")


class TestFridayShutdownBriefing(unittest.TestCase):

    def setUp(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        os.makedirs("data", exist_ok=True)
        self.store = MemoryStore(db_path=DB_PATH, schema_path="jatayu/memory/schema.sql")
        store_module._GLOBAL_STORE = self.store
        self.cc = CommandCenter()

    def tearDown(self):
        self.store.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_falls_through_when_nothing_saved(self):
        result = self.cc.dispatch(text=TRIGGER_PHRASE, session_id="s1")
        self.assertIsNone(result, "should fall through to the Brain if no weekly update is saved yet")

    def test_exact_wording_with_saved_note(self):
        self.store.save_note("weekly_update", "Test content for this week.")
        result = self.cc.dispatch(text=TRIGGER_PHRASE, session_id="s1")
        self.assertIsNotNone(result)
        self.assertEqual(
            result.text,
            "Jai Shri Ram Captain! Test content for this week. Take rest, and see you at 4:00 AM on Monday, Har Har Mahadev Captain!"
        )

    def test_zero_llm_source_tag(self):
        self.store.save_note("weekly_update", "Content.")
        result = self.cc.dispatch(text=TRIGGER_PHRASE, session_id="s1")
        self.assertEqual(result.lane, 0)  # LANE_0 = zero-LLM, instant

    def test_phrasing_variation_still_matches(self):
        self.store.save_note("weekly_update", "Content.")
        variant = "jai shri ram jatayu, friday night, shutting down for the week, give me the weekly brief please"
        result = self.cc.dispatch(text=variant, session_id="s2")
        self.assertIsNotNone(result)

    def test_plain_greeting_does_not_false_trigger(self):
        self.store.save_note("weekly_update", "Content.")
        result = self.cc.dispatch(text="Jai Shri Ram Jatayu", session_id="s3", intent="conversation")
        # Either falls through (None) or is handled by the normal greeting path —
        # must NOT be the briefing content.
        if result is not None:
            self.assertNotIn("Content.", result.text)

    def test_detector_function_directly(self):
        self.assertTrue(_is_friday_shutdown_briefing(TRIGGER_PHRASE.lower()))
        self.assertFalse(_is_friday_shutdown_briefing("jai shri ram jatayu"))
        self.assertFalse(_is_friday_shutdown_briefing("what's the weather on friday"))


if __name__ == "__main__":
    unittest.main()
