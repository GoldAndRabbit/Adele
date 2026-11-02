import contextlib
import io
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from workflow.live import package


class PackageParallelTests(unittest.TestCase):
    def test_covers_start_while_metadata_is_still_running(self):
        covers_started = threading.Event()
        metadata_done = threading.Event()
        concert = SimpleNamespace(song_dir=lambda item: Mock())
        item = {"idx": 1, "title": "Song"}

        def metadata(*args):
            if not covers_started.wait(2):
                raise AssertionError("封面等待介绍结束，没有并行")
            metadata_done.set()

        def covers(*args):
            self.assertFalse(metadata_done.is_set())
            covers_started.set()

        with patch.object(package, "selected", return_value=[(item, {})]), \
                patch.object(package, "draft_meta", side_effect=metadata) as draft, \
                patch.object(package, "make_covers", side_effect=covers) as cover, \
                patch.object(package, "cover_candidates", return_value=[{}]), \
                patch.dict("sys.modules", {"workflow.live.cover_rank": SimpleNamespace(rank=Mock())}), \
                contextlib.redirect_stdout(io.StringIO()):
            package.stage_package(concert, SimpleNamespace(force=False))
        self.assertTrue(metadata_done.is_set())
        draft.assert_called_once()
        cover.assert_called_once()

    def test_metadata_failure_does_not_stop_other_songs(self):
        items = [({"idx": n, "title": str(n)}, {}) for n in (1, 2)]
        concert = SimpleNamespace(song_dir=lambda item: Mock())
        with patch.object(package, "selected", return_value=items), \
                patch.object(package, "draft_meta", side_effect=[RuntimeError("API error"), None]), \
                patch.object(package, "make_covers") as cover, \
                patch.object(package, "cover_candidates", return_value=[{}]), \
                patch.dict("sys.modules", {"workflow.live.cover_rank": SimpleNamespace(rank=Mock())}), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            package.stage_package(concert, SimpleNamespace(force=False))
        self.assertEqual(cover.call_count, 2)
        self.assertIn("1/2", output.getvalue())


if __name__ == "__main__":
    unittest.main()
