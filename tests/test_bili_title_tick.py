import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

from post_bili.title_tick import allowed,choose_action,finish,GAP_SECONDS


class OneArchivePacingTests(unittest.TestCase):
    def setUp(self):
        self.current=datetime(2026,11,16,17,30,tzinfo=ZoneInfo('Asia/Shanghai'))

    def test_next_archive_waits_a_full_minute_after_finish(self):
        state=finish({},'成功',True,self.current)
        self.assertEqual(GAP_SECONDS,60)
        self.assertFalse(allowed(state,self.current+timedelta(seconds=59))[0])
        self.assertTrue(allowed(state,self.current+timedelta(seconds=60))[0])

    def test_platform_rejection_requires_thirty_minute_cooldown(self):
        state=finish({},'412 Client Error',False,self.current)
        self.assertEqual(state['status'],'platform_cooldown')
        self.assertFalse(allowed(state,self.current+timedelta(minutes=29))[0])
        self.assertTrue(allowed(state,self.current+timedelta(minutes=30))[0])

    def test_cover_mismatch_prevents_all_automatic_retries(self):
        state=finish({},'AssertionError: 封面发生变化',False,self.current)
        self.assertFalse(allowed(state,self.current+timedelta(days=1))[0])

    def test_description_correction_and_title_edit_are_separate_items(self):
        progress={'counts':{'verified':258}}
        self.assertEqual(choose_action(progress,{}),'album')
        self.assertEqual(choose_action(progress,{'status':'verified'}),'title')
        self.assertEqual(choose_action({'counts':{'verified':378}},{'status':'verified'}),'done')
