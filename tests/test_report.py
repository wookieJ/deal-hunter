"""The report is generated markup, so these guard its structure.

The sorting itself runs in the browser; what can be checked here is that every
card carries the values the sort reads, and that the controls are present. A card
missing `data-km` would silently sort to the bottom forever.
"""
import sys, tempfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dealhunter.report import html


def offer(uid="olx:1", value=80, price=1000.0, km=50):
    row = {"uid": uid, "url": "https://example.test/x", "title": "Example offer",
           "location": "Somewhere", "is_business": False, "value": value,
           "verdict": "Good offer.", "reasons": ["+10 something"], "attrs": {},
           "price": price, "photos": [], "summary_fields": ["a"], "chip_fields": ["b"]}
    if km is not None:
        row.update(drive_km=km, drive_min=km, drive_estimated=False)
    return row


def render(tabs):
    tmp = tempfile.TemporaryDirectory()
    path = html.render_tabs(Path(tmp.name) / "index.html", tabs)
    text = path.read_text(encoding="utf-8")
    tmp.cleanup()
    return text


class TestSortableReport(unittest.TestCase):
    def setUp(self):
        self.text = render([{
            "name": "example", "source": "olx", "last_run": "2026-08-25T10:00:00",
            "stats": {"found": 2, "seen": 1, "new": 1, "changed": 0, "rejected": 0, "offers": 2},
            "top": [offer("olx:1", 90, 1500.0, 40), offer("olx:2", 60, 700.0, 120)],
            "new": [offer("olx:3", 75, 900.0, 10)], "changed": [],
        }])

    def test_every_card_carries_the_sort_values(self):
        self.assertEqual(self.text.count('data-score="'), 3)
        self.assertEqual(self.text.count('data-price="'), 3)
        self.assertEqual(self.text.count('data-km="'), 3)

    def test_all_three_sort_controls_are_offered(self):
        for key in ("score", "price", "km"):
            self.assertIn(f'data-sort="{key}"', self.text)

    def test_sections_are_wrapped_so_sorting_does_not_mix_them(self):
        self.assertEqual(self.text.count('class="card-list"'), 2)   # top + new

    def test_missing_price_or_distance_renders_an_empty_value(self):
        text = render([{
            "name": "example", "source": "olx", "last_run": None,
            "stats": {"found": 1, "seen": 0, "new": 0, "changed": 0, "rejected": 0, "offers": 1},
            "top": [offer("olx:9", 50, None, None)], "new": [], "changed": [],
        }])
        # Empty, not zero: a missing value must sink, not pretend to be free or next door.
        self.assertIn('data-price=""', text)
        self.assertIn('data-km=""', text)

    def test_report_is_self_contained(self):
        self.assertNotIn("<script src=", self.text)
        self.assertNotIn("<link rel=\"stylesheet\"", self.text)


if __name__ == "__main__":
    unittest.main()
