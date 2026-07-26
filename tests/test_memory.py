"""
Layer 1 memory tests — run: python3 -m unittest tests/test_memory.py

Covers:
  - Alias resolution (exact + fuzzy) for people & projects
  - Entity structured fields (emails, phones, contract terms)
  - Reseed idempotency (no duplicate rows)
  - Protected facts always present in retrieve_for_prompt()
  - No corrupted TestUser identity data
  - Scale performance (retrieval over 1000+ facts < 20ms)
"""

import os
import random
import time
import unittest

from jatayu.memory.store import MemoryStore
from jatayu.memory import seed as seed_data

DB_PATH = "data/test_memory.db"


def fresh_store() -> MemoryStore:
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    os.makedirs("data", exist_ok=True)
    schema_path = os.path.join(os.path.dirname(__file__), "..", "jatayu", "memory", "schema.sql")
    return MemoryStore(db_path=DB_PATH, schema_path=schema_path)


class TestMemoryStore(unittest.TestCase):

    def test_alias_resolution(self):
        store = fresh_store()
        seed_data.seed_people(store)
        seed_data.seed_projects(store)

        for alias, expected_name in [
            ("Tejaswini", "Tejaswini Hegde"),
            ("Bekku", "Tejaswini Hegde"),
            ("Bekkumari", "Tejaswini Hegde"),
            ("Subbi", "Sumedha Bhat"),
            ("Sumedha", "Sumedha Bhat"),
            ("Ram Raghavan", "Ram Raghavan"),
            ("Guenther", "Guenther"),
        ]:
            person = store.get_person(alias)
            self.assertIsNotNone(person, f"get_person('{alias}') returned None")
            self.assertEqual(person["name"], expected_name, f"'{alias}' resolved to {person['name']}, expected {expected_name}")

        # fuzzy tier: slight misspelling should still resolve
        fuzzy = store.get_person("Tejaswni")  # missing an 'i'
        self.assertIsNotNone(fuzzy)
        self.assertEqual(fuzzy["name"], "Tejaswini Hegde")

        proj = store.get_project("Fifth Veda")
        self.assertIsNotNone(proj)
        self.assertEqual(proj["name"], "The 5th Veda")

        store.close()

    def test_entity_fields_correct(self):
        store = fresh_store()
        seed_data.seed_people(store)
        seed_data.seed_projects(store)

        tejaswini = store.get_person("Tejaswini")
        self.assertEqual(tejaswini["fields"]["email"], "hegdetejaswini29@gmail.com")
        self.assertEqual(tejaswini["fields"]["phone"], "+91 7349129851")

        sumedha = store.get_person("Sumedha")
        self.assertEqual(sumedha["fields"]["email"], "bhatsumedha21@gmail.com")
        self.assertEqual(sumedha["fields"]["phone"], "9353750749")
        self.assertIn("sister", sumedha["fields"]["relation"].lower())

        framelux = store.get_project("Framelux")
        self.assertEqual(framelux["fields"]["contract"]["amount"], 1340)
        self.assertEqual(framelux["fields"]["contract"]["currency"], "USD")

        veda = store.get_project("The 5th Veda")
        self.assertEqual(veda["fields"]["contract"]["amount"], 250)
        self.assertEqual(veda["fields"]["contract"]["currency"], "GBP")

        store.close()

    def test_dedup_on_reseed(self):
        store = fresh_store()
        seed_data.seed_people(store)
        seed_data.seed_people(store)  # run twice on purpose
        seed_data.seed_projects(store)
        seed_data.seed_projects(store)

        people = store.list_entities("person")
        projects = store.list_entities("project")
        self.assertEqual(len(people), 6, f"expected 6 people, got {len(people)} (dedup failed)")
        self.assertEqual(len(projects), 8, f"expected 8 projects, got {len(projects)} (dedup failed)")

        store.close()

    def test_protected_facts_always_present(self):
        store = fresh_store()
        seed_data.seed_facts(store)

        block = store.retrieve_for_prompt("what time is the standup call today")
        self.assertIn("Sujay Bhat", block)
        self.assertIn("espresso", block.lower())

        store.close()

    def test_no_bad_identity_data(self):
        store = fresh_store()
        seed_data.seed_facts(store)
        identity_facts = store.list_memories(category="identity")
        for f in identity_facts:
            self.assertNotIn("TestUser", f["fact"])

    def test_partial_update_does_not_clobber_existing_fields(self):
        """Regression test for a real production bug: updating a person with
        only SOME fields specified (e.g. adding a project note) must not wipe
        out fields set in an earlier call (e.g. email) just because the second
        call's tool wrapper defaults unspecified fields to '' instead of None."""
        from jatayu.memory.store import _tool_remember_entity

        store = fresh_store()
        import jatayu.memory.store as store_module
        store_module._GLOBAL_STORE = store  # point the module-level singleton at our test db

        _tool_remember_entity(type="person", name="Priya Nair", email="priya@example.com",
                               profession="Video Editor")
        person = store.get_person("Priya Nair")
        self.assertEqual(person["fields"]["email"], "priya@example.com")

        # Simulate a later, unrelated update that only mentions a new fact —
        # NOT re-stating the email — the way the model does in practice.
        _tool_remember_entity(type="person", name="Priya Nair",
                               notes="Hired as Video Editor for The 5th Veda.")

        person = store.get_person("Priya Nair")
        self.assertEqual(person["fields"]["email"], "priya@example.com",
                          "email was wiped by an update that didn't mention it — clobbering bug regressed")
        self.assertEqual(person["fields"]["profession"], "Video Editor",
                          "profession was wiped by an update that didn't mention it — clobbering bug regressed")

        store.close()

    def test_performance_at_scale(self):
        store = fresh_store()
        seed_data.seed_facts(store)
        seed_data.seed_people(store)
        seed_data.seed_projects(store)

        random.seed(42)
        N = 1000
        words = ["invoice", "deadline", "client", "video", "render", "script", "call", "note",
                 "draft", "meeting", "budget", "asset", "review", "feedback", "upload"]

        t0 = time.perf_counter()
        for i in range(N):
            body = " ".join(random.choice(words) for _ in range(8))
            store.remember(f"Synthetic fact #{i}: {body}.", category="knowledge", importance=random.random())
        insert_elapsed = time.perf_counter() - t0

        queries = [
            "who is Tejaswini",
            "what is the Framelux contract worth",
            "tell me about the 5th Veda deal",
            "video render deadline client",
            "what does Sujay like to drink",
        ]
        latencies = []
        for q in queries:
            t0 = time.perf_counter()
            store.retrieve_for_prompt(q, top_k=5)
            latencies.append((time.perf_counter() - t0) * 1000)

        avg = sum(latencies) / len(latencies)
        worst = max(latencies)

        self.assertLess(worst, 20.0, f"retrieval too slow at scale: {worst:.2f}ms (target <20ms)")

        t0 = time.perf_counter()
        for _ in range(50):
            store.get_person("Bekku")
            store.get_project("Framelux")
        lookup_avg = (time.perf_counter() - t0) * 1000 / 100

        self.assertLess(lookup_avg, 100.0, f"lookup too slow: {lookup_avg:.3f}ms (target <100ms)")

        store.close()


if __name__ == "__main__":
    unittest.main()
