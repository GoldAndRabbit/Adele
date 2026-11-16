import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from playwright.async_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeout

from workflow import douyin_queue as queue
from workflow.vertical_publish import DailyPostingLimit, TransientPublishError, match_work


class PublicationMatchTests(unittest.TestCase):
    plan = dict(title="Ribs 神婆 洛德 Lorde 肋骨 2026ACL音乐节", track="Ribs", duration=317.4)

    def test_old_same_song_does_not_hide_new_caption(self):
        cards = ["01:00\nLorde Ribs 蹦迪现场#lorde",
                 "05:17\nRibs 神婆 洛德 Lorde 肋骨 2026ACL音乐节#Lorde"]
        self.assertTrue(match_work(cards, self.plan))

    def test_other_performance_is_not_confirmation_or_error(self):
        self.assertFalse(match_work(["01:00\nLorde Ribs 蹦迪现场#lorde"], self.plan))


class QueueRetryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.context = dict(batch="batch", song="song", total=2)
        self.receipt = self.root / "receipt.json"
        self.patch = patch.object(queue, "QUEUE", self.root)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def test_page_timeouts_keep_retrying_beyond_old_limit(self):
        uploader = AsyncMock(side_effect=[PlaywrightTimeout("page load")] * 11 + [None])
        with patch.object(queue, "publish", uploader), patch.object(queue.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            self.assertTrue(await queue.publish_with_retries({}, self.receipt, self.context))
        self.assertEqual(uploader.await_count, 12)
        self.assertEqual([call.args[0] for call in sleep.await_args_list],
                         [15, 30, 60, 120, 240, 300, 300, 300, 300, 300, 300])

    async def test_daily_limit_stops_without_retry(self):
        self.receipt.write_text('{"status":"daily_limit"}')
        uploader = AsyncMock(side_effect=DailyPostingLimit("今天投稿次数已达到上限"))
        with patch.object(queue, "publish", uploader), patch.object(queue.asyncio, "sleep", new_callable=AsyncMock) as sleep:
            self.assertFalse(await queue.publish_with_retries({}, self.receipt, self.context))
        uploader.assert_awaited_once()
        sleep.assert_not_awaited()
        state = json.loads((self.root / "status.json").read_text())
        self.assertEqual(state["status"], "daily_limit")
        self.assertEqual(state["song"], "song")
        self.assertTrue(state["resume_after"].endswith("T00:30:00+08:00"))
        self.assertEqual(json.loads(self.receipt.read_text())["status"], "daily_limit")

    async def test_invalid_configuration_does_not_retry_forever(self):
        uploader = AsyncMock(side_effect=ValueError("missing cover"))
        with patch.object(queue, "publish", uploader), self.assertRaises(RuntimeError):
            await queue.publish_with_retries({}, self.receipt, self.context)
        uploader.assert_awaited_once()
        state = json.loads((self.root / "status.json").read_text())
        self.assertEqual(state["status"], "needs_attention")

    async def test_socket_reset_retries_without_logging_request_headers(self):
        error = PlaywrightError('APIRequestContext.get: socket hang up (ECONNRESET)\nCall log:\n - cookie: secret')
        uploader = AsyncMock(side_effect=[error, None])
        with patch.object(queue, "publish", uploader), patch.object(queue.asyncio, "sleep", new_callable=AsyncMock):
            self.assertTrue(await queue.publish_with_retries({}, self.receipt, self.context))
        self.assertEqual(uploader.await_count, 2)
        self.assertNotIn('secret', (self.root / 'status.json').read_text())

    async def test_empty_timeout_and_temporary_server_failure_retry(self):
        uploader = AsyncMock(side_effect=[TimeoutError(), TransientPublishError('HTTP 503'), None])
        with patch.object(queue, "publish", uploader), patch.object(queue.asyncio, "sleep", new_callable=AsyncMock):
            self.assertTrue(await queue.publish_with_retries({}, self.receipt, self.context))
        self.assertEqual(uploader.await_count, 3)
