import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow import content_repair as cr
from workflow.live.paths import read_json, write_json
from workflow.content_check import source_identity


class ContentRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.d=self.root/'songs/01_song'
        (self.d/'subs/translation').mkdir(parents=True)
        self.item={'name':'01_song'}
        self.c=SimpleNamespace(slug='test',dir=self.root,segments=self.root/'segments.json',
            song_dir=lambda item:self.d)
        self.source=self.root/'source.mkv';self.source.write_bytes(b'original')
        write_json(self.root/'vertical_source.json',{'songs':{'01_song':{
            'source':str(self.source),'slice':[40,70]}}})
        write_json(self.c.segments,{'items':[{'name':'01_song','start':40,'end':70}]})
        write_json(self.d/'song.json',{'slice':[40,70],'source_file':str(self.source)})
        (self.d/'lyrics.txt').write_text('actual words\n')
        write_json(self.d/'subs/lines.json',[{'start_ms':1000,'end_ms':3000,'text':'actual words'}])
        write_json(self.d/'subs/translation/result.json',{'units':[{'i':0,'start':1000,
            'end':3000,'orig':'actual words','type':'歌词','v2_final':'原译文'}],'notes':{}})
        write_json(self.d/'subs/asr_words_1.json',[{'w':'actual','s':1,'e':2}])
        (self.d/'audio.flac').write_bytes(b'old clock audio')

    def test_cut_extension_keeps_translation_and_old_clock_evidence(self):
        with patch.object(cr,'assert_idle'),patch('workflow.preview.enable_browser'),\
             patch('workflow.song.watermark.ensure_song'),\
             patch('workflow.song.song_translation_workflow.build_outputs'):
            backup=cr.change_cut(self.c,self.item,35,70)
        unit=read_json(self.d/'subs/translation/result.json')['units'][0]
        self.assertEqual((unit['start'],unit['end'],unit['v2_final']),(6000,8000,'原译文'))
        self.assertEqual(read_json(self.root/'vertical_source.json')['songs']['01_song']['slice'],[35,70])
        self.assertTrue((backup/'subs/asr_words_1.json').exists())
        self.assertTrue((backup/'audio.flac').exists())
        self.assertFalse((self.d/'audio.flac').exists())

    def test_active_worker_assets_cannot_be_changed(self):
        worker=SimpleNamespace(info={'pid':1,'cmdline':['python','-m','workflow.delivery',
            'test','--only','01_song']})
        with patch('psutil.process_iter',return_value=[worker]):
            with self.assertRaises(RuntimeError):cr.assert_idle(self.c,self.item)

    def test_same_song_name_in_another_concert_does_not_block_repair(self):
        worker=SimpleNamespace(info={'pid':1,'cmdline':['python','-m','workflow.delivery',
            'different_concert','--only','01_song']})
        with patch('psutil.process_iter',return_value=[worker]):cr.assert_idle(self.c,self.item)

    def test_confident_model_rewrite_needs_two_independent_reads(self):
        reads=[[{'w':'looking','s':1,'e':2},{'w':'back','s':2,'e':3}]]
        self.assertFalse(cr.corroborated('Swimming by the big birds',1,3,reads))
        self.assertFalse(cr.corroborated('looking back',1,3,reads))
        self.assertTrue(cr.corroborated('looking back',1,3,reads*2))

    def test_parallel_review_writers_use_distinct_atomic_temporary_files(self):
        p=self.root/'shared-review.json'
        with ThreadPoolExecutor(max_workers=6) as workers:
            list(workers.map(lambda n:write_json(p,{'writer':n,'body':'x'*1000}),range(40)))
        self.assertEqual(read_json(p)['body'],'x'*1000)
        self.assertFalse(list(self.root.glob('.shared-review.json.*.tmp')))

    def test_exact_audible_refrain_is_restored_only_in_an_uncovered_gap(self):
        words=[{'w':w,'s':50+i*.3,'e':50+(i+1)*.3} for i,w in enumerate('I get the job done'.split())]
        issues=[{'kind':'missing_subtitle','start':50,'end':51.5}]
        refs=['I get the job done','I get the job done every day']
        rows=cr.exact_missing_rows(issues,words,[],refs,40,30)
        self.assertEqual([r['text'] for r in rows],['I get the job done'])
        self.assertFalse(cr.exact_missing_rows(issues,words,[{'start':9500,'end':12000}],refs,40,30))

    def test_review_windows_stay_inside_source_and_do_not_grow_unbounded(self):
        issues=[{'start':41,'end':43},{'start':65,'end':69},{'start':110,'end':115}]
        windows=cr.merge_intervals(issues,40,100)
        self.assertEqual(windows[0][:2],[0,11])
        self.assertTrue(all(0<=a<b<=100 and b-a<=75 for a,b,_ in windows))

    def test_unsupported_or_unheard_model_claim_does_not_resolve_issue(self):
        (self.d/'reports').mkdir(exist_ok=True)
        write_json(self.d/'reports/source_lyrics_evidence.json',{'words':[]})
        issue={'id':'specific-issue','kind':'unsupported_subtitle','unit':0,'start':41,'end':43}
        report={'status':'failed','issues':[issue]}
        def fake_extract(source,start,end,path):path.write_bytes(b'observed audio')
        def fake_ask(audio,prompt,output):
            result={'decisions':[{'issue_id':'specific-issue','status':'supported',
                'reason':'generic claim without heard words','confidence':1}]}
            write_json(output,{'result':result});return result
        with patch.object(cr,'assert_idle'),patch.object(cr,'check',return_value=report),\
             patch.object(cr,'boundary_identity',return_value={'binding':'original'}),\
             patch.object(cr,'extract',side_effect=fake_extract),patch.object(cr,'ask',side_effect=fake_ask):
            cr.repair_captions(self.c,self.item)
        self.assertEqual(read_json(self.d/cr.REVIEW)['resolutions'],[])

    def test_extended_selection_reuses_old_vocals_with_their_original_clock(self):
        (self.d/'reports').mkdir(exist_ok=True)
        old=self.root/'preserved-vocals.wav';old.write_bytes(b'isolated original vocals')
        original=source_identity(self.source)
        write_json(self.d/'reports/source_lyrics_evidence.json',{'input':{'source':original},
            'words':[],'alternate_reads':[{'origin':'independent_saved_vocal_asr',
            'original_source':original,'cache_sha256':'a'*64,'source_range':[35,75],
            'audio_track':source_identity(old),'words':[]} ]})
        issue={'id':'specific-issue','kind':'unsupported_subtitle','unit':0,'start':41,'end':43}
        report={'status':'failed','issues':[issue]};seen=[]
        def extract(source,start,end,path):
            seen.append((source,start,end));path.write_bytes(b'review audio')
        def ask(audio,prompt,path):
            result={'decisions':[]};write_json(path,{'result':result});return result
        with patch.object(cr,'assert_idle'),patch.object(cr,'check',return_value=report),\
             patch.object(cr,'boundary_identity',return_value={'source':original}),\
             patch.object(cr,'extract',side_effect=extract),patch.object(cr,'ask',side_effect=ask):
            cr.repair_captions(self.c,self.item)
        self.assertEqual(seen,[(str(old.resolve()),5,16)])


if __name__=='__main__':unittest.main()
