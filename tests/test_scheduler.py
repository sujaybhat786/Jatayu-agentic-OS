"""Regression test for the task-persistence bug found 2026-07-26:
add_task's data used to silently wipe ALL tasks the moment the stored date
no longer matched today — meaning anything added the night before was gone
by morning. Fixed in scheduler.py's _load(); this test guards against it
coming back.
"""

import json
import os
import unittest

import jatayu.tools.scheduler as scheduler


TEST_SCHEDULE_PATH = "data/test_schedule.json"


class TestSchedulerPersistence(unittest.TestCase):

    def setUp(self):
        if os.path.exists(TEST_SCHEDULE_PATH):
            os.remove(TEST_SCHEDULE_PATH)
        os.makedirs("data", exist_ok=True)
        self._orig_path_fn = scheduler._schedule_path
        scheduler._schedule_path = lambda: __import__("pathlib").Path(TEST_SCHEDULE_PATH)

    def tearDown(self):
        scheduler._schedule_path = self._orig_path_fn
        if os.path.exists(TEST_SCHEDULE_PATH):
            os.remove(TEST_SCHEDULE_PATH)

    def test_tasks_survive_date_rollover(self):
        scheduler.add_task("Plan Monday client call", priority="high")
        scheduler.add_task("Draft Tuesday deliverable", priority="medium")

        # Simulate the stored file being from an earlier date (a real day
        # having passed), the way it would look the morning after.
        with open(TEST_SCHEDULE_PATH) as f:
            data = json.load(f)
        data["date"] = "2020-01-01"
        with open(TEST_SCHEDULE_PATH, "w") as f:
            json.dump(data, f)

        result = scheduler.list_tasks()
        self.assertIn("Plan Monday client call", result,
                      "task was wiped by date rollover — persistence bug regressed")
        self.assertIn("Draft Tuesday deliverable", result,
                      "task was wiped by date rollover — persistence bug regressed")


if __name__ == "__main__":
    unittest.main()
