import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image
from fastapi import HTTPException

from server import app as server
from workflow import bili_collection as collection
from workflow.live.paths import Concert, write_json


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = Concert("sample")
        self.c.dir = Path(self.temp.name)
        self.c.songs = self.c.dir / "songs"
        self.item = {"kind": "song", "name": "hello", "title": "Hello"}
        write_json(self.c.info, {"title": "伦敦现场", "artist": "Adele", "date": "2021-11-06"})
        write_json(self.c.setlist, {"items": [self.item]})
        self.ai = self.c.song_dir(self.item) / "covers/ai"
        self.ai.mkdir(parents=True)
        Image.new("RGB", (640, 360), "navy").save(self.ai / "master.png")
        Image.new("RGB", (640, 360), "red").save(self.ai / "bili.jpg")
        write_json(self.ai / "masters.json", [{"file": "master.png"}])
        write_json(self.ai / "variants.json", [{"master": "master.png", "platform": "bili-ai", "ratio": "16x9", "file": "bili.jpg"}])

    def test_only_existing_bili_landscape_masters_are_candidates(self):
        rows = collection.candidates(self.c, [self.item])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["path"], self.ai / "master.png")
        (self.ai / "bili.jpg").unlink()
        self.assertEqual(collection.candidates(self.c, [self.item]), [])

    def test_limits_defaults_and_unicode(self):
        defaults = collection.defaults("现场" * 60, [self.item] * 300)
        self.assertLessEqual(len(defaults["title"]), 50)
        self.assertLessEqual(len(defaults["description"]), 500)
        self.assertTrue(defaults["sections_enabled"])
        valid = collection.validate({"title": "🎤" * 50, "description": "中" * 500}, [])
        self.assertEqual(len(valid["title"]), 50)
        for fields in ({"title": "中" * 51}, {"title": " "}, {"title": "a\nb"},
                       {"title": "a", "description": "中" * 501},
                       {"title": "a", "sections_enabled": "false"}):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                collection.validate(fields, [])

    def test_api_saves_metadata_and_generates_actual_title_cover(self):
        with patch.object(server, "concert", return_value=self.c):
            info = server.collection_info(self.c, "sample", "伦敦现场")
            self.assertTrue(info["sections_enabled"])
            saved = server.save_collection("sample", {"title": "Adele 伦敦现场", "description": "合集简介",
                                                      "sections_enabled": False, "source_id": info["source_id"]})
            self.assertFalse(saved["sections_enabled"])
            self.assertEqual(server.collection_info(self.c, "sample", "default")["description"], "合集简介")
            response = server.collection_cover("sample")
            with Image.open(response.path) as image:
                self.assertEqual(image.size, (1920, 1080))
                # Text creates bright pixels on a plain dark master.
                self.assertGreater(max(image.convert("L").crop((100, 600, 1800, 1000)).getdata()), 230)
            with self.assertRaises(HTTPException) as raised:
                server.save_collection("sample", {"title": "x" * 51})
            self.assertEqual(raised.exception.status_code, 422)
            # Rejected writes must preserve the last saved title.
            self.assertEqual(server.collection_info(self.c, "sample", "default")["title"], saved["title"])

    def test_simplified_chinese_title_uses_font_with_missing_glyph_coverage(self):
        from workflow.make_cover import font
        title = "Shakira-2026-夏奇拉马德里演唱会"
        key = collection.title_font_key(title)
        self.assertEqual(key, "cjk_sc")
        face = font(key, 64)
        missing = bytes(face.getmask(chr(0x10FFFF)))
        for char in title:
            self.assertNotEqual(bytes(face.getmask(char)), missing, char)
        self.assertEqual(collection.title_font_key("Adele Hello"), "cjk")

    def test_first_source_is_automatic_and_path_matches_generated_file(self):
        rows = collection.candidates(self.c, [self.item])
        info = collection.validate({"title": "合集", "source_id": "old-selection"}, rows)
        self.assertEqual(info["source_id"], rows[0]["id"])
        with patch.object(server, "concert", return_value=self.c):
            server.save_collection("sample", info)
            saved = server.collection_info(self.c, "sample", "default")
            response = server.collection_cover("sample")
            self.assertEqual(saved["cover_path"], str(Path(response.path).resolve()))
            self.assertTrue(Path(saved["cover_path"]).is_file())

    def test_titles_fit_one_centered_line_including_long_and_chinese_titles(self):
        titles = ["2026-格莱美-第68届", "Lorde-2026-奥斯汀城市极限音乐节",
                  "Shakira-2026-夏奇拉马德里演唱会", "W" * 50, "演" * 50]
        for title in titles:
            with self.subTest(title=title):
                face, (x, y), box = collection.title_layout(title)
                self.assertLessEqual(box[2] - box[0], 1660)
                self.assertAlmostEqual(x + (box[0] + box[2]) / 2, 960)
                self.assertEqual(y + box[3], 930)
                self.assertGreaterEqual(x + box[0], 130)
                self.assertLessEqual(x + box[2], 1790)
                if len(title) == 50:
                    self.assertLess(face.size, 112)
                # Inspect rendered bright pixels: each horizontal band belongs
                # to the same title line and the visible block is centered.
                output = self.c.dir / "layout.jpg"
                collection.render_cover(self.ai / "master.png", title, output)
                with Image.open(output) as image:
                    mask = image.convert("L").point(lambda value: 255 if value > 225 else 0)
                    left, top, right, bottom = mask.getbbox()
                self.assertLess(abs((left + right) / 2 - 960), 3)
                self.assertLess(bottom - top, face.size * 1.6)

    def test_performance_intro_migrates_without_song_position_and_keeps_whole_sentences(self):
        text = ("这场演出是 Olivia Rodrigo 在 Austin City Limits TV 节目中的完整表演，本曲是整场演出的第一首。"
                "舞台以紫红色调的城市夜景剪影为背景。"
                "Olivia 身穿浅灰色短袖上衣，搭配深色百褶裙。" + "观众举手欢呼，气氛热烈。" * 80)
        write_json(self.c.song_dir(self.item) / "post_draft.json", {"intro": {"performance": text}})
        description = collection.performance_description(self.c, [self.item], "合集")
        self.assertIn("Austin City Limits TV", description)
        self.assertIn("城市夜景", description)
        self.assertIn("百褶裙", description)
        self.assertNotIn("本曲", description)
        self.assertNotIn("第一首", description)
        self.assertLessEqual(len(description), 500)
        self.assertTrue(description.endswith("。"))
        with patch.object(server, "concert", return_value=self.c):
            auto = collection.defaults("合集", [self.item])
            server.save_collection("sample", auto)
            self.assertEqual(server.collection_info(self.c, "sample", "合集")["description"], description)
            server.save_collection("sample", {"title": "合集", "description": "用户定稿简介"})
            self.assertEqual(server.collection_info(self.c, "sample", "合集")["description"], "用户定稿简介")

    def test_mixed_artist_and_singles_collections_do_not_reuse_one_song_stage(self):
        info = {"title": "第68届格莱美颁奖典礼", "artist": "Various Artists", "date": "2026-02-01", "city": "洛杉矶"}
        write_json(self.c.info, info)
        write_json(self.c.song_dir(self.item) / "post_draft.json", {"intro": {"performance": "开场嘉宾的专属舞台。"}})
        description = collection.performance_description(self.c, [self.item], "合集")
        self.assertIn("格莱美", description)
        self.assertNotIn("专属舞台", description)
        self.c.slug = "singles"
        self.assertIsNone(collection.performance_description(self.c, [self.item], "合集"))

    def test_virtual_collections_have_separate_storage(self):
        self.assertNotEqual(collection.storage_path(self.c, "artist_adele"),
                            collection.storage_path(self.c, "artist_lorde"))
        self.assertTrue(collection.storage_path(self.c, "../../escape").is_relative_to(self.c.dir))


if __name__ == "__main__":
    unittest.main()
