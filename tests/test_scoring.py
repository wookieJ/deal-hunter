"""These tests encode the owner's stated buying rules. If a change breaks one of
them, the change is wrong unless the rule itself has changed."""
import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter import config, pipeline
from dealhunter.models import RawListing
from dealhunter.normalize.bikes import BikeNormalizer
from dealhunter.scoring.bikes import BikeScorer, haversine_km

SETTINGS = config.load_settings()
PROFILE = config.load_profile("gravel")
pipeline.prepare(PROFILE, SETTINGS)      # resolves the proximity anchor, as a run does
POZNAN = (52.4064, 16.9252)
WARSAW = (52.2297, 21.0122)
# Fixture "home", deliberately arbitrary: real addresses must not live in a
# tracked file. The real one is in the gitignored config/settings.local.yml.
TEST_HOME = {"name": "dom", "lat": 51.7500, "lon": 17.5000}


def score_of(title, desc="", price=3000, lat=POZNAN[0], lon=POZNAN[1], **kw):
    raw = RawListing(source="olx", external_id="1", url="u", title=title,
                     description=desc, price=price, lat=lat, lon=lon, **kw)
    attrs = BikeNormalizer().normalize(raw)
    return BikeScorer().score(attrs, raw, PROFILE)


class TestPriceDominatesSpec(unittest.TestCase):
    """The core rule: a pricier bike must not win on spec alone."""

    def test_expensive_better_spec_loses_to_sensible_cheap(self):
        cheap = score_of("Merida Silex 400 rozmiar L, Shimano 105, hamulce hydrauliczne "
                         "tarczowe, widelec karbonowy", price=3000)
        pricey = score_of("Merida Silex 700 rozmiar L, Shimano GRX 810, hamulce hydrauliczne "
                          "tarczowe, widelec karbonowy, tubeless", price=5000)
        self.assertGreater(cheap.value, pricey.value,
                           f"cheap={cheap.value} pricey={pricey.value}")

    def test_expensive_bike_still_appears_rather_than_being_hidden(self):
        pricey = score_of("Merida Silex 700 rozmiar L, Shimano GRX 810, hydrauliczne, "
                          "widelec karbonowy, osie przelotowe, tubeless", price=5000)
        self.assertFalse(pricey.disqualified)
        self.assertGreater(pricey.value, 45)

    def test_target_price_beats_soft_max_all_else_equal(self):
        same = "Merida Silex 400 rozmiar L Shimano GRX 400 hydrauliczne"
        self.assertGreater(score_of(same, price=3000).value, score_of(same, price=4000).value)

    def test_above_hard_max_is_rejected(self):
        s = score_of("Merida Silex 700 rozmiar L GRX 810", price=6200)
        self.assertTrue(s.disqualified)


class TestGeometrySizing(unittest.TestCase):
    """Sizing must use manufacturer geometry, not the size label alone."""

    def test_geometry_is_used_when_the_model_is_known(self):
        s = score_of("Merida Silex 400 rozmiar L 2019 GRX 400", price=3000)
        self.assertTrue(any("geometria" in r for r in s.reasons))
        self.assertTrue(any("reach 415" in r for r in s.reasons))

    def test_label_only_bike_cannot_reach_full_size_marks(self):
        geo = score_of("Merida Silex 400 rozmiar L 2019 GRX 400", price=3000)
        label = score_of("Kross Esker 4.0 rozmiar L GRX 400", price=3000)
        geo_pts = [r for r in geo.reasons if "geometria" in r][0]
        label_pts = [r for r in label.reasons if "rozmiar L" in r][0]
        self.assertGreater(float(geo_pts.split("/")[0]), float(label_pts.split("/")[0]))

    def test_medium_is_not_rejected_because_sizing_is_brand_dependent(self):
        s = score_of("Merida Silex 400 rozmiar M 2023 GRX 400", price=3000)
        self.assertFalse(s.disqualified)
        self.assertGreater(s.value, 55)

    def test_obviously_wrong_sizes_are_rejected(self):
        for title in ["Gravel rozmiar S GRX 400", "Gravel rozmiar XS GRX",
                      "Gravel rozmiar 44 cm GRX"]:
            self.assertTrue(score_of(title, price=3000).disqualified, title)

    def test_unknown_year_lowers_geometry_confidence(self):
        dated = score_of("Merida Silex 400 rozmiar L 2019 GRX 400", price=3000)
        undated = score_of("Merida Silex 400 rozmiar L GRX 400", price=3000)
        self.assertTrue(any("rocznik nieznany" in r for r in undated.reasons))
        self.assertNotEqual(dated.value, undated.value)


