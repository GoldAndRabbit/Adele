import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from post_bili.edit_title import sync
from workflow.live.paths import write_json, read_json


class TitleOnlyEditTests(unittest.TestCase):
    def fixtures(self, directory):
        body = '当前线上的完整简介。' * 180
        (directory / 'post').mkdir()
        write_json(directory / 'post/bili_upload.json', {'简介': body})
        receipt = {'bvid': 'BV1234567890', 'aid': 123, 'desc': body}
        before = {'archive': {**receipt, 'title': '旧标题', 'cover': 'https://i1/bfs/archive/one.jpg',
                             'cover43': 'https://i2/bfs/archive/two.jpg', 'state': 0,
                             'desc_v2': [{'raw_text': body, 'type': 1, 'biz_id': ''}], 'desc_format_id': 9999},
                  'videos': [{'cid': 456, 'filename': 'media-file', 'title': '分P名称', 'desc': ''}]}
        after = copy.deepcopy(before)
        after['archive']['title'] = '新标题'
        return receipt, before, after

    def test_edit_preserves_complete_copy_both_covers_and_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            receipt, before, after = self.fixtures(d)
            http = Mock()
            http.post.return_value.json.return_value = {'code': 0}
            with patch('post_bili.edit_title.editor_view', side_effect=[before, after]), \
                 patch('post_bili.edit_title.bili_cookies', return_value={'bili_jct': 'token'}), \
                 patch('post_bili.edit_cover.bili_cookies', return_value={'bili_jct': 'token'}):
                result = sync(d, '新标题', d / 'task', receipt=receipt, session=http)
            payload = http.post.call_args.kwargs['json']
            self.assertEqual(payload['title'], '新标题')
            for key in ('desc', 'desc_v2', 'cover', 'cover43'):
                self.assertEqual(payload[key], before['archive'][key])
            self.assertEqual(payload['videos'], before['videos'])
            self.assertEqual(result['status'], 'verified')
            self.assertTrue(result['changed'])

    def test_matching_title_is_verified_without_resubmitting(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            receipt, before, _ = self.fixtures(d)
            http = Mock()
            with patch('post_bili.edit_title.editor_view', return_value=before):
                result = sync(d, '旧标题', d / 'task', receipt=receipt, session=http)
            http.post.assert_not_called()
            self.assertFalse(result['changed'])

    def test_cover_change_is_not_reported_as_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            receipt, before, after = self.fixtures(d)
            after['archive']['cover43'] = 'https://i2/bfs/archive/unexpected.jpg'
            http = Mock()
            http.post.return_value.json.return_value = {'code': 0}
            with patch('post_bili.edit_title.editor_view', side_effect=[before, after]), \
                 patch('post_bili.edit_title.bili_cookies', return_value={'bili_jct': 'token'}), \
                 patch('post_bili.edit_cover.bili_cookies', return_value={'bili_jct': 'token'}):
                with self.assertRaisesRegex(AssertionError, '封面'):
                    sync(d, '新标题', d / 'task', receipt=receipt, session=http)
            self.assertEqual(read_json(d / 'task/online-title-updates/BV1234567890.json')['status'],
                             'accepted_pending_verification')

    def test_post_timeout_keeps_uncertain_intent_for_read_only_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            receipt, before, _ = self.fixtures(d)
            http = Mock()
            http.post.side_effect = TimeoutError('no response')
            with patch('post_bili.edit_title.editor_view', return_value=before), \
                 patch('post_bili.edit_title.bili_cookies', return_value={'bili_jct': 'token'}), \
                 patch('post_bili.edit_cover.bili_cookies', return_value={'bili_jct': 'token'}):
                with self.assertRaises(TimeoutError):
                    sync(d, '新标题', d / 'task', receipt=receipt, session=http)
            self.assertEqual(read_json(d / 'task/online-title-updates/BV1234567890.json')['status'], 'submitting')
