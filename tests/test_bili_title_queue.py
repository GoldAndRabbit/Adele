import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from post_bili.title_queue import wait_delay,blocked_reason


class BackgroundTitlePacingTests(unittest.TestCase):
    def test_each_item_waits_until_its_persisted_deadline(self):
        current=datetime(2026,11,16,18,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        pacing={'next_attempt_after':(current+timedelta(seconds=60)).isoformat()}
        self.assertEqual(wait_delay(pacing,current),60)
        self.assertEqual(wait_delay(pacing,current+timedelta(seconds=59)),1)
        self.assertEqual(wait_delay(pacing,current+timedelta(seconds=61)),0)

    def test_reporting_trigger_does_not_override_platform_cooldown(self):
        current=datetime(2026,11,16,18,20,tzinfo=ZoneInfo('Asia/Shanghai'))
        pacing={'status':'platform_cooldown','next_attempt_after':(current+timedelta(minutes=30)).isoformat()}
        self.assertEqual(wait_delay(pacing,current+timedelta(minutes=20)),600)
        self.assertFalse(blocked_reason(pacing))

    def test_preservation_failure_or_login_requirement_stops_the_worker(self):
        self.assertTrue(blocked_reason({'status':'preservation_check_failed'}))
        self.assertTrue(blocked_reason({'last_output':'稿件查询失败：账号未登录'}))