class TestLocation(unittest.TestCase):
    def test_local_offer_outranks_a_distant_identical_one(self):
        title = "Merida Silex 400 rozmiar L 2019 GRX 400 hydrauliczne"
        near = score_of(title, price=3000, lat=POZNAN[0], lon=POZNAN[1])
        far = score_of(title, price=3000, lat=49.62, lon=22.68)   # Bieszczady
        self.assertGreater(near.value, far.value)

    def test_distant_offer_is_never_rejected(self):
        s = score_of("Merida Silex 400 rozmiar L 2019 GRX 400", price=3000,
                     lat=49.62, lon=22.68)
        self.assertFalse(s.disqualified)

    def test_haversine_sanity(self):
        km = haversine_km(*POZNAN, *WARSAW)
        self.assertTrue(270 < km < 290, km)


class TestSearchAreaVersusHome(unittest.TestCase):
    """The search area (where to hunt) and home (where you live) are different
    things - you can hunt in another city."""

    def _profile(self, proximity_to, area, home):
        profile = config.load_profile("gravel")
        profile["search"]["olx"]["area"] = area
        profile["preferences"]["location"]["proximity_to"] = proximity_to
        pipeline.prepare(profile, {"home": home})
        return profile

    def test_anchor_follows_the_search_area_by_default(self):
        profile = self._profile("search_area",
                                {"name": "Krakow", "lat": 50.0647, "lon": 19.9450,
                                 "radius_km": 50},
                                TEST_HOME)
        anchor = profile["preferences"]["location"]["anchor"]
        self.assertEqual(anchor["name"], "Krakow")
        self.assertEqual(anchor["radius_km"], 50)

    def test_anchor_can_be_pinned_to_home_instead(self):
        profile = self._profile("home",
                                {"name": "Krakow", "lat": 50.0647, "lon": 19.9450},
                                TEST_HOME)
        self.assertEqual(profile["preferences"]["location"]["anchor"]["name"], "dom")

    def test_hunting_elsewhere_rewards_offers_there_not_near_home(self):
        """Searching around Krakow must favour Krakow offers even though home is
        400 km away - otherwise the search area would be meaningless."""
        profile = self._profile("search_area",
                                {"name": "Krakow", "lat": 50.0647, "lon": 19.9450,
                                 "radius_km": 50},
                                TEST_HOME)
        scorer, norm = BikeScorer(), BikeNormalizer()

        def at(lat, lon):
            raw = RawListing(source="olx", external_id="1", url="u",
                             title="Merida Silex 400 rozmiar L 2019 GRX 400",
                             description="", price=3000, lat=lat, lon=lon)
            return scorer.score(norm.normalize(raw), raw, profile).value

        self.assertGreater(at(50.0647, 19.9450), at(TEST_HOME["lat"], TEST_HOME["lon"]))

    def test_missing_area_and_home_is_handled(self):
        profile = config.load_profile("gravel")
        profile["search"]["olx"].pop("area", None)
        pipeline.prepare(profile, {})
        self.assertEqual(profile["preferences"]["location"]["anchor"], {})


class TestSellerAndFeatures(unittest.TestCase):
    def test_shop_offers_are_not_penalised(self):
        title = "Merida Silex 400 rozmiar L 2019 GRX 400 hydrauliczne"
        private = score_of(title, price=3000, is_business=False)
        shop = score_of(title, price=3000, is_business=True)
        self.assertEqual(private.value, shop.value)

    def test_hydraulic_brakes_and_carbon_fork_raise_the_score(self):
        plain = score_of("Kross Esker rozmiar L GRX 400", price=3000)
        loaded = score_of("Kross Esker rozmiar L GRX 400 hamulce tarczowe hydrauliczne "
                          "widelec karbonowy osie przelotowe tubeless", price=3000)
        self.assertGreater(loaded.value, plain.value)

    def test_rim_brakes_are_worse_than_unknown_brakes(self):
        rim = score_of("Kross Esker rozmiar L GRX 400 hamulce szczękowe", price=3000)
        unknown = score_of("Kross Esker rozmiar L GRX 400", price=3000)
        self.assertLess(rim.value, unknown.value)


class TestExplainability(unittest.TestCase):
    def test_every_score_carries_reasons_and_a_verdict(self):
        s = score_of("Merida Silex 400 rozmiar L 2019 GRX 400", price=3000)
        self.assertTrue(s.reasons)
        self.assertTrue(s.verdict)
        self.assertTrue(0 <= s.value <= 100)

    def test_budget_multiplier_is_shown(self):
        s = score_of("Merida Silex 400 rozmiar L 2019 GRX 400", price=5000)
        self.assertTrue(any(r.startswith("x0.") for r in s.reasons))


if __name__ == "__main__":
    unittest.main()
