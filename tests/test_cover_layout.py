import unittest
from unittest.mock import patch

from PIL import Image
from workflow import make_cover as cover


class CoverLayoutTests(unittest.TestCase):
    def test_pink_heart_is_colored_and_measured_in_the_cover_title(self):
        face = cover.font("sans", 96)
        title = "u + me = 🩷"
        canvas = Image.new("RGBA", (850, 180))
        cover.draw_text(canvas, (425, 140), title, face)
        def pink_pixels(region):
            return sum(r > 180 and g < 130 and b > 90 and a > 200 for r, g, b, a in region.getdata())

        self.assertGreater(pink_pixels(canvas.crop((425, 0, 850, 180))), 400)
        self.assertEqual(pink_pixels(canvas.crop((0, 0, 425, 180))), 0)
        self.assertAlmostEqual(cover.ink_width(title, face), sum(w for _,w in cover.symbol_runs(title, face)))

    def test_reviewed_solo_lead_can_represent_duet(self):
        import hashlib
        from workflow.fibo_concert import check_group_reference
        item = {"name": "drunk_in_love", "artist": "Beyoncé & Jay-Z"}
        frame = b"selected image"
        spec = {"group_performance": True, "solo_review": {
            "performer": "Beyoncé", "front_clear": True, "reason": "Unobstructed front view",
            "reference_sha256": hashlib.sha256(frame).hexdigest()}}
        check_group_reference(item, spec, frame)
        with self.assertRaises(ValueError):
            check_group_reference(item, spec, b"another image")
        spec["solo_review"]["front_clear"] = False
        with self.assertRaises(ValueError):
            check_group_reference(item, spec, frame)

    def test_closed_eyes_are_excluded_even_when_all_candidates_are_closed(self):
        pool = {"close": [{"t": 1.0, "box": None, "sharp": 1, "place": 1, "vlm": {"eyes": "closed"}}]}
        self.assertEqual(cover.select_final(pool, {"close": 5}), {"close": []})

    def test_blink_review_is_tied_to_exact_image_and_role(self):
        import hashlib
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from workflow.cover_eye_review import check_for_blink

        with TemporaryDirectory() as tmp, patch("workflow.cover_eye_review.inspect_eyes",
                                                return_value=[{"check_closed": True}]):
            image = Path(tmp) / "reference.jpg"
            image.write_bytes(b"original")
            spec = {"eye_review": {"reference": {"reason": "Opaque sunglasses",
                                                 "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}}}
            check_for_blink(image, spec, "reference")
            with self.assertRaises(ValueError):
                check_for_blink(image, spec, "master")
            image.write_bytes(b"new frame")
            with self.assertRaises(ValueError):
                check_for_blink(image, spec, "reference")

    def test_badge_stays_top_left_even_when_a_face_overlaps(self):
        args = cover.build_parser().parse_args(["--name", "test", "--title", "Royals",
                                                "--subtitle", "Lorde"])
        args.compact_credits = True
        args.brand_scale = .54
        for size in [(1920, 1080), (1440, 1080), (1080, 1440)]:
            with patch.object(cover, "layout_faces", return_value=[(50, 50, 140, 140)]), \
                    patch.object(cover, "paste_with_shadow", wraps=cover.paste_with_shadow) as paste:
                cover.compose(Image.new("RGB", size), args)
                _, badge, (x, y) = paste.call_args_list[0].args
                logo_width = round(size[0] * (.18 if size[0] < size[1] else .17))
                self.assertEqual(badge.width, round(logo_width * .231 / .284))
                self.assertEqual(x, 60 + (logo_width - badge.width) // 2)
                self.assertGreater(y, 34)

    def test_compact_medleys_preserve_song_metadata_and_two_song_titles(self):
        from workflow.live import package
        for title, expected in [("Nothing Even Matters / Brown Sugar / Lady", "Nothing Even Matters等串烧"),
                                ("Beautiful / Brave", "Beautiful / Brave")]:
            item = {"title": title}
            with patch.object(package, "cover_title", return_value=title):
                self.assertEqual(package.compact_cover_title(None, item), expected)
            self.assertEqual(item["title"], title)

    def test_optional_artist_and_event_before_language_tag(self):
        self.assertEqual(cover.cover_subtitle("Eminem · 中英字幕", "埃米纳姆", "奥斯卡2020"),
                         "埃米纳姆 Eminem·奥斯卡2020·中英字幕")
        self.assertEqual(cover.cover_subtitle("埃米纳姆 Eminem · 中英字幕", "埃米纳姆"),
                         "埃米纳姆 Eminem·中英字幕")

    def test_compact_ai_titles_fit_each_canvas_and_dominate_credits(self):
        for width, height in ((1920, 1080), (1440, 1080), (1080, 1440)):
            for title in ("One", "Drunk in Love", "Beautiful / Brave", "Follow Your Arrow", "m.A.A.d city / Radioactive", "Try / Just Give Me a Reason"):
                with self.subTest(title=title, width=width):
                    layout = cover.compact_credit_layout(title, "歌手 · 2014格莱美", "cjk", width, height)
                    if title == "Try / Just Give Me a Reason" and width == 1080:
                        self.assertEqual([entry[0] for entry in layout[:-1]], title.split(" / "))
                    elif title != "Try / Just Give Me a Reason":
                        self.assertEqual([entry[0] for entry in layout[:-1]], [title])
                    heights = []
                    last_bottom = 0
                    for line, face, baseline, _, tracking in layout:
                        left, top, right, bottom = face.getbbox(line, anchor="ms")
                        self.assertLessEqual(cover.ink_width(line, face, tracking), width * .90)
                        self.assertGreater(baseline + top, last_bottom)
                        last_bottom = baseline + bottom
                        heights.append(bottom - top)
                    self.assertLessEqual(heights[-1], max(heights[:-1]) * .65)
                    self.assertEqual(last_bottom, round(height * (.83 if width < height else .80)))

    def test_long_medley_lead_keeps_its_own_width(self):
        title = "Does Anybody Really Know What Time It Is?"
        credit = "Beginnings 等串烧 · 芝加哥乐队 & 罗宾·西克 · 2014格莱美"
        for width, height in ((1920, 1080), (1440, 1080), (1080, 1440)):
            lines = cover.compact_credit_layout(title, credit, "cjk", width, height)
            widths = [cover.ink_width(text, face, tracking) for text, face, _, _, tracking in lines]
            self.assertEqual(" ".join(line[0] for line in lines[:-1]), title)
            self.assertGreater(max(widths[:-1]), width * .85)
            self.assertEqual(lines[-1][-1], 0)

    def test_credit_can_extend_past_a_short_title(self):
        for size in ((1920, 1080), (1440, 1080), (1080, 1440)):
            title, credit = cover.compact_credit_layout("TQG", "夏奇拉 Shakira · 马德里演唱会2026", "cjk", *size)
            self.assertGreater(cover.ink_width(*credit[:2]), cover.ink_width(*title[:2]))
            self.assertEqual(credit[-1], 0)

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
