import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from server import metadata
from server import app as review_server
from workflow.live import paths


class MetadataCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "variants.json"
        metadata._load.cache_clear()

    def test_cached_cover_data_is_independent_and_invalidates_on_replace(self):
        self.path.write_text(json.dumps({"file": "old.jpg"}))
        original = self.path.stat()
        result = metadata.read_json(self.path)
        result["url"] = "/temporary-response-field"
        self.assertEqual(metadata.read_json(self.path), {"file": "old.jpg"})
        replacement = self.path.with_suffix(".tmp")
        replacement.write_text(json.dumps({"file": "new.jpg"}))
        os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
        replacement.replace(self.path)
        self.assertEqual(metadata.read_json(self.path), {"file": "new.jpg"})

    def test_removed_or_newly_created_metadata_does_not_stay_cached(self):
        self.assertEqual(metadata.read_json(self.path, []), [])
        self.path.write_text('{"ready":true}')
        self.assertEqual(metadata.read_json(self.path), {"ready": True})
        self.path.unlink()
        self.assertIsNone(metadata.read_json(self.path))

    def test_repeated_scan_reuses_file_contents(self):
        self.path.write_text('{"ready":true}')
        for _ in range(3):
            metadata.read_json(self.path)
        stats = metadata._load.cache_info()
        self.assertEqual((stats.misses, stats.hits), (1, 2))


class ProgressRefreshTests(unittest.TestCase):
    def test_just_published_cover_uses_fresh_album_catalog(self):
        stale = {'title': 'Show', 'covers': [{'name': 'old_song'}]}
        fresh = {'title': 'Show', 'covers': [{'name': 'old_song'}, {'name': 'new_song'}]}
        with patch.object(review_server, 'concert', return_value=object()), patch.object(
                review_server, 'build_album_covers', return_value=fresh), patch.object(
                review_server, 'collection_info', return_value={}), patch.object(
                review_server, 'review_snapshot') as snapshot:
            snapshot.return_value.get.return_value = stale
            snapshot.return_value.refresh.side_effect = lambda build, ttl: build()
            result = review_server.get_album_covers('sample', fresh=True)
            self.assertEqual([r['name'] for r in result['covers']], ['old_song', 'new_song'])
            snapshot.return_value.get.assert_not_called()
            self.assertNotIn('collection', fresh)

    def test_reload_refreshes_covers_products_and_visible_songs_together(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(
            review_server, "CONCERTS", Path(temp)
        ), patch.object(paths, "CONCERTS", Path(temp)):
            root = Path(temp)

            def write(path, data):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(data))

            items = [{"idx": 1, "name": "hello", "title": "Hello", "kind": "song", "artist": "Adele"},
                     {"idx": 2, "name": "new_song", "title": "New song", "kind": "song", "review_hidden": True}]
            for slug in ("concert", "singles"):
                write(root / slug / "concert.json", {"title": slug})
                write(root / slug / "setlist.json", {"items": items[:1] if slug == "singles" else items})
                (root / slug / "songs/hello").mkdir(parents=True)

            snapshot = review_server.ReviewSnapshot("test-progress-refresh")
            snapshot.path = root / "snapshot.json"
            cached = snapshot.refresh(review_server.build_concert_index, 60)
            self.assertTrue(all(len(g["tracks"]) == 1 for g in cached))
            self.assertTrue(all(not g["tracks"][0]["platform_covers_ready"] for g in cached))

            items[1]["review_hidden"] = False
            write(root / "concert/setlist.json", {"items": items})
            for slug, name in (("concert", "hello"), ("concert", "new_song"), ("singles", "hello")):
                song = root / slug / "songs" / name
                ai = song / "covers/ai"
                write(ai / "masters.json", [{"file": "master.jpg"}])
                variants = [{"master": "master.jpg", "platform": platform, "ratio": ratio,
                             "file": f"{platform}-{ratio}.jpg"}
                            for platform, ratio in (("bili-ai", "16x9"), ("bili-ai", "4x3"),
                                                    ("douyin-ai", "3x4"), ("douyin-ai", "4x3"))]
                write(ai / "variants.json", variants)
                for row in variants:
                    (ai / row["file"]).touch()
                write(song / "products/products.json", {"status": "ready", "items": [
                    {"platform": platform, "status": "ready", "file": f"{platform}.mp4"}
                    for platform in ("bilibili", "douyin")]})
                for platform in ("bilibili", "douyin"):
                    (song / "products" / f"{platform}.mp4").write_bytes(b'video')
                (song / "vertical").mkdir()
                (song / "vertical/full.mp4").touch()

            with patch.object(review_server, "review_snapshot", return_value=snapshot):
                self.assertIs(review_server.list_concerts(), cached)
                result = review_server.list_concerts(progress=True)
                self.assertEqual(len(result[0]["tracks"]), 2)
                for group in result:
                    for track in group["tracks"]:
                        for key in ("dual_products_ready", "platform_covers_ready", "portrait_preview_ready"):
                            self.assertTrue(track[key])
                self.assertEqual(review_server.list_concerts(), result)
                self.assertFalse(cached[0]["tracks"][0]["platform_covers_ready"])

                # Metadata alone is insufficient if one actual cover disappears.
                (root / "concert/songs/hello/covers/ai/douyin-ai-3x4.jpg").unlink()
                result = review_server.list_concerts(progress=True)
                self.assertFalse(result[0]["tracks"][0]["platform_covers_ready"])


if __name__ == "__main__":
    unittest.main()
