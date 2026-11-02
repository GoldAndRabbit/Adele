import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from workflow.song import title_translation as title


class TitleTranslationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.d = Path(self.temp.name)

    def test_fixed_title_wins_without_model_and_keeps_artist(self):
        title.save(self.d, {'title_zh': '旧标题', 'artist_zh': '埃米纳姆'})
        (self.d / 'zh_fixed.json').write_text(json.dumps({'__title__': '真正的痞子阿姆'}))
        r = {'title': '《The Real Slim Shady》 Eminem', 'units': []}
        with patch('workflow.song.song_translation_workflow.cached_ask', side_effect=AssertionError('must not call model')):
            title.translate(None, r, self.d)
        self.assertEqual(r['title_zh'], '《真正的痞子阿姆》 埃米纳姆')
        title.apply(self.d, r)
        self.assertEqual(r['title_zh'], '《真正的痞子阿姆》 埃米纳姆')

    def test_generated_title_is_saved_and_reused(self):
        r = {'title': '《Stan》 Eminem', 'units': []}
        with patch('workflow.song.song_translation_workflow.cached_ask', return_value={'zh': '斯坦', 'artist_zh': '埃米纳姆', 'why': '人物名'}) as model:
            title.translate(None, r, self.d)
            title.translate(None, r, self.d)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(title.resolved(self.d), '斯坦')
        self.assertEqual(r['title_zh'], '《斯坦》 埃米纳姆')

    def test_fixed_only_keeps_artist_on_fresh_translation(self):
        (self.d / 'zh_fixed.json').write_text(json.dumps({'__title__': '忘我'}))
        r = {'title': '《Lose Yourself》 Eminem', 'units': []}
        title.translate(None, r, self.d)
        self.assertEqual(r['title_zh'], '《忘我》 埃米纳姆')

    def test_metadata_reads_title_before_subtitles_exist(self):
        from workflow.make_meta import subs_title_zh
        title.save(self.d, {'title_zh': '胡迪尼'})
        self.assertEqual(subs_title_zh(self.d), '胡迪尼')


if __name__ == '__main__':
    unittest.main()
