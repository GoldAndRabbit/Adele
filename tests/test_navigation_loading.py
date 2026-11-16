"""The track list must remain available when all heavy requests fail."""
import importlib.util
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from server import app as server

ROOT = Path(__file__).resolve().parents[1]


class NavigationEndpointTests(unittest.TestCase):
    def test_navigation_never_scans_song_assets_or_review_status(self):
        items = [{"idx": 1, "name": "hello", "title": "Hello", "kind": "song", "artist": "Adele"}]
        for slug in ("new_concert", "artist_6164656c65", "singles_261115"):
            with self.subTest(slug=slug), ExitStack() as stack:
                concert = SimpleNamespace(
                    slug=slug, info=Path("unused.json"), has_cover_pool=False,
                    load=lambda key: {"items": [], "gaps": []})
                stack.enter_context(patch.object(server, "concert", return_value=concert))
                stack.enter_context(patch.object(server, "visible_items", return_value=items))
                stack.enter_context(patch.object(server, "read_json", return_value={"title": "Adele"}))
                stack.enter_context(patch.object(server, "song_summary", side_effect=AssertionError("heavy scan")))
                stack.enter_context(patch.object(server.review, "load", side_effect=AssertionError("review scan")))
                result = server.get_concert(slug, navigation=True)
                self.assertEqual(result["slug"], slug)
                self.assertEqual([song["name"] for song in result["songs"]], ["hello"])


@unittest.skipUnless(importlib.util.find_spec("playwright"), "Playwright is required for browser regression checks")
class NavigationBrowserTests(unittest.TestCase):
    def test_cold_routes_show_tracks_without_index_covers_or_song_details(self):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(channel="chrome")
            except Exception as error:
                self.skipTest(str(error))
            try:
                for target in ("new_concert/~album-covers",
                               "new_concert/hello",
                               "artist_6164656c65",
                               "artist_6164656c65/hello"):
                    with self.subTest(target=target):
                        context = browser.new_context()
                        page = context.new_page()

                        def respond(route):
                            from urllib.parse import urlparse
                            url = urlparse(route.request.url)
                            if url.path.startswith("/api/"):
                                if url.query == "navigation=true":
                                    slug = url.path.split("/")[-1]
                                    song = {"idx": 1, "name": "hello", "title": "Hello",
                                            "kind": "song", "artist": "Adele"}
                                    route.fulfill(json={"slug": slug, "info": {"title": "Adele"},
                                                        "items": [song], "songs": [song],
                                                        "has_cover_pool": False})
                                else:
                                    route.abort()
                                return
                            path = ROOT / "web" / (url.path.lstrip("/") or "index.html")
                            if path.is_file():
                                route.fulfill(path=str(path))
                            else:
                                route.abort()

                        page.route("**/*", respond)
                        try:
                            page.goto("http://navigation.test/#/" + target,
                                      wait_until="domcontentloaded")
                            page.wait_for_selector("#songs .song-row", timeout=5000)
                            self.assertEqual(page.locator("#songs .song-row").count(), 1)
                            self.assertEqual(
                                page.locator("#songs .song-row a").get_attribute("href"),
                                "#/" + target.split("/")[0] + "/hello")
                        finally:
                            context.close()
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()
