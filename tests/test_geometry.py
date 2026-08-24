import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.normalize.lookup import resolve as _resolve


def resolve(brand, title, variant, year):
    """The bikes domain's geometry table, via the generic lookup."""
    found = _resolve('geometry', 'bikes', brand, title, variant, year)
    if not found:
        return {'geo_reach': None, 'geo_stack': None, 'geo_confidence': '', 'geo_note': ''}
    return {'geo_reach': found['values'].get('reach'),
            'geo_stack': found['values'].get('stack'),
            'geo_confidence': found['confidence'], 'geo_note': found['note']}


class TestGeometryLookup(unittest.TestCase):
    def test_generation_is_selected_by_model_year(self):
        old = resolve("merida", "Merida Silex 400 rozmiar L", "L", 2019)
        new = resolve("merida", "Merida Silex 400 rozmiar L", "L", 2023)
        self.assertEqual((old["geo_reach"], old["geo_stack"]), (415, 644))
        self.assertEqual((new["geo_reach"], new["geo_stack"]), (426, 626))

    def test_same_label_different_geometry_across_generations(self):
        """The whole reason size labels cannot be trusted."""
        old = resolve("merida", "Merida Silex", "M", 2019)
        new = resolve("merida", "Merida Silex", "M", 2023)
        self.assertNotEqual(old["geo_stack"], new["geo_stack"])

    def test_missing_year_is_flagged_as_ambiguous(self):
        r = resolve("merida", "Merida Silex 300", "L", None)
        self.assertEqual(r["geo_confidence"], "ambiguous")

    def test_unknown_brand_returns_empty(self):
        self.assertIsNone(resolve("cube", "Cube Nuroad", "L", 2022)["geo_reach"])

    def test_unknown_size_returns_empty(self):
        self.assertIsNone(resolve("merida", "Merida Silex", "XXL", 2023)["geo_reach"])


if __name__ == "__main__":
    unittest.main()
