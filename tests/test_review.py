import json
from pathlib import Path
import tempfile
import unittest

from workflow.live import review
from workflow.paths import render_subtitle


class ConcertFixture:
    def __init__(self, directory):
        self.dir = Path(directory)
        self.review = self.dir / "review.json"
        self.song = self.dir / "song"
        self.song.mkdir()

    def song_dir(self, item):
        return self.song

    def load(self, key):
        if key == "segments":
            return {"items": [{"name": "song", "start": 10, "end": 60}]}
        if key == "review" and self.review.exists():
            return json.loads(self.review.read_text())
        return None


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.concert = ConcertFixture(self.temp.name)
        self.song = self.concert.song
        self.item = {"name": "song"}
        self.write("covers/cover_01.jpg", "cover")

    def write(self, name, content):
        path = self.song / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def approve(self):
        return review.save_entry(self.concert, self.item, {"status": "approved", "cover": "cover_01"})

    def test_current_subtitles_can_be_approved_without_legacy_file(self):
        self.write("subs/lyrics_literal.ass", "literal")
        self.assertFalse((self.song / "lyrics.ass").exists())
        entry = self.approve()
        self.assertEqual(review.effective(self.concert, self.item, entry), "approved")
        self.assertEqual(review.song_status(self.concert, self.item)["stage"], "refined")

    def test_legacy_or_draft_only_cannot_be_approved(self):
        self.write("lyrics.ass", "legacy")
        self.write("subs/lyrics.ass", "draft")
        with self.assertRaisesRegex(ValueError, "成品字幕"):
            self.approve()
        self.assertEqual(review.song_status(self.concert, self.item)["stage"], "located")

    def test_poetic_preferred_and_literal_used_when_poetic_missing(self):
        self.write("subs/lyrics_literal.ass", "literal")
        self.assertEqual(render_subtitle(self.song).name, "lyrics_literal.ass")
        entry = self.approve()
        self.write("subs/lyrics_poetic.ass", "poetic")
        self.assertEqual(render_subtitle(self.song).name, "lyrics_poetic.ass")
        self.assertEqual(review.effective(self.concert, self.item, entry), "stale")
        entry = self.approve()
        (self.song / "subs/lyrics_poetic.ass").unlink()
        self.assertEqual(review.effective(self.concert, self.item, entry), "stale")

    def test_reviewed_assets_changes_require_reapproval(self):
        self.write("subs/lyrics_literal.ass", "literal")
        self.write("subs/lyrics_poetic.ass", "poetic")
        for name in ("subs/lyrics.ass", "subs/lyrics_literal.ass", "subs/lyrics_poetic.ass",
                     "covers/cover_01.jpg", "covers/cover_01_4x3.jpg", "watermark.json", "post_draft.json"):
            with self.subTest(name=name):
                entry = self.approve()
                self.write(name, "updated content")
                self.assertEqual(review.effective(self.concert, self.item, entry), "stale")

    def test_posting_fields_invalidate_but_note_does_not(self):
        self.write("subs/lyrics_literal.ass", "literal")
        for field, value in (("title", "title"), ("intro", "intro"), ("tags", ["tag"]), ("cover", "cover_02")):
            with self.subTest(field=field):
                self.approve()
                entry = review.save_entry(self.concert, self.item, {field: value})
                self.assertEqual(review.effective(self.concert, self.item, entry), "stale")
        self.approve()
        entry = review.save_entry(self.concert, self.item, {"note": "internal note"})
        self.assertEqual(review.effective(self.concert, self.item, entry), "approved")

    def test_old_fingerprint_requires_reapproval(self):
        self.write("subs/lyrics_literal.ass", "literal")
        entry = self.approve()
        entry["fingerprint"] = "legacy fingerprint"
        self.assertEqual(review.effective(self.concert, self.item, entry), "stale")


if __name__ == "__main__":
    unittest.main()
