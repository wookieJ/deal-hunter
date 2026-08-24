"""Keyword rules: the shortest path from a YAML line to a score.

These guard the promise that a new kind of product needs no code - including that
a single profile can add its own rules without touching the domain pack.
"""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.models import RawListing
from dealhunter.normalize.base import get_normalizer
from dealhunter.scoring.base import get_scorer

BASE_PROFILE = {
    "domain": "laptops",
    "preferences": {"budget": {"target": 2500, "comfortable_max": 3000,
                               "soft_max": 3600, "hard_max": 4500}},
    "weights": {"condition": 10},
    "bonuses": {},
}


def score(title="Laptop", desc="", price=2000, profile=None):
    raw = RawListing(source="olx", external_id="1", url="u", title=title,
                     description=desc, price=price)
    attrs = get_normalizer("laptops").normalize(raw)
    return get_scorer("laptops").score(attrs, raw, profile or BASE_PROFILE)


class TestDomainKeywordRules(unittest.TestCase):
    def test_positive_keyword_raises_the_score(self):
        plain = score(desc="Laptop biurowy, stan dobry")
        gpu = score(desc="Laptop biurowy z kartą NVIDIA GeForce, stan dobry")
        self.assertGreater(gpu.value, plain.value)
        self.assertTrue(any("dedicated GPU" in r for r in gpu.reasons))

    def test_negative_keyword_lowers_the_score(self):
        plain = score(desc="Laptop, stan dobry")
        hot = score(desc="Laptop, stan dobry, niestety przegrzewa sie przy grach")
        self.assertLess(hot.value, plain.value)

    def test_reject_keyword_disqualifies(self):
        result = score(desc="Laptop zalany, sprzedam tanio")
        self.assertTrue(result.disqualified)
        self.assertIn("liquid damage", result.disqualified_by)

    def test_negated_keyword_does_not_fire(self):
        """"nie zalany" must not be read as liquid damage."""
        self.assertFalse(score(desc="Sprzet sprawny, nie zalany, bez usterek").disqualified)

    def test_several_rules_stack(self):
        one = score(desc="Laptop z NVIDIA GeForce")
        many = score(desc="Laptop z NVIDIA GeForce, i7, dysk NVMe, ekran OLED, gwarancja")
        self.assertGreater(many.value, one.value)


class TestProfileKeywordRules(unittest.TestCase):
    """A one-off search can add rules without touching the domain pack."""

    def _profile(self, rules):
        profile = {k: v for k, v in BASE_PROFILE.items()}
        profile["preferences"] = {**BASE_PROFILE["preferences"], "rules": rules}
        return profile

    def test_profile_rule_adds_points(self):
        profile = self._profile([{"name": "docking", "any": ["stacja dokuj"], "points": 10,
                                  "note": "docking station included"}])
        without = score(desc="Laptop biurowy", profile=profile)
        with_hit = score(desc="Laptop biurowy plus stacja dokujaca", profile=profile)
        self.assertGreater(with_hit.value, without.value)
        self.assertTrue(any("docking station" in r for r in with_hit.reasons))

    def test_profile_rule_can_reject(self):
        profile = self._profile([{"name": "no_charger", "any": ["bez zasilacza"],
                                  "reject": True, "note": "no charger"}])
        self.assertTrue(score(desc="Laptop bez zasilacza", profile=profile).disqualified)

    def test_required_rule_rejects_when_absent(self):
        profile = self._profile([{"name": "must_have_ssd", "any": ["ssd", "nvme"],
                                  "require": True, "note": "SSD required"}])
        self.assertTrue(score(desc="Laptop z dyskiem HDD", profile=profile).disqualified)
        self.assertFalse(score(desc="Laptop z dyskiem SSD", profile=profile).disqualified)

    def test_scope_limits_a_rule_to_the_title(self):
        profile = self._profile([{"name": "titled", "any": ["gamingowy"], "points": 9,
                                  "scope": "title", "note": "gaming in title"}])
        in_title = score(title="Laptop gamingowy", profile=profile)
        in_desc = score(title="Laptop", desc="uzywany do gier, gamingowy", profile=profile)
        self.assertTrue(any("gaming in title" in r for r in in_title.reasons))
        self.assertFalse(any("gaming in title" in r for r in in_desc.reasons))


class TestDomainIsolation(unittest.TestCase):
    def test_domains_keep_their_own_vocabulary(self):
        """Universal concepts like `warranty` may repeat; product specifics may not."""
        from dealhunter import domains
        bikes = set(domains.load("bikes").get("flags") or {})
        laptops = set(domains.load("laptops").get("flags") or {})
        universal = {"warranty"}
        self.assertTrue(bikes and laptops)
        self.assertEqual(bikes & laptops, bikes & laptops & universal)
        self.assertIn("carbon_fork", bikes)
        self.assertNotIn("carbon_fork", laptops)
        self.assertIn("ssd", laptops)
        self.assertNotIn("ssd", bikes)

    def test_engine_source_mentions_no_product_attributes(self):
        """The engine must stay product-agnostic; product words belong in YAML."""
        engine_dir = Path(__file__).resolve().parents[1] / "src" / "dealhunter"
        banned = ("frame_size_cm", "groupset_tier", "cpu_tier", "ram_gb", "frame_material")
        offenders = []
        for path in engine_dir.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            for word in banned:
                # A docstring may mention one as an example; code must not use it.
                for line in text.splitlines():
                    if word in line and not line.strip().startswith("#") and '"""' not in line:
                        offenders.append(f"{path.name}: {line.strip()[:60]}")
        self.assertEqual(offenders, [], "product attributes leaked into the engine")


if __name__ == "__main__":
    unittest.main()
