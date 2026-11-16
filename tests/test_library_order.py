import tempfile
import unittest
from pathlib import Path

from server.library_order import date_key, track_dates
from workflow.live.paths import Concert, write_json


class LibraryOrderTests(unittest.TestCase):
    def test_partial_and_genius_dates_sort_chronologically(self):
        self.assertEqual(date_key("June 3, 2013"), "2013-06-03")
        self.assertEqual(date_key(2002), "2002-01-01")
        self.assertEqual(date_key("20261003"), "2026-10-03")
        self.assertIsNone(date_key("unknown"))
        self.assertIsNone(date_key("2026-99-99"))

    def test_release_and_added_dates_are_independent_of_regenerated_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Concert("sample")
            c.songs = Path(tmp)
            item = {"name": "hello", "added_at": "2026-11-14T09:00:00+08:00"}
            folder = c.song_dir(item)
            folder.mkdir()
            write_json(folder / "song.json", {"genius": [{"release_date": "June 3, 2013"}]})
            write_json(folder / "post_draft.json", {"song": {"release_year": 2014}})
            dates = track_dates(c, item)
            self.assertEqual(dates, {"published_at": "2013-06-03", "added_at": item["added_at"]})
            write_json(folder / "post_draft.json", {"song": {"release_year": 2014}, "title": "new title"})
            self.assertEqual(track_dates(c, item), dates)

    def test_missing_directory_and_unknown_release_do_not_break_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = Concert("sample")
            c.songs = Path(tmp)
            dates = track_dates(c, {"name": "missing", "production_day": "261015"})
            self.assertIsNone(dates["published_at"])
            self.assertTrue(dates["added_at"].startswith("2026-10-15"))


if __name__ == "__main__":
    unittest.main()
