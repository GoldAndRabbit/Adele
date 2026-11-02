import unittest
from types import SimpleNamespace

from server.app import display_title, visible_items
from workflow.live.singles import production_day


class SinglesGroupsTests(unittest.TestCase):
    def test_saved_production_day_does_not_depend_on_source_date(self):
        self.assertEqual(production_day({"production_day": "261030", "date": "2000-01-01"}), "261030")

    def test_date_group_filters_items_and_legacy_route_keeps_all(self):
        items = [{"production_day": "261030"}, {"production_day": "261026"}]
        c = SimpleNamespace(items=lambda: items, review_day="261030")
        self.assertEqual(visible_items(c), items[:1])
        del c.review_day
        self.assertEqual(visible_items(c), items)

    def test_version_label_does_not_replace_song_title(self):
        item = {"title": "The Real Slim Shady", "display_title": "Clean版 · The Real Slim Shady"}
        self.assertEqual(display_title(item), "Clean版 · The Real Slim Shady")
        self.assertEqual(item["title"], "The Real Slim Shady")

    def test_duplicate_stays_hidden_in_all_and_dated_lists(self):
        items = [{"production_day": "261030", "review_hidden": True}, {"production_day": "261030"}]
        c = SimpleNamespace(items=lambda: items)
        self.assertEqual(visible_items(c), items[1:])
        c.review_day = "261030"
        self.assertEqual(visible_items(c), items[1:])


if __name__ == "__main__":
    unittest.main()
