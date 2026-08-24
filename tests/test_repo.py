"""Deduplication and change detection - the behaviour the whole tool rests on."""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.models import RawListing, ScoreResult
from dealhunter.storage.db import connect
from dealhunter.storage.repo import Repo


def offer(price=4000, title="Merida Silex 400", desc="gravel"):
    return RawListing(source="olx", external_id="123", url="u", title=title,
                      description=desc, price=price)


class TestRepo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(connect(Path(self.tmp.name) / "t.sqlite3"))
        self.run_id = self.repo.start_run("gravel", "olx")

    def tearDown(self):
        self.tmp.cleanup()

    def test_first_sighting_is_new(self):
        status, _ = self.repo.upsert(offer(), self.run_id)
        self.assertEqual(status, "new")

    def test_identical_rerun_is_seen_not_new(self):
        self.repo.upsert(offer(), self.run_id)
        status, changes = self.repo.upsert(offer(), self.run_id)
        self.assertEqual(status, "seen")
        self.assertEqual(changes, [])

    def test_price_change_is_detected_and_described(self):
        self.repo.upsert(offer(price=4500), self.run_id)
        status, changes = self.repo.upsert(offer(price=4200), self.run_id)
        self.assertEqual(status, "changed")
        self.assertIn("drop", changes[0])
        self.assertIn("4200", changes[0])

    def test_price_history_accumulates(self):
        for price in (5000, 4700, 4400):
            self.repo.upsert(offer(price=price), self.run_id)
        history = self.repo.price_history("olx:123")
        self.assertEqual([h["price"] for h in history], [5000, 4700, 4400])

    def test_description_change_is_detected(self):
        self.repo.upsert(offer(), self.run_id)
        status, changes = self.repo.upsert(offer(desc="gravel, nowe opony"), self.run_id)
        self.assertEqual(status, "changed")
        self.assertIn("description", changes[0])

    def test_scores_from_another_profile_version_are_stale(self):
        """A profile change must invalidate stored scores, or the ranking silently
        mixes numbers produced by different scoring rules."""
        self.repo.upsert(offer(), self.run_id)
        self.repo.save_score("olx:123", "gravel", ScoreResult(90, "ok"), "hash-v1")
        self.repo.commit()
        self.assertEqual(self.repo.stale("gravel", "hash-v1"), [])
        stale = self.repo.stale("gravel", "hash-v2")
        self.assertEqual([s["uid"] for s in stale], ["olx:123"])

    def test_scores_without_a_fingerprint_count_as_stale(self):
        self.repo.upsert(offer(), self.run_id)
        self.repo.save_score("olx:123", "gravel", ScoreResult(90, "ok"))
        self.repo.commit()
        self.assertEqual(len(self.repo.stale("gravel", "hash-v1")), 1)

    def test_first_run_flag(self):
        self.assertTrue(self.repo.is_first_run("gravel"))
        self.repo.finish_run(self.run_id, 1, 1, 0, 0)
        self.assertFalse(self.repo.is_first_run("gravel"))


if __name__ == "__main__":
    unittest.main()


class TestClear(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(connect(Path(self.tmp.name) / "t.sqlite3"))
        run_id = self.repo.start_run("gravel", "olx")
        self.repo.upsert(offer(), run_id)
        self.repo.save_score("olx:123", "gravel", ScoreResult(90, "ok"), "h")
        self.repo.conn.execute(
            "INSERT INTO travel_cache(key, km, minutes, fetched_at) VALUES ('a',1,2,'now')")
        self.repo.commit()

    def tearDown(self):
        self.tmp.cleanup()

    def _count(self, table):
        return self.repo.conn.execute(f"SELECT COUNT(*) c FROM {table}").fetchone()["c"]

    def test_clear_removes_offers_but_keeps_travel_cache(self):
        self.repo.clear()
        for table in ("listing", "listing_version", "score", "run"):
            self.assertEqual(self._count(table), 0, table)
        self.assertEqual(self._count("travel_cache"), 1)

    def test_clear_all_removes_travel_cache_too(self):
        self.repo.clear(keep_travel_cache=False)
        self.assertEqual(self._count("travel_cache"), 0)

    def test_database_is_usable_after_clearing(self):
        self.repo.clear()
        run_id = self.repo.start_run("gravel", "olx")
        self.assertEqual(self.repo.upsert(offer(), run_id)[0], "new")
