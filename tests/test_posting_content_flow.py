"""Regression checks for canonical drafts versus self-referential upload exports."""
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from workflow.live.paths import read_json, write_json
from workflow.delivery_bundle import write_bundle
from post_bili.upload import description

class Fixture:
    slug = 'fixture'
    def __init__(self, root):
        self.dir = root
        self.directory = root / 'songs/song'
        self.directory.mkdir(parents=True)
        self.info = root / 'concert.json'
        write_json(self.info, {'artist':'Adele','artist_zh':'阿黛尔',
                              'title_zh':'2021年演唱会','date':'2021-10-24'})
    def load(self, key):
        return read_json(self.info) if key == 'info' else read_json(self.dir / (key+'.json'))
    def song_dir(self, item):
        return self.directory

class PostingContentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.c = Fixture(Path(self.temp.name))
        self.item = {'name':'song','title':'Hello','artist':'Adele'}
        self.draft = {'song':{'title':'Hello','artist':'Adele','artist_zh':'阿黛尔'},
            'performance':{'event':'2021年演唱会','date':'2021-10-24'},
            'intro':{'song':'歌曲正文。'*125,'performance':'演出正文。'*125,'lyrics':'意象正文。'*125},
            'intro_text':'旧占位简介', 'tags':['阿黛尔','音乐现场','英语歌曲']}
        write_json(self.c.directory/'post_draft.json', self.draft)
        (self.c.directory/'post').mkdir()
        write_json(self.c.directory/'post/bili_upload.json', {'标题':'旧标题','简介':'旧占位简介',
            '标签':['旧标签'],'可见范围':'仅自己可见','定时发布':None})
    def test_sections_override_outdated_intro_text(self):
        self.assertEqual(description(self.draft), '\n\n'.join(self.draft['intro'].values()))
    def test_rebuild_updates_both_platforms_and_preserves_settings(self):
        result = write_bundle(self.c, self.item)
        text = description(self.draft)
        self.assertEqual(result['bilibili']['简介'], text)
        self.assertEqual(result['douyin']['description_body'], self.draft['intro']['song'])
        self.assertIn('英语歌曲', result['bilibili']['标签'])
        self.assertEqual(result['bilibili']['可见范围'], '仅自己可见')
        self.assertIsNone(result['bilibili']['定时发布'])
        self.assertEqual(read_json(self.c.directory/'post/bili_upload.json')['简介'], text)
        self.assertEqual(read_json(self.c.directory/'vertical/douyin_submission.json')['description_body'],self.draft['intro']['song'])
    def test_second_rebuild_does_not_reuse_its_previous_export(self):
        write_bundle(self.c,self.item)
        self.draft['intro']['song'] = '新的歌曲正文。'*80
        write_json(self.c.directory/'post_draft.json',self.draft)
        result = write_bundle(self.c,self.item)
        self.assertEqual(result['bilibili']['简介'],description(self.draft))
        self.assertEqual(result['douyin']['description_body'],self.draft['intro']['song'])
    def test_upload_preflight_rejects_placeholder_intro(self):
        from post_bili.upload import check
        _, errors = check({'title':'Hello','desc':'占位简介','tag':[]})
        self.assertTrue(any('简介' in message and '1800' in message for message in errors))

    def test_standard_package_accepts_current_title_rule(self):
        from workflow.live.package import validate_presentation
        self.draft['title']='阿黛尔 Hello Adele 现场'
        write_json(self.c.directory/'post_draft.json',self.draft)
        with patch('workflow.live.package.post_title',return_value=self.draft['title']),patch('workflow.live.package.subtitle_line',return_value='现场'):
            validate_presentation(self.c,self.item)

    def test_standard_package_rejects_placeholder_intro(self):
        from workflow.live.package import validate_presentation
        self.draft.update(title='阿黛尔 Hello Adele 现场',intro={},intro_text='占位简介')
        write_json(self.c.directory/'post_draft.json',self.draft)
        with patch('workflow.live.package.post_title',return_value=self.draft['title']),patch('workflow.live.package.subtitle_line',return_value='现场'):
            with self.assertRaisesRegex(ValueError,'简介'):
                validate_presentation(self.c,self.item)

    def test_retired_exported_cover_is_not_kept_as_an_active_selection(self):
        saved=read_json(self.c.directory/'post/bili_upload.json')
        saved['封面16:9']='/retired/imagegen.jpg'
        saved['封面4:3']='/retired/imagegen-wide.jpg'
        write_json(self.c.directory/'post/bili_upload.json',saved)
        result=write_bundle(self.c,self.item)
        self.assertIsNone(result['bilibili']['封面16:9'])
        self.assertIsNone(result['bilibili']['封面4:3'])

    def test_explicit_review_edits_remain_authoritative(self):
        title = '阿黛尔 Hello 阿呆 Adele 你好 人工确认的演出信息'
        write_json(self.c.dir/'review.json',{'songs':{'song':{'title':title,'intro':'人工确认的简介。','tags':['人工标签']}}})
        result=write_bundle(self.c,self.item)
        self.assertEqual(result['bilibili']['标题'],title)
        self.assertEqual(result['bilibili']['标题字符数'],len(title))
        self.assertEqual(result['bilibili']['简介'],'人工确认的简介。')
        self.assertEqual(result['douyin']['description_body'],'人工确认的简介。')
        self.assertEqual(result['bilibili']['标签'],['人工标签'])

    def test_reviewed_title_survives_reexport_and_upload_name_processing(self):
        from workflow.bili_title import apply_submission_names
        title = '阿黛尔 Hello 阿呆 Adele 你好 人工定稿'
        write_json(self.c.dir/'review.json',{'songs':{'song':{'title':title}}})
        first = write_bundle(self.c,self.item)['bilibili']
        second = write_bundle(self.c,self.item)['bilibili']
        apply_submission_names(second,self.c.directory,self.draft)
        self.assertEqual(first['标题'],title)
        self.assertEqual(second['标题'],title)

    def test_packaging_export_and_preflight_share_the_current_single_song_source(self):
        from workflow.bili_title import apply_submission_names
        from workflow.live.package import post_title
        from post_bili.upload import load_post
        source = {'song':{'title':'Current Song','artist':'Adele','artist_zh':'阿黛尔','title_zh':'新歌'},
                  'performance':{'event_en':'Current Show'}}
        write_json(self.c.directory/'post/song.json',source)
        exported = write_bundle(self.c,self.item)['bilibili']
        expected = post_title(self.c,self.item)
        apply_submission_names(exported,self.c.directory,load_post(self.c.directory)[0])
        self.assertIn('Current Song',expected)
        self.assertIn('Current Show',expected)
        self.assertEqual(exported['标题'],expected)

if __name__=='__main__':unittest.main()
