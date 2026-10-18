from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from workflow_v2 import segment, setlist  # noqa: E402


class SetlistTests(unittest.TestCase):
    def test_parse_tape_medley_and_cover(self):
        items = setlist.parse(
            "# 注释\n"
            "[tape] Intro Video | | video interlude\n"
            "La fuerte\n"
            "GIRL LIKE ME | Black Eyed Peas | Black Eyed Peas cover\n"
            "Empire / Inevitable | | medley\n"
            "Pies descalzos, sueños blancos | | genius=https://genius.com/x | \n", "Shakira")
        self.assertEqual([it["kind"] for it in items], ["interlude", "song", "song", "song", "song"])
        self.assertEqual(items[1]["name"], "02_la_fuerte")
        self.assertEqual(items[1]["artist"], "Shakira")
        self.assertEqual(items[2]["artist"], "Black Eyed Peas")
        self.assertEqual(items[3]["parts"], ["Empire", "Inevitable"])
        self.assertEqual(items[4]["parts"], ["Pies descalzos, sueños blancos"])


class SegmentTests(unittest.TestCase):
    def test_caption_words_drop_rollup_repeats(self):
        srt = ("1\n00:00:01,000 --> 00:00:02,000\nES QUE TAMBIÉN\n\n"
               "2\n00:00:02,000 --> 00:00:03,000\nES QUE TAMBIÉN\nTENGO MI ORGULLO\n\n"
               "3\n00:00:03,000 --> 00:00:04,000\nTENGO MI ORGULLO\nY NO\n\n")
        with tempfile.NamedTemporaryFile("w", suffix=".srt", delete=False) as f:
            f.write(srt)
        words = segment.caption_words(f.name)
        self.assertEqual([w for _, w in words], "es que tambien tengo mi orgullo y no".split())
        self.assertEqual(words[3][0], 2.0)

    def test_title_match(self):
        self.assertTrue(segment.title_match("LABICICLETA", {"la bicicleta"}))
        self.assertTrue(segment.title_match("PIES DESCALZOS", {"pies descalzos suenos blancos"}))
        self.assertTrue(segment.title_match("BZRP MUSIC SESSIONS, VOL. 53/66", {"bzrp music sessions 53"}))
        self.assertFalse(segment.title_match("MADRID", {"te dejo madrid"}))

    def test_order_dp_keeps_setlist_order(self):
        # 3 首歌、12 个窗口：0-3 是第 1 首，4-5 讲话，6-8 第 2 首，9-11 第 3 首；第 2 段里混了一个像第 1 首的窗口
        S = np.full((12, 3), 50, np.float32)
        S[0:4, 0] = 95
        S[6:9, 1] = 95
        S[7, 0] = 96
        S[9:12, 2] = 95
        path = segment.order_dp(S)
        self.assertTrue((path[0:4] == 1).all())
        self.assertTrue((path[6:9] == 3).all())
        self.assertTrue((path[9:12] == 5).all())


if __name__ == "__main__":
    unittest.main()
