import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from post_bili.receipt import archive_stale_receipt, current_receipt, receipt_matches, video_identity
from post_bili.full_library import reconcile_submission, submit_song, upload_batch
from post_bili.upload import DEFAULTS, to_page, from_page
from workflow.live.paths import write_json


class ReceiptVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        claimed_patch = patch('post_bili.full_library.claimed_bvids', return_value={})
        claimed_patch.start()
        self.addCleanup(claimed_patch.stop)
        self.song = Path(self.temp.name)
        (self.song / 'post').mkdir()
        (self.song / 'products').mkdir()
        self.video = self.song / 'products/bilibili-4k60.mp4'
        self.video.write_bytes(b'new render')
        self.page = {'视频文件': str(self.video), '标题': 'Same title'}
        write_json(self.song / 'post/bili_upload.json', self.page)
        write_json(self.song / 'products/products.json', {
            'run_id': 'new-run', 'items': [{'platform': 'bilibili', 'status': 'ready',
                                           'file': self.video.name, 'sha256': 'manifest-hash'}]})

    def test_old_video_receipt_does_not_skip_new_render_and_is_preserved(self):
        record = {'bvid': 'BV1234567890', 'video': str(self.song / 'old.mp4')}
        write_json(self.song / 'post/publish.json', record)
        self.assertIsNone(current_receipt(self.song))
        archive_stale_receipt(self.song)
        self.assertFalse((self.song / 'post/publish.json').exists())
        history = list((self.song / 'post/publish-history').glob('*.json'))
        self.assertEqual(len(history), 1)
        self.assertEqual(json.loads(history[0].read_text()), record)

    def test_receipt_is_invalid_after_same_path_file_changes(self):
        record = {'bvid': 'BV1234567890', 'video': str(self.video),
                  'video_identity': video_identity(self.song)}
        self.assertTrue(receipt_matches(self.song, record))
        self.video.write_bytes(b'different render bytes')
        self.assertFalse(receipt_matches(self.song, record))

    def test_manifest_and_posting_page_must_agree(self):
        old = self.song / 'old.mp4'
        old.write_bytes(b'old')
        with self.assertRaises(ValueError):
            video_identity(self.song, old)

    def test_title_recovery_without_independent_evidence_is_not_trusted(self):
        self.assertFalse(receipt_matches(self.song, {
            'bvid': 'BV1234567890', 'video': str(self.video), 'recovered_from_platform': True}))

    def test_legacy_receipt_with_actual_current_video_can_migrate(self):
        self.assertTrue(receipt_matches(self.song, {'bvid': 'BV1234567890', 'video': str(self.video)}))

    def test_reconcile_filters_old_same_title_before_restoring_new_attempt(self):
        write_json(self.song / 'post/bili_batch_pending', {
            'started_at': 2000, 'video_identity': video_identity(self.song)})
        listing = 'BV1234567890\tSame title\nBV0987654321\tSame title\n'
        old = json.dumps({'archive': {'aid': 1, 'ctime': 1000}, 'videos': [{}]})
        new = json.dumps({'archive': {'aid': 2, 'ctime': 2010}, 'videos': [{}]})
        with patch('post_bili.full_library.read_platform', side_effect=[listing, old, new]), \
                patch('post_bili.full_library.from_page', return_value={'video': str(self.video)}):
            self.assertTrue(reconcile_submission(self.song))
        self.assertEqual(current_receipt(self.song)['bvid'], 'BV0987654321')

    def test_old_same_title_alone_is_not_recovered(self):
        write_json(self.song / 'post/bili_batch_pending', {
            'started_at': 2000, 'video_identity': video_identity(self.song)})
        listing = 'BV1234567890\tSame title\n'
        old = json.dumps({'archive': {'aid': 1, 'ctime': 1000}, 'videos': [{}]})
        with patch('post_bili.full_library.read_platform', side_effect=[listing, old]):
            self.assertFalse(reconcile_submission(self.song))
        self.assertFalse((self.song / 'post/publish.json').exists())

    def test_same_title_created_before_this_attempt_is_not_recovered(self):
        write_json(self.song / 'post/bili_batch_pending', {
            'started_at': 2000.9, 'video_identity': video_identity(self.song)})
        listing = 'BV1234567890\tSame title\n'
        old = json.dumps({'archive': {'aid': 1, 'ctime': 1999}, 'videos': [{}]})
        with patch('post_bili.full_library.read_platform', side_effect=[listing, old]):
            self.assertFalse(reconcile_submission(self.song))

    def test_bvid_already_assigned_to_another_render_cannot_be_recovered(self):
        write_json(self.song / 'post/bili_batch_pending', {
            'started_at': 2000, 'video_identity': video_identity(self.song)})
        listing = 'BV1234567890\tSame title\n'
        new = json.dumps({'archive': {'aid': 1, 'ctime': 2010}, 'videos': [{}]})
        with patch('post_bili.full_library.read_platform', side_effect=[listing, new]):
            self.assertFalse(reconcile_submission(self.song, claimed={'BV1234567890': {'/another/song'}}))

    def test_known_old_render_does_not_require_an_unrelated_remote_query(self):
        write_json(self.song / 'post/bili_batch_pending', {
            'started_at': 2000, 'video_identity': video_identity(self.song)})
        with patch('post_bili.full_library.read_platform', return_value='BV1234567890\tSame title\n') as read:
            self.assertFalse(reconcile_submission(self.song, retired={'BV1234567890'}))
        read.assert_called_once()

    def test_failed_submit_leaves_pending_without_sleeping_or_repeating(self):
        with patch('post_bili.full_library.batch.upload', side_effect=subprocess.CalledProcessError(1, ['upload'])) as upload, \
                patch('post_bili.full_library.time.sleep') as sleep:
            with self.assertRaises(subprocess.CalledProcessError):
                submit_song(self.song)
        upload.assert_called_once()
        sleep.assert_not_called()
        self.assertTrue((self.song / 'post/bili_batch_pending').exists())

    def test_pending_submit_does_not_upload_again_or_block_on_remote_query(self):
        write_json(self.song / 'post/bili_batch_pending', {'started_at': 2000})
        with patch('post_bili.full_library.batch.upload') as upload, \
                patch('post_bili.full_library.reconcile_submission') as reconcile:
            with self.assertRaises(ValueError):
                submit_song(self.song)
        upload.assert_not_called()
        reconcile.assert_not_called()

    def test_one_song_failure_does_not_skip_later_songs_in_batch(self):
        first, second = self.song / 'first', self.song / 'second'
        progress = {}
        uploaded = set()
        def receipt(song):
            return {'bvid': 'BV0987654321'} if song in uploaded else None
        def submit(song, line="bda2"):
            if song == first:
                raise subprocess.CalledProcessError(1, ['upload'])
            uploaded.add(song)
        with patch('post_bili.full_library.current_receipt', side_effect=receipt), \
                patch('post_bili.full_library.batch.upload') as preflight, \
                patch('post_bili.full_library.submit_song', side_effect=submit) as posting:
            self.assertFalse(upload_batch([first, second], progress, lambda: None))
        self.assertEqual([call.args[0] for call in posting.call_args_list], [first, second])
        self.assertEqual(progress['pending_songs'], ['first'])
        self.assertIn('first', progress['song_errors'])
        self.assertNotIn('second', progress['song_errors'])

    def test_reviewed_legacy_page_without_optional_activity_fields_still_loads(self):
        fields = {**DEFAULTS, 'video': 'new.mp4', 'cover': 'wide.jpg', 'cover43': 'four.jpg',
                  'title': 'Reviewed title', 'source': '', 'desc': 'Reviewed description',
                  'tag': ['tag'], 'dtime': None}
        page = to_page(fields)
        for key in ('话题', '话题ID', '活动ID'):
            page.pop(key)
        restored = from_page(page)
        self.assertEqual(restored['title'], fields['title'])
        self.assertEqual(restored['desc'], fields['desc'])
        self.assertEqual(restored['cover'], fields['cover'])
        self.assertEqual(restored['topic'], '')
        self.assertIsNone(restored['topic_id'])
        self.assertIsNone(restored['mission_id'])
