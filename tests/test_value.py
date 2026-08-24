import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.scoring import value


class TestValueModel(unittest.TestCase):
    def test_better_groupset_estimates_higher(self):
        low = value.estimate({"groupset_tier": 42, "frame_material": "aluminium"})
        high = value.estimate({"groupset_tier": 92, "frame_material": "aluminium"})
        self.assertGreater(high, low)

    def test_carbon_is_worth_more_than_aluminium(self):
        alu = value.estimate({"groupset_tier": 72, "frame_material": "aluminium"})
        carbon = value.estimate({"groupset_tier": 72, "frame_material": "carbon"})
        self.assertGreater(carbon, alu)

    def test_older_bikes_are_worth_less(self):
        new = value.estimate({"groupset_tier": 72, "model_year": 2025})
        old = value.estimate({"groupset_tier": 72, "model_year": 2012})
        self.assertGreater(new, old)

    def test_clear_bargain_earns_points(self):
        attrs = {"groupset_tier": 90, "frame_material": "carbon", "brakes": "hydraulic_disc"}
        points, note = value.bargain(3000, attrs)
        self.assertGreater(points, 0)
        self.assertIn("okazja", note)

    def test_overpriced_for_spec_is_penalised(self):
        points, note = value.bargain(5000, {"groupset_tier": 28, "frame_material": "aluminium"})
        self.assertLess(points, 0)
        self.assertIn("drogo", note)

    def test_fairly_priced_bike_is_neutral(self):
        points, _ = value.bargain(3200, {"groupset_tier": 60, "frame_material": "aluminium"})
        self.assertEqual(points, 0)

    def test_missing_price_is_handled(self):
        self.assertEqual(value.bargain(None, {"groupset_tier": 60}), (0.0, ""))


if __name__ == "__main__":
    unittest.main()


class TestProfileFingerprint(unittest.TestCase):
    """Guards the rule that a changed profile invalidates stored scores."""

    def setUp(self):
        from dealhunter import config
        self.config = config
        self.profile = config.load_profile("gravel", use_local=False)

    def test_same_profile_gives_same_fingerprint(self):
        self.assertEqual(self.config.profile_fingerprint(self.profile),
                         self.config.profile_fingerprint(dict(self.profile)))

    def test_changing_a_weight_changes_the_fingerprint(self):
        changed = {**self.profile, "weights": {**self.profile["weights"], "size": 99}}
        self.assertNotEqual(self.config.profile_fingerprint(self.profile),
                            self.config.profile_fingerprint(changed))

    def test_changing_the_search_query_does_not(self):
        """Search scope is not a scoring rule - rescoring it would be pointless work."""
        changed = {**self.profile, "search": {"olx": {"category_id": 1651}}}
        self.assertEqual(self.config.profile_fingerprint(self.profile),
                         self.config.profile_fingerprint(changed))
