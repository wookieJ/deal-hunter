"""Keyword rules: the shortest path from a YAML line to a score.

These guard the promise that a new kind of product needs no code - including that
a single profile can add its own rules without touching the domain pack.
"""
import re, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.models import RawListing
from dealhunter.normalize.base import get_normalizer
from dealhunter.scoring.base import get_scorer

BASE_PROFILE = {
    "name": "test", "source": "olx", "domain": "laptops",
    "search": {"category_id": 1199},
    "budget": {"target": 2500, "comfortable_max": 3000,
               "soft_max": 3600, "hard_max": 4500},
    "scoring": {"weights": {"condition": 10}, "rules": []},
}


def score(title="Laptop", desc="", price=2000, profile=None):
    from copy import deepcopy
    from dealhunter import config, pipeline
    profile = deepcopy(profile or BASE_PROFILE)
    pipeline.prepare(profile, config.load_settings())
    raw = RawListing(source="olx", external_id="1", url="u", title=title,
                     description=desc, price=price)
    attrs = get_normalizer("laptops").normalize(raw)
    return get_scorer("laptops").score(attrs, raw, profile)


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
        from copy import deepcopy
        profile = deepcopy(BASE_PROFILE)
        profile["scoring"]["rules"] = rules
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

    def test_engine_code_contains_no_product_vocabulary(self):
        """The engine must stay product-agnostic.

        Docstrings may name a bike or a laptop to explain a concept - that is
        prose. Code may not: an identifier or a string literal that knows what a
        groupset is has put product knowledge back into the engine.
        """
        import ast

        # Whole words only: "stack" must not flag "haystack".
        banned = re.compile(
            r"\b(frame_size\w*|groupset\w*|cpu_tier|ram_gb|frame_material|"
            r"geometry|reach|stack|brakes|wheel_size)\b")
        engine_dir = Path(__file__).resolve().parents[1] / "src" / "dealhunter"
        offenders = []

        for path in sorted(engine_dir.rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            docstrings = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                     ast.AsyncFunctionDef)):
                    body = getattr(node, "body", [])
                    if body and isinstance(body[0], ast.Expr) and \
                            isinstance(body[0].value, ast.Constant) and \
                            isinstance(body[0].value.value, str):
                        docstrings.add(id(body[0].value))

            for node in ast.walk(tree):
                text = None
                if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                        and id(node) not in docstrings:
                    text = node.value
                elif isinstance(node, ast.Name):
                    text = node.id
                elif isinstance(node, ast.Attribute):
                    text = node.attr
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    text = node.name
                if not text:
                    continue
                if banned.search(text.lower()):
                    offenders.append(f"{path.name}: {text[:60]!r}")

        self.assertEqual(sorted(set(offenders)), [],
                         "product vocabulary leaked into engine code")


if __name__ == "__main__":
    unittest.main()


class TestNoDomainSearch(unittest.TestCase):
    """A search with no domain pack must still behave sensibly - that is the mode
    a brand new kind of product starts in."""

    PROFILE = {
        "name": "monitor", "source": "olx",
        "search": {"category_id": 1201},
        "budget": {"target": 900, "comfortable_max": 1200,
                   "soft_max": 1600, "hard_max": 2500},
        "scoring": {
            "weights": {"rules": 55, "location": 25, "condition": 20},
            "rules": [
                {"name": "high refresh", "any": [r"\b(144|165|240)\s*hz\b"], "points": 20},
                {"name": "dead pixels", "any": [r"martw\w*\s*piksel\w*"], "points": -18},
                {"name": "broken", "any": [r"nie\s*dzia[lł]a"], "reject": True},
            ]},
    }

    def _score(self, title="Monitor", desc="", price=800):
        from copy import deepcopy
        from dealhunter import config, pipeline
        profile = deepcopy(self.PROFILE)
        pipeline.prepare(profile, config.load_settings())
        raw = RawListing(source="olx", external_id="1", url="u", title=title,
                         description=desc, price=price, lat=52.2297, lon=21.0122)
        attrs = get_normalizer(None).normalize(raw)
        return get_scorer(None).score(attrs, raw, profile)

    def test_scores_without_any_domain_pack(self):
        result = self._score(desc="Monitor 165Hz, stan bardzo dobry")
        self.assertFalse(result.disqualified)
        self.assertGreater(result.value, 0)
        self.assertTrue(any("high refresh" in r for r in result.reasons))

    def test_reject_rule_still_applies(self):
        self.assertTrue(self._score(desc="Monitor nie dziala").disqualified)

    def test_negation_guard_applies_without_a_domain(self):
        """The guard is the engine's, not a pack's. A search with no pack was
        losing it and penalising 'brak martwych pikseli' as an admitted defect."""
        clean = self._score(desc="Ekran sprawny, brak martwych pikseli")
        faulty = self._score(desc="Ekran ma 2 martwe piksele w rogu")
        self.assertFalse(any("dead pixels" in r for r in clean.reasons))
        self.assertTrue(any("dead pixels" in r for r in faulty.reasons))
        self.assertGreater(clean.value, faulty.value)
