"""Extraction rules are the part most likely to silently rot as sellers change
how they write listings, so they get the densest test coverage."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.models import RawListing
from dealhunter.normalize.base import get_normalizer


def listing(title="", desc="", **kw):
    return RawListing(source="olx", external_id="1", url="u", title=title,
                      description=desc, price=kw.pop("price", 4000), **kw)


class TestFrameSize(unittest.TestCase):
    def setUp(self):
        self.n = get_normalizer("bikes")

    def test_cm_variants(self):
        for text, expected in [
            ("Gravel rozmiar ramy 56", 56), ("rama 54 cm", 54), ("Merida Silex 400 rozm. 53", 53),
            ("Rower gravel, 58cm, stan bdb", 58), ("frame size 55", 55),
        ]:
            self.assertEqual(self.n.normalize(listing(title=text))["frame_size_cm"], expected, text)

    def test_wheel_size_is_not_frame_size(self):
        a = self.n.normalize(listing(title="Gravel koła 28 cali, opony 700x38"))
        self.assertIsNone(a["frame_size_cm"])

    def test_letter_sizes(self):
        for text, expected in [("rozmiar L", "L"), ("rozm. M/L", "M/L"), ("size XL", "XL")]:
            self.assertEqual(self.n.normalize(listing(title=text))["frame_size_letter"], expected)

    def test_olx_inch_bucket_is_estimated(self):
        a = self.n.normalize(listing(title="Gravel", params={"framesize": "19-20"}))
        self.assertEqual(a["frame_size_cm"], 54)
        self.assertTrue(a["frame_size_estimated"])


class TestNegationGuard(unittest.TestCase):
    """The bug that hid good offers: sellers advertise the ABSENCE of damage."""

    def setUp(self):
        self.n = get_normalizer("bikes")

    def test_negated_damage_is_not_a_disqualifier(self):
        for text in ["Rama bez pęknięć i wgnieceń", "brak uszkodzeń ramy",
                     "nie ma pęknięć ramy", "żadnych uszkodzeń ramy"]:
            a = self.n.normalize(listing(title="Gravel Merida", desc=text))
            self.assertNotIn("frame_damage", a["disqualifiers"], text)

    def test_real_damage_is_still_caught(self):
        a = self.n.normalize(listing(title="Gravel", desc="Niestety pęknięta rama, na części"))
        self.assertIn("frame_damage", a["disqualifiers"])


class TestSpecs(unittest.TestCase):
    def setUp(self):
        self.n = get_normalizer("bikes")

    def test_groupset_specificity(self):
        cases = [("Shimano GRX 810 1x11", "Shimano GRX 800/820"),
                 ("shimano grx 400", "Shimano GRX 400"),
                 ("napęd Shimano 105", "Shimano 105"),
                 ("SRAM Force AXS", "SRAM Force AXS")]
        for text, expected in cases:
            self.assertEqual(self.n.normalize(listing(title=text))["groupset"], expected, text)

    def test_groupset_tier_ordering(self):
        tier = lambda t: self.n.normalize(listing(title=t))["groupset_tier"]
        self.assertGreater(tier("Shimano GRX 810"), tier("Shimano GRX 400"))
        self.assertGreater(tier("Shimano Tiagra"), tier("Shimano Claris"))

    def test_brakes_and_material(self):
        a = self.n.normalize(listing(title="Gravel karbonowa rama, hamulce tarczowe hydrauliczne"))
        self.assertEqual(a["brakes"], "hydraulic_disc")
        self.assertEqual(a["frame_material"], "carbon")

    def test_carbon_fork_is_not_a_carbon_frame(self):
        """A carbon fork on an aluminium frame is common; conflating the two
        inflated the market-value estimate by 60%."""
        a = self.n.normalize(listing(title="Merida Silex 400 GRX, karbonowy widelec",
                                     desc="rama aluminiowa, widelec carbon"))
        self.assertEqual(a["frame_material"], "aluminium")
        self.assertIn("carbon_fork", a["flags"])

    def test_explicit_carbon_frame_is_recognised(self):
        for text in ["rama karbonowa", "karbonowa rama", "full carbon"]:
            self.assertEqual(self.n.normalize(listing(desc=text))["frame_material"],
                             "carbon", text)

    def test_flatbar_conversion_is_flagged(self):
        a = self.n.normalize(listing(title="Merida Silex 400 flatbar fitness"))
        self.assertIn("flatbar", a["disqualifiers"])

    def test_fitness_in_the_title_disqualifies(self):
        a = self.n.normalize(listing(title="cannondale quick 1 rozm. L fitness/gravel"))
        self.assertIn("fitness_bike", a["disqualifiers"])

    def test_fitness_in_the_description_does_not(self):
        """Sellers describe how they used the bike; that is not a category."""
        a = self.n.normalize(listing(title="Merida Silex 400 gravel rozmiar L",
                                     desc="Uzywany rekreacyjnie, do fitness i dojazdow"))
        self.assertNotIn("fitness_bike", a["disqualifiers"])

    def test_brand_and_year(self):
        a = self.n.normalize(listing(title="Merida Silex 400 2022 rozmiar L"))
        self.assertEqual(a["brand"], "merida")
        self.assertEqual(a["model_year"], 2022)

    def test_ebike_and_parts_are_disqualified(self):
        self.assertIn("ebike", self.n.normalize(listing(title="Rower elektryczny gravel"))["disqualifiers"])
        self.assertIn("parts_only", self.n.normalize(listing(title="Gravel na części"))["disqualifiers"])


if __name__ == "__main__":
    unittest.main()
