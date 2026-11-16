import tempfile
import unittest
import copy
import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

from post_bili.edit_description import sync, sync_archive, sync_web
from workflow.live.paths import read_json, write_json


class DescriptionSyncTests(unittest.TestCase):
    def test_web_correction_keeps_current_title_both_covers_and_video(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            before = {'archive':{'aid':12,'bvid':'BV1234567890','title':'已修正标题','desc':'原简介',
                                 'cover':'https://i1/bfs/archive/wide','cover43':'https://i2/bfs/archive/tall'},
                      'videos':[{'cid':13,'filename':'file','title':'分P','desc':''}]}
            after = copy.deepcopy(before)
            after['archive']['desc'] = '核实后的简介'
            http = Mock()
            http.post.return_value.json.return_value={'code':0}
            with patch('post_bili.edit_description.current_receipt',return_value={'aid':12,'bvid':'BV1234567890'}), \
                 patch('post_bili.edit_cover.editor_view',side_effect=[before,after]), \
                 patch('post_bili.edit_description.bili_cookies',return_value={'bili_jct':'token'}), \
                 patch('post_bili.edit_cover.bili_cookies',return_value={'bili_jct':'token'}):
                result=sync_web(d,'核实后的简介',d/'task',
                                expected_before_sha256=hashlib.sha256('原简介'.encode()).hexdigest(),session=http)
            payload=http.post.call_args.kwargs['json']
            for key in ('title','cover','cover43'):
                self.assertEqual(payload[key],before['archive'][key])
            self.assertEqual(payload['videos'],before['videos'])
            self.assertEqual(result['status'],'verified')

    def test_web_correction_rejects_unexpected_newer_text_without_writing(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            before={'archive':{'aid':12,'bvid':'BV1234567890','desc':'用户刚改过的新简介'},'videos':[]}
            http=Mock()
            with patch('post_bili.edit_description.current_receipt',return_value={'aid':12,'bvid':'BV1234567890'}), \
                 patch('post_bili.edit_cover.editor_view',return_value=before):
                with self.assertRaisesRegex(ValueError,'其他修改'):
                    sync_web(d,'核实后的简介',d/'task',expected_before_sha256='old-hash',session=http)
            http.post.assert_not_called()

    def test_preview_is_not_full_description_and_accepted_edit_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / 'post').mkdir()
            text = '完整简介。' * 380
            write_json(directory / 'post/bili_upload.json', {'简介': text})
            archive = {'aid': 12, 'title': 'Existing title', 'desc': text[:250], 'cover': 'existing.jpg'}
            data = {'archive': archive, 'videos': [{'cid': 13, 'filename': 'file', 'title': 'video'}]}
            response = Mock()
            response.json.return_value = {'code': 0}
            with patch('post_bili.edit_description.current_receipt', return_value={'bvid': 'BV1234567890'}), \
                    patch('post_bili.edit_description.show', return_value=data), \
                    patch('post_bili.edit_description.public_description', return_value=None), \
                    patch('post_bili.edit_description.bili_cookies', return_value={'bili_jct': 'csrf'}), \
                    patch('post_bili.edit_description.requests.post', return_value=response) as post:
                self.assertFalse(sync(directory, directory / 'backup'))
                payload = post.call_args.kwargs['json']
                self.assertEqual(payload['desc'], text)
                self.assertEqual(payload['desc_v2'], [{'raw_text': text, 'type': 1, 'biz_id': ''}])
                self.assertEqual(payload['title'], archive['title'])
                self.assertEqual(payload['cover'], archive['cover'])
                self.assertFalse(sync(directory, directory / 'backup'))
                post.assert_called_once()
            self.assertEqual(read_json(directory / 'post/description_update.json')['status'],
                             'accepted_pending_verification')
            with patch('post_bili.edit_description.current_receipt', return_value={'bvid': 'BV1234567890'}), \
                    patch('post_bili.edit_description.public_description', return_value=text), \
                    patch('post_bili.edit_description.requests.post') as post:
                self.assertTrue(sync(directory, directory / 'backup'))
                post.assert_not_called()
            self.assertEqual(read_json(directory / 'post/description_update.json')['status'], 'verified')

    def test_restoration_preserves_a_newer_full_description(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            with patch('post_bili.edit_description.public_description', return_value='新的完整简介。' * 150), \
                    patch('post_bili.edit_description.show') as show, \
                    patch('post_bili.edit_description.requests.post') as post:
                self.assertFalse(sync_archive('BV1234567890', '原始简介。' * 300, {},
                    directory / 'result.json', directory / 'backup', only_if_truncated=True))
            show.assert_not_called()
            post.assert_not_called()
            self.assertEqual(read_json(directory / 'result.json')['status'], 'preserved_current_description')

    def test_confirmed_submission_is_not_edited_again_while_transcoding(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            text = '已提交的完整简介。' * 180
            with patch('post_bili.edit_description.public_description', return_value=None), \
                    patch('post_bili.edit_description.show') as show, \
                    patch('post_bili.edit_description.requests.post') as post:
                self.assertFalse(sync_archive('BV1234567890', text, {'desc': text},
                    directory / 'result.json', directory / 'backup'))
            show.assert_not_called()
            post.assert_not_called()
            self.assertEqual(read_json(directory / 'result.json')['status'], 'submitted_pending_verification')
