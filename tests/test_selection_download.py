import argparse
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from workflow import selection_download as worker


class DownloadRetryTests(unittest.TestCase):
    def run_queue(self, outcomes, retries=0):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        storage = root / 'external'
        job = storage / 'selection-downloads/_queue'
        job.mkdir(parents=True)
        (root / 'external_storage.json').write_text(json.dumps({'root': str(storage)}))
        item = dict(artist='Artist', artist_id='artist', title='Music Video', video_id='abc',
                    url='https://youtu.be/abc', duration_seconds=180, attempts=0,
                    verification_retries=retries, status='pending')
        (job / 'queue.json').write_text(json.dumps({'items': [item]}))
        outcomes = iter(outcomes)
        def attempt(command, log_path):
            self.assertIn(f'temp:{storage}/selection-downloads/Artist', command)
            code, tail = next(outcomes)
            if code == 0:
                (job / 'abc.path').write_text(str(storage / 'selection-downloads/Artist/video.mkv') + '\n')
            return code, tail
        args = argparse.Namespace(browser='chrome:Default', batch_size=5, gap_min=60, gap_max=120, batch_pause=600)
        with patch.object(worker, 'ROOT', root), patch.object(Path, 'is_mount', return_value=True), \
             patch.object(worker.shutil, 'disk_usage', return_value=SimpleNamespace(free=100 * 1024**3)), \
             patch.object(worker, 'cli_args', return_value=[]), \
             patch.object(worker, 'download_attempt', side_effect=attempt) as download, \
             patch.object(worker, 'probe', return_value={'verified': True}), \
             patch.object(worker.time, 'sleep') as sleep:
            worker.run(args)
        return json.loads((job / 'queue.json').read_text()), download.call_count, sleep

    def test_challenge_waits_5_minutes_then_success_continues(self):
        state, calls, sleep = self.run_queue([(1, "Sign in to confirm you're not a bot"), (0, '')])
        self.assertEqual(calls, 2)
        sleep.assert_called_once_with(300)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(state['items'][0]['status'], 'completed')

    def test_second_challenge_stops_without_calling_it_expired_login(self):
        state, calls, sleep = self.run_queue([(1, 'Sign in to confirm'), (1, 'Sign in to confirm')])
        self.assertEqual(calls, 2)
        sleep.assert_called_once_with(300)
        self.assertEqual(state['status'], 'needs_verification')
        self.assertEqual(state['items'][0]['status'], 'pending')

    def test_retry_budget_survives_restart(self):
        state, calls, sleep = self.run_queue([(1, 'Sign in to confirm')], retries=1)
        self.assertEqual(calls, 1)
        sleep.assert_not_called()
        self.assertEqual(state['status'], 'needs_verification')

    def test_explicit_invalid_cookie_does_not_use_bot_challenge_retry(self):
        state, calls, sleep = self.run_queue([(1, 'cookies are no longer valid')])
        self.assertEqual(calls, 1)
        sleep.assert_not_called()
        self.assertEqual(state['status'], 'needs_login')

    def test_old_log_challenge_does_not_taint_new_attempt(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'video.log'
            path.write_text('Sign in to confirm\n')
            code, tail = worker.download_attempt([sys.executable, '-c', 'print("temporary network failure");exit(1)'], path)
            self.assertEqual(code, 1)
            self.assertNotIn('Sign in to confirm', tail)
            self.assertIn('temporary network failure', tail)
