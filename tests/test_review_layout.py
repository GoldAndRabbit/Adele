"""User scrolling must not move the song controls behind the flow navigation."""
import importlib.util
import json
from pathlib import Path
import unittest
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(importlib.util.find_spec('playwright'), 'Playwright is required')
class ReviewLayoutTests(unittest.TestCase):
    def test_full_album_card_remains_scrollable_below_navigation(self):
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel='chrome', headless=True)
            except Exception as error:
                self.skipTest(str(error))
            try:
                page = browser.new_page(viewport={'width': 1280, 'height': 720})
                page.set_content('<header class="flow-header">流程导航</header><div class="app">'
                    '<aside class="sidebar"></aside><main class="main"><section id="view">'
                    '<div class="card" style="height:3000px">全场封面</div></section></main></div>')
                page.add_style_tag(content=(ROOT/'web/style.css').read_text())
                page.locator('.main').hover()
                page.mouse.wheel(0, 1200)
                page.wait_for_function("document.querySelector('.main').scrollTop > 0")
                self.assertGreaterEqual(page.locator('.card').evaluate('(el) => el.clientHeight'), 2990)
                self.assertEqual(page.evaluate('document.documentElement.scrollTop'), 0)
            finally:
                browser.close()

    def test_long_cover_review_keeps_both_navigation_rows_visible(self):
        from playwright.sync_api import sync_playwright, expect

        item = {'idx': 1, 'name': 'my_kink', 'title': 'My Kink Is Karma',
                'artist': 'Chappell Roan', 'kind': 'song'}
        concert = {'slug': 'sample', 'info': {'title': '2026 Lollapalooza', 'artist': 'Chappell Roan'},
                   'songs': [item], 'items': [item], 'has_cover_pool': False}
        song = {**item, 'concert': concert, 'portrait_review': {'covers': []},
                'bili_upload': json.dumps({'标题': item['title'], '简介': '演出简介。'*300})}
        covers = {'frames': [], 'variants': [], 'generated': [
            {'file': 'master.jpg', 'model': 'fibo', 'url': '/example.svg',
             'reference_url': '/example.svg', 'prompt': '构图说明\n'*1000}]}

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel='chrome', headless=True)
            except Exception as error:
                self.skipTest(str(error))
            try:
                for width, height in ((1920, 1080), (1280, 720), (700, 500), (390, 844)):
                    with self.subTest(viewport=(width, height)):
                        context = browser.new_context(viewport={'width': width, 'height': height})
                        page = context.new_page()

                        def respond(route):
                            path = urlparse(route.request.url).path
                            if path == '/api/concerts':
                                route.fulfill(json=[{'slug': 'sample', 'title': 'Sample', 'tracks': [item]}])
                            elif path == '/api/concerts/sample':
                                route.fulfill(json=concert)
                            elif path.endswith('/cover_design'):
                                route.fulfill(json=covers)
                            elif path == '/api/concerts/sample/songs/my_kink':
                                route.fulfill(json=song)
                            elif path.startswith('/api/'):
                                route.fulfill(json={})
                            elif path == '/example.svg':
                                route.fulfill(content_type='image/svg+xml', body=(
                                    '<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080">'
                                    '<rect width="1920" height="1080" fill="#345"/></svg>'))
                            else:
                                file = ROOT/'web'/(path.lstrip('/') or 'index.html')
                                if file.is_file():
                                    route.fulfill(path=str(file))
                                else:
                                    route.abort()

                        page.route('**/*', respond)
                        page.goto('http://layout.test/#/sample/my_kink', wait_until='domcontentloaded')
                        tabs = page.get_by_role('tablist', name='单曲审核')
                        expect(tabs).to_be_visible()
                        tabs.get_by_role('tab', name='封面', exact=True).click()
                        expect(page.locator('.cover-review-table tbody tr')).to_have_count(1)
                        panel = page.locator('.song-review-card > section:visible')
                        panel.hover()
                        page.mouse.wheel(0, 1000)
                        page.wait_for_function('''() => document.querySelector(
                            '.song-review-card > section:not([hidden])').scrollTop > 0''')
                        geometry = page.evaluate('''() => ({
                            flow: document.querySelector('.flow-header').getBoundingClientRect().bottom,
                            controls: document.querySelector('.review-header').getBoundingClientRect().top,
                            scroll: document.documentElement.scrollTop,
                            overflow: document.body.scrollHeight-innerHeight
                        })''')
                        self.assertGreaterEqual(geometry['controls'], geometry['flow'])
                        self.assertEqual(geometry['scroll'], 0)
                        self.assertLessEqual(geometry['overflow'], 1)
                        expect(tabs.get_by_role('tab', name='投稿', exact=True)).to_be_visible()
                        page.get_by_role('tab', name='选品流', exact=True).click()
                        expect(page.locator('#app')).to_be_hidden()
                        page.get_by_role('tab', name='工作流', exact=True).click()
                        expect(tabs).to_be_visible()
                        context.close()
            finally:
                browser.close()


if __name__ == '__main__':
    unittest.main()
