"""Tests for save_note/recall_note — guaranteed verbatim storage, separate
from the general `facts` system (which the LLM is free to paraphrase from).
"""

import os
import unittest

from jatayu.memory.store import MemoryStore

DB_PATH = "data/test_notes.db"


class TestVerbatimNotes(unittest.TestCase):

    def setUp(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        os.makedirs("data", exist_ok=True)
        self.store = MemoryStore(db_path=DB_PATH, schema_path="jatayu/memory/schema.sql")

    def tearDown(self):
        self.store.close()
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_exact_text_round_trips_unchanged(self):
        text = ("This week I closed 2 new clients and brought in $4,000 in revenue, "
                "published 3 websites with 2 more building. 300K followers, 2.5M views, "
                "gained 3,000+ new followers.")
        self.store.save_note("weekly_update", text)
        self.assertEqual(self.store.recall_note("weekly_update"), text,
                          "recalled text must be byte-for-byte identical to what was saved")

    def test_resaving_same_label_replaces_not_appends(self):
        self.store.save_note("weekly_update", "First version.")
        self.store.save_note("weekly_update", "Second version.")
        result = self.store.recall_note("weekly_update")
        self.assertEqual(result, "Second version.")
        self.assertNotIn("First version", result)

    def test_missing_label_returns_none(self):
        self.assertIsNone(self.store.recall_note("does_not_exist"))

    def test_different_labels_stay_independent(self):
        self.store.save_note("weekly_update", "Weekly content.")
        self.store.save_note("todo_list", "Todo content.")
        self.assertEqual(self.store.recall_note("weekly_update"), "Weekly content.")
        self.assertEqual(self.store.recall_note("todo_list"), "Todo content.")


if __name__ == "__main__":
    unittest.main()
