import tempfile
import unittest
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch

from post_bili.sync_titles import manifest, pin_local, verify_no_edit_titles, eligible_rows, edit_was_rejected
from workflow.live.paths import read_json, write_json


class CurrentBatchTitleScopeTests(unittest.TestCase):
    def test_blocked_query_is_not_evidence_that_the_previous_edit_was_rejected(self):
        self.assertFalse(edit_was_rejected('412 Client Error for url: https://member.bilibili.com/x/vupre/web/archive/view'))
        self.assertFalse(edit_was_rejected('Read timed out for url: https://member.bilibili.com/x/vu/web/edit'))
        self.assertTrue(edit_was_rejected('412 Client Error for url: https://member.bilibili.com/x/vu/web/edit?csrf=[redacted]'))

    def test_uncertain_edit_does_not_block_other_archives(self):
        current=datetime(2026,11,16,18,40,tzinfo=ZoneInfo('Asia/Shanghai'))
        rows=[{'bvid':'pending'},{'bvid':'next'},{'bvid':'done'}]
        results={'pending':{'status':'pending_verification','checked_at':'2026-11-16T18:39:00+08:00'},
                 'next':{'status':'needs_retry','checked_at':'2026-11-16T16:01:00+08:00'},
                 'done':{'status':'verified'}}
        self.assertEqual(eligible_rows(rows,results,current),[rows[1]])
        later=current.replace(hour=19,minute=10)
        self.assertEqual(eligible_rows(rows,results,later),[rows[1],rows[0]])

    def test_read_only_title_verification_does_not_claim_pending_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'online-title-updates').mkdir()
            rows = [{'bvid':f'BV{i:010}', 'aid':i, 'title':'目标', 'snapshot_title':'目标'} for i in range(4)]
            rows[2]['snapshot_title'] = '旧标题'
            write_json(root/'online-title-updates'/('BV0000000001.json'), {'status':'submitting'})
            snapshot = root/'list.txt'
            snapshot.write_text('BV0000000000\t目标\t公开\nBV0000000001\t目标\t公开\n'
                                'BV0000000002\t目标\t公开\nBV0000000003\t其他\t公开\n')
            results = {}
            self.assertEqual(verify_no_edit_titles({'records':rows,'total':4},results,root,snapshot),1)
            self.assertEqual(list(results),['BV0000000000'])
            self.assertEqual(results['BV0000000000']['verification_mode'],'creator_list_no_edit')
            self.assertTrue(results['BV0000000000']['protected_fields_not_written'])

    def test_historical_receipts_for_current_song_do_not_expand_the_378_targets(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            records = [{'scope':'本次成片', 'bvid':f'BV{i:010}', 'local_path':str(root/str(i)),
                        'proposed':f'歌手 歌{i} 演出', 'before':'旧标题', 'online_title':'旧标题'}
                       for i in range(378)]
            # Legacy rows may incorrectly carry current_batch=True; scope and
            # the exact receipt binding must still exclude those old BVs.
            records += [{**records[i], 'scope':'历史版本', 'current_batch':True, 'bvid':f'BV9{i:09}'}
                        for i in range(30)]
            source = root/'review.json'
            write_json(source, {'records':records})
            (root/'task').mkdir()
            def receipt(directory):
                i = int(directory.name)
                return {'bvid':f'BV{i:010}', 'aid':i}
            with patch('post_bili.sync_titles.current_receipt', side_effect=receipt):
                plan = manifest(source,root/'task')
            self.assertEqual(len(plan['records']),378)
            self.assertEqual({r['bvid'] for r in plan['records']},{r['bvid'] for r in records[:378]})

    def test_local_title_pinning_preserves_review_and_cover_description_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = root/'song'
            (d/'post').mkdir(parents=True)
            c = root/'concert'
            c.mkdir()
            write_json(c/'review.json', {'songs':{'song':{'cover':'chosen','intro':'人工简介','status':'approved'}}})
            before = {'标题':'旧', '标题字符数':1, '简介':'完整简介', '封面16:9':'live16',
                      '封面4:3':'live43', '标签':['音乐'], '可见范围':'公开'}
            write_json(d/'post/bili_upload.json',before)
            task = root/'task'
            task.mkdir()
            plan = {'records':[{'bvid':'BV1234567890','path':str(d),'title':'歌手 歌名 演出'}]}
            with patch('post_bili.sync_titles.concert_directory',return_value=c):
                self.assertEqual(pin_local(plan,{'BV1234567890':{'status':'verified'}},task),1)
            after = read_json(d/'post/bili_upload.json')
            self.assertEqual({k:v for k,v in after.items() if k not in ('标题','标题字符数')},
                             {k:v for k,v in before.items() if k not in ('标题','标题字符数')})
            self.assertEqual(read_json(c/'review.json')['songs']['song'],
                             {'cover':'chosen','intro':'人工简介','status':'approved','title':'歌手 歌名 演出'})
