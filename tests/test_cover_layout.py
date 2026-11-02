import unittest
from unittest.mock import patch

from PIL import Image
from workflow import make_cover as cover


class CoverLayoutTests(unittest.TestCase):
    def test_optional_artist_and_event_before_language_tag(self):
        self.assertEqual(cover.cover_subtitle("Eminem · 中英字幕", "埃米纳姆", "奥斯卡2020"),
                         "埃米纳姆 Eminem·奥斯卡2020·中英字幕")
        self.assertEqual(cover.cover_subtitle("埃米纳姆 Eminem · 中英字幕", "埃米纳姆"),
                         "埃米纳姆 Eminem·中英字幕")

    def test_natural_layout_never_expands_character_spacing(self):
        for title in ("Stan", "The Real Slim Shady"):
            for size in ((1920, 1080), (1440, 1080)):
                with self.subTest(title=title, size=size):
                    args = cover.build_parser().parse_args([
                        "--name", "test", "--title", title, "--subtitle", "Eminem · 中英字幕",
                        "--artist-zh", "埃米纳姆", "--event", "奥斯卡2020",
                    ])
                    original = args.subtitle
                    with patch.object(cover, "draw_text_tracked") as draw:
                        cover.compose(Image.new("RGB", size), args)
                        cover.compose(Image.new("RGB", size), args)
                    self.assertEqual(args.subtitle, original)
                    self.assertEqual(args.sub_fit, "natural")
                    for call in draw.call_args_list:
                        text, font, tracking = call.args[3:6]
                        self.assertEqual(tracking, 0)
                        self.assertLessEqual(cover.ink_width(text, font), size[0] * 0.90)
                        self.assertEqual(text.count("奥斯卡2020"), 1)


if __name__ == "__main__":
    unittest.main()
