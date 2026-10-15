import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import sys

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "workflow"))
import get_ytb_lyrics_from_link as workflow  # noqa: E402


class LyricsWorkflowTests(unittest.TestCase):
    def test_video_metadata_and_title_cleanup(self):
        self.assertEqual(workflow.identify_song({
            "title": "Singer - Song (Official Music Video) [4K]", "channel": "TV Show",
        }), ("Song", "Singer"))
        self.assertEqual(workflow.identify_song({
            "title": "TV performance", "track": "Song (Remix)", "artist": "Singer",
        }), ("Song (Remix)", "Singer"))

    def test_real_concert_video_titles(self):
        self.assertEqual(workflow.identify_song({
            "title": 'Disturbed "The Sound Of Silence" 03/28/16 | CONAN on TBS',
            "channel": "Team Coco",
        }), ("The Sound Of Silence", "Disturbed"))
        self.assertEqual(workflow.identify_song({
            "title": "Eminem - Lose Yourself (Live - 2009) (Explicit Version)",
            "channel": "EminemExplicit",
        }), ("Lose Yourself", "Eminem"))

    def test_lyrics_preserve_inline_links_and_exclude_ui(self):
        html = '''<div>Advertisement</div><div data-lyrics-container="true">
        <div class="LyricsHeader">Song Lyrics</div>[Verse 1]<br>First <a>linked</a> line<br>
        Second line<span data-exclude-from-selection="true">Annotation UI</span></div>
        <div data-lyrics-container="true">[Chorus]<br>Third line</div>'''
        text = workflow.extract_lyrics(html)
        self.assertIn("First linked line\n", text)
        self.assertIn("Second line\n\nThird line", text)
        self.assertNotIn("UI", text)
        self.assertNotIn("Lyrics", text)
        self.assertNotIn("[Verse", text)
        self.assertIn("[Chorus]", workflow.extract_lyrics(html, keep_sections=True))
        with self.assertRaises(ValueError):
            workflow.extract_lyrics("<html>Access denied</html>")

    def test_search_rejects_same_title_from_wrong_artist(self):
        session = Mock()
        session.get.return_value.json.return_value = {"response": {"sections": [
            {"type": "song", "hits": [{"result": {
                "title": "Hello", "primary_artist": {"name": "Lionel Richie"},
                "url": "https://genius.com/example-lyrics", "lyrics_state": "complete",
            }}]},
        ]}}
        with self.assertRaises(ValueError):
            workflow.search_song(session, "Hello", "Adele")

    def test_workflow_writes_utf8_and_preserves_existing_file_on_failure(self):
        session = Mock()
        session.headers = {}
        session.get.return_value.text = '<div data-lyrics-container="true">原创测试<br>第二行</div>'
        session.__enter__ = Mock(return_value=session)
        session.__exit__ = Mock(return_value=False)
        song = {"title": "Test", "primary_artist": {"name": "Singer"},
                "url": "https://genius.com/singer-test-lyrics"}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(workflow, "ROOT", Path(directory)), \
                patch.object(workflow.requests, "Session", return_value=session), \
                patch.object(workflow, "youtube_info", return_value={"track": "Test", "artist": "Singer"}), \
                patch.object(workflow, "search_song", return_value=song), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            args = ["https://youtu.be/test", "--name", "sample"]
            self.assertEqual(workflow.main(args), 0)
            dest = Path(directory) / "posts/sample/lyrics.txt"
            expected = "原创测试\n第二行\n"
            self.assertEqual(dest.read_text(encoding="utf-8"), expected)
            self.assertEqual(workflow.main(args), 1)
            session.get.side_effect = requests.HTTPError("403 Forbidden")
            self.assertEqual(workflow.main(args + ["--overwrite"]), 1)
            self.assertEqual(dest.read_text(encoding="utf-8"), expected)

    def test_output_filename_stays_inside_posts(self):
        dest = workflow.output_path("../../escape")
        self.assertEqual(dest.parent.parent, workflow.ROOT / "posts")
        self.assertEqual(dest.name, "lyrics.txt")
        with self.assertRaises(ValueError):
            workflow.validate_url("https://youtube.com.evil.example/watch?v=123")


if __name__ == "__main__":
    unittest.main()
