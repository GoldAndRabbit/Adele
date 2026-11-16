import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from post_bili.repair_intros import repair, extend_interpretation
from post_bili.upload import DEFAULTS, to_page
from post_bili.metadata_quality import fingerprint
from workflow.live.paths import read_json, write_json


class IntroRepairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'song'
        (self.directory / 'post').mkdir(parents=True)
        self.out = Path(self.temp.name) / 'repairs'
        self.out.mkdir()
        self.source = {'song': {'title': 'Song', 'artist': 'Artist'},
                       'intro': {'song': '旧歌曲段', 'performance': '旧演出段', 'lyrics': '旧解读段'}}
        write_json(self.directory / 'post/song.json', self.source)
        self.page = to_page({**DEFAULTS, 'video': 'video.mp4', 'cover': 'wide.jpg', 'cover43': 'four.jpg',
                             'title': 'Reviewed title', 'source': '', 'desc': '\n\n'.join(self.source['intro'].values()),
                             'tag': ['tag'], 'dtime': None})
        write_json(self.directory / 'post/bili_upload.json', self.page)
        write_json(self.directory / 'metadata_policy.json', {'title_format': 'reviewed_current'})
        self.song = {'path': str(self.directory), 'name': 'song', 'concert': 'sample'}
        self.generated = {**self.source['intro'], 'lyrics': self.source['intro']['lyrics'] + '意象。' * 620}

    def test_only_intro_changes_and_review_binding_is_updated(self):
        with patch('post_bili.repair_intros.extend_interpretation', return_value=self.generated):
            repair(self.song, self.out)
        page = read_json(self.directory / 'post/bili_upload.json')
        self.assertEqual({k: v for k, v in page.items() if k not in ('简介', '简介字符数')},
                         {k: v for k, v in self.page.items() if k not in ('简介', '简介字符数')})
        self.assertTrue(1800 <= len(page['简介']) <= 2000)
        self.assertTrue(page['简介'].startswith(self.page['简介']))
        self.assertEqual(read_json(self.directory / 'post/song.json')['song'], self.source['song'])
        saved_intro = read_json(self.directory / 'post/song.json')['intro']
        self.assertEqual(saved_intro['song'], self.source['intro']['song'])
        self.assertEqual(saved_intro['performance'], self.source['intro']['performance'])
        self.assertEqual(read_json(self.directory / 'metadata_policy.json')['reviewed_fingerprint'],
                         fingerprint(page['标题'], page['简介'], page['标签']))
        self.assertTrue((self.out / 'sample--song/before.json').exists())

    def test_concurrent_intro_edit_is_preserved(self):
        def generate(*args, **kwargs):
            page = read_json(self.directory / 'post/bili_upload.json')
            page['简介'] = '用户刚修改的简介'
            write_json(self.directory / 'post/bili_upload.json', page)
            return self.generated
        with patch('post_bili.repair_intros.extend_interpretation', side_effect=generate):
            with self.assertRaises(ValueError):
                repair(self.song, self.out)
        self.assertEqual(read_json(self.directory / 'post/bili_upload.json')['简介'], '用户刚修改的简介')
        self.assertEqual(read_json(self.directory / 'post/song.json'), self.source)

    def test_expansion_preserves_facts_and_rejects_new_stage_claims(self):
        original = {**self.source['intro'], 'lyrics': self.source['intro']['lyrics'] + '旧' * 1780}
        material = {'已有三部分介绍': original, '歌词材料': '愿望与选择', '歌名与歌手': {}}
        extra = '舞台上有巨大的飞龙。' + '情绪中的犹疑让愿望与选择形成对照。' * 150
        with patch('post_bili.repair_intros.chat_json', return_value={'text': extra}):
            intro = extend_interpretation(material, 'test')
        self.assertEqual(intro['song'], self.source['intro']['song'])
        self.assertEqual(intro['performance'], self.source['intro']['performance'])
        self.assertTrue(intro['lyrics'].startswith(self.source['intro']['lyrics']))
        self.assertNotIn('飞龙', intro['lyrics'])
        self.assertEqual(intro['lyrics'].count('情绪中的犹疑让愿望与选择形成对照。'), 1)
        self.assertTrue(1800 <= len('\n\n'.join(intro.values())) <= 2000)
