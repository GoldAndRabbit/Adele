import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from workflow import content_check as cc


OWN = 'silver lanterns shimmer softly through the ancient forest tonight'
OTHER = 'purple rockets travel swiftly beyond distant planets before sunrise'


def words(text, start, step=.4):
    return [{'w':w, 's':start+i*step, 'e':start+(i+1)*step-.04}
            for i,w in enumerate(text.split())]


class ContentCheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root/'original.mkv'
        self.source.write_bytes(b'original media')
        self.item = {'name':'01_own', 'idx':1}
        self.other = {'name':'02_other', 'idx':2}
        self.c = SimpleNamespace(slug='test', dir=self.root,
            song_items=lambda:[self.item,self.other], song_dir=lambda it:self.root/it['name'])
        for it,lyric in [(self.item,OWN),(self.other,OTHER)]:
            d = self.c.song_dir(it)
            (d/'reports').mkdir(parents=True)
            (d/'subs/translation').mkdir(parents=True)
            (d/'lyrics.txt').write_text(lyric)
            (d/'song.json').write_text(json.dumps({'slice':[40,70] if it==self.item else [75,100],
                                                   'source_file':str(self.source)}))
            (d/'subs/lines.json').write_text('[]')
            import pysubs2
            ass=pysubs2.SSAFile()
            ass.events.append(pysubs2.SSAEvent(start=9500,end=15000,text=lyric+r'\N中文译文'))
            ass.save(str(d/'subs/lyrics_poetic.ass'))
            (d/'subs/translation/result.json').write_text(json.dumps({'units':[
                {'i':0,'orig':lyric,'type':'歌词','start':9500,'end':15000,'v2_final':'中文译文'}]}))
        (self.root/'vertical_source.json').write_text(json.dumps({'songs':{
            '01_own':{'source':str(self.source),'slice':[40,70]},
            '02_other':{'source':str(self.source),'slice':[75,100]}}}))
        self.d = self.c.song_dir(self.item)
        identity = cc.boundary_identity(self.c,self.item)
        self.put(cc.EVIDENCE, {'input':identity,'source_duration':150,
            'contexts':[{'start':5,'end':105,'status':'ok'}], 'words':words(OWN,50)})
        self.put(cc.REVIEW, {'input':identity,'music':{'status':'passed',
            'start_reason':'verified instrumental onset before vocal',
            'end_reason':'verified instrumental decay and applause',
            'evidence':['original waveform and frames']}})

    def put(self,name,value):
        (self.d/name).write_text(json.dumps(value))

    def passed(self):
        result=cc.check(self.c,self.item)
        self.assertEqual(result['status'],'passed',result['issues'])
        return result

    def test_original_audio_inside_cut_passes_without_demanding_every_studio_verse(self):
        self.passed()
        self.assertEqual(cc.require_passed(self.c,self.item)['status'],'passed')

    def test_standard_production_reuses_prepared_assets_without_new_audit(self):
        with patch.object(cc,'audit_enabled',return_value=False),patch.object(cc,'check') as audit,\
             patch('workflow.source_lyrics.capture') as capture:
            report=cc.check_for_render(self.c,self.item)
        self.assertEqual(report['mode'],'prepared_preview')
        self.assertEqual(report['status'],'not_requested')
        audit.assert_not_called();capture.assert_not_called()

    def test_prepared_job_keeps_asset_integrity_without_claiming_audited_content(self):
        report=cc.prepared_report(self.c,self.item)
        for name in cc.ASSETS:(self.root/name).write_text(name)
        policy={'slice':[40,70],'content_check':cc.job_certificate(report,self.root,'a'*64)}
        self.assertEqual(policy['content_check']['status'],'not_requested')
        cc.require_job(policy,self.root)
        (self.root/'landscape.ass').write_text('different subtitles')
        with self.assertRaises(cc.ContentCheckFailed):cc.require_job(policy,self.root)

    def test_unrelated_single_without_lyrics_does_not_block_current_original(self):
        unrelated={'name':'03_unrelated','idx':3}
        self.c.song_items=lambda:[self.item,self.other,unrelated]
        policy=json.loads((self.root/'vertical_source.json').read_text())
        policy['songs'][unrelated['name']]={'source':str(self.root/'different.mp4'),'slice':[0,80]}
        (self.root/'vertical_source.json').write_text(json.dumps(policy))
        self.assertEqual(set(cc.inputs(self.c,self.item)['references']),{'01_own','02_other'})
        self.passed()

    def test_nontranslated_interjection_does_not_require_a_burned_event(self):
        p=self.d/'subs/translation/result.json';r=json.loads(p.read_text())
        r['units'].append({'i':1,'orig':'Woah-oh-oh','type':'语气词','start':1000,'end':2000,'v2_final':''})
        p.write_text(json.dumps(r))
        self.passed()

    def test_letter_chant_is_checked_against_actual_translation_not_han_presence(self):
        import pysubs2
        p=self.d/'subs/translation/result.json';r=json.loads(p.read_text())
        r['units'].append({'i':1,'orig':'H-O-T-T-O-G-O','type':'现场即兴','start':1000,'end':2000,
                           'v2_final':'H-O-T-T-O-G-O'})
        p.write_text(json.dumps(r))
        ass=pysubs2.load(str(self.d/'subs/lyrics_poetic.ass'))
        ass.events.append(pysubs2.SSAEvent(start=1000,end=2000,text='H-O-T-T-O-G-O'+r'\N'+'H-O-T-T-O-G-O'))
        ass.save(str(self.d/'subs/lyrics_poetic.ass'))
        self.passed()

    def test_own_lyrics_before_start_or_after_end_block_delivery(self):
        for start,kind in [(30,'missing_head'),(72,'missing_tail')]:
            with self.subTest(kind=kind):
                issues,_=cc.analyze([40,70],words(OWN,start),cc.lyric_references(self.c),'01_own',[])
                self.assertIn(kind,{i['kind'] for i in issues})

    def test_neighbor_lyrics_inside_cut_are_rejected_even_if_subtitles_call_them_speech(self):
        issues,_=cc.analyze([40,70],words(OTHER,55),cc.lyric_references(self.c),'01_own',[
            {'i':0,'orig':OTHER,'type':'讲话','start':15000,'end':20000}])
        self.assertIn('cross_song',{i['kind'] for i in issues})

    def test_actual_sung_line_without_subtitle_is_rejected(self):
        issues,_=cc.analyze([40,70],words(OWN,50),cc.lyric_references(self.c),'01_own',[])
        self.assertIn('missing_subtitle',{i['kind'] for i in issues})

    def test_actually_displayed_live_spoken_refrain_is_not_missing(self):
        units=[{'i':0,'orig':OWN,'type':'讲话','start':9500,'end':15000}]
        issues,_=cc.analyze([40,70],words(OWN,50),{'01_own':[OWN]},'01_own',units)
        self.assertNotIn('missing_subtitle',{i['kind'] for i in issues})

    def test_two_bound_independent_vocal_reads_can_correct_misheard_mix(self):
        unit={'i':0,'orig':OWN,'type':'歌词','start':10000,'end':15000}
        mix=words('this recognizer heard an entirely different phrase',50)
        read={'origin':'independent_saved_vocal_asr','original_source':{'path':'original'},
            'cache_sha256':'a'*64,'words':words(OWN,50)}
        issues,_=cc.analyze([40,70],mix,{'01_own':[OWN]},'01_own',[unit],[read])
        self.assertIn('unsupported_subtitle',{i['kind'] for i in issues})
        issues,_=cc.analyze([40,70],mix,{'01_own':[OWN]},'01_own',[unit],[read,{**read,'cache_sha256':'b'*64}])
        self.assertNotIn('unsupported_subtitle',{i['kind'] for i in issues})

    def test_ambiguous_short_refrains_do_not_claim_song_ownership(self):
        refs={'01_own':['oh baby i love you'], '02_other':['oh baby i love you']}
        self.assertEqual(cc.identify(words('oh baby i love you oh baby i love you',50),refs,'01_own'),[])

    def test_unique_four_word_final_line_outside_cut_is_not_missed(self):
        refs={'01_own':['death or love tonight'], '02_other':[OTHER]}
        issues,_=cc.analyze([40,70],words('death or love tonight',72),refs,'01_own',[])
        self.assertIn('missing_tail',{x['kind'] for x in issues})

    def test_previous_song_word_in_same_asr_window_does_not_claim_missing_head(self):
        ws=words('killer',35)+words(OWN,50)
        issues,_=cc.analyze([40,70],ws,{'01_own':[OWN],'02_other':[OTHER]},'01_own',[])
        self.assertNotIn('missing_head',{i['kind'] for i in issues})

    def test_non_lyric_shush_after_final_line_does_not_claim_missing_tail(self):
        ws=words(OWN,62)+words('shh',72)
        issues,_=cc.analyze([40,70],ws,{'01_own':[OWN],'02_other':[OTHER]},'01_own',[])
        self.assertNotIn('missing_tail',{i['kind'] for i in issues})

    def test_short_reference_cannot_make_unrelated_long_phrases_look_like_a_song(self):
        refs={'01_own':['i','oh',OWN], '02_other':['i','oh',OTHER]}
        found=cc.identify(words(OWN,50),refs,'01_own')
        self.assertTrue(found)
        self.assertEqual({x['owner'] for x in found},{'01_own'})

    def test_unsupported_forced_lyric_is_rejected(self):
        units=[{'i':0,'orig':OWN,'type':'歌词','start':10000,'end':15000}]
        issues,_=cc.analyze([40,70],words('this next one is called something entirely different',50),
                            {'01_own':[OWN]},'01_own',units)
        self.assertIn('unsupported_subtitle',{x['kind'] for x in issues})

    def test_compatible_multi_pass_vocal_is_an_uncertainty_not_a_proven_error(self):
        unit={'i':0,'orig':'Swam without looking back','start':1000}
        issue={'kind':'unsupported_subtitle','unit':0,'heard':'swimming by the big birds'}
        line={'start_ms':1000,'text':unit['orig'],'qwen':'got looking back','anchor':True,
              'conf':.61,'agree':['A1','A2','A3','A4']}
        self.assertEqual(cc.supported_vocal_disagreement(issue,[unit],[line])['kind'],'asr_disagreement')
        line['agree']=['A1','A2','C']
        self.assertIsNone(cc.supported_vocal_disagreement(issue,[unit],[line]))

    def test_clap_your_hands_cannot_authorize_animal_even_with_three_reads(self):
        unit={'i':0,'orig':"But you're an animal",'start':1000}
        issue={'kind':'unsupported_subtitle','unit':0,'heard':'just clap your hands'}
        line={'start_ms':1000,'text':unit['orig'],'qwen':'just clap your hands','anchor':True,
              'conf':.9,'agree':['A1','A2','A3','A4']}
        self.assertIsNone(cc.supported_vocal_disagreement(issue,[unit],[line]))

    def test_distinctive_title_words_allow_a_phonetic_disagreement_warning(self):
        unit={'i':0,'orig':'A super graphic ultra-modern, oh','start':1000}
        issue={'kind':'unsupported_subtitle','unit':0,'heard':'go tell model'}
        line={'start_ms':1000,'text':unit['orig'],'qwen':'Super graphic culture model you got me',
              'anchor':True,'conf':.6,'agree':['A1','A2','A3','A4']}
        self.assertEqual(cc.supported_vocal_disagreement(issue,[unit],[line])['kind'],'asr_disagreement')

    def test_correct_sidecar_cannot_authorize_wrong_actual_burn_file(self):
        import pysubs2
        ass=pysubs2.SSAFile()
        ass.events.append(pysubs2.SSAEvent(start=9500,end=15000,text=OTHER+r'\N另一首的字幕'))
        ass.save(str(self.d/'subs/lyrics_poetic.ass'))
        result=cc.check(self.c,self.item)
        self.assertEqual(result['status'],'failed')
        self.assertIn('rendered_subtitle_mismatch',{i['kind'] for i in result['issues']})

    def test_failed_or_missing_music_review_cannot_pass(self):
        self.put(cc.REVIEW,{})
        self.assertIn('music_boundaries_not_verified',{i['kind'] for i in cc.check(self.c,self.item)['issues']})

    def test_unclear_audio_finding_blocks_even_when_recognized_lyrics_match(self):
        review=json.loads((self.d/cc.REVIEW).read_text())
        review['findings']=[{'status':'pending','start':55,'end':58,
                            'reason':'two independent reads disagree on the live ad-lib'}]
        self.put(cc.REVIEW,review)
        result=cc.check(self.c,self.item)
        self.assertEqual(result['status'],'failed')
        self.assertFalse(result['checks']['lyrics_and_cross_song'])
        with self.assertRaises(cc.ContentCheckFailed):cc.require_passed(self.c,self.item)

    def test_human_hold_blocks_production_before_capture_or_check(self):
        self.passed()
        (self.root/'production_hold.json').write_text(json.dumps(
            {'active':True,'reason':'waiting for the requested human review'}))
        with patch.object(cc,'check') as check:
            with self.assertRaisesRegex(cc.ContentCheckFailed,'human review'):
                cc.check_for_render(self.c,self.item)
            check.assert_not_called()

    def test_hold_added_after_dispatch_rejects_previously_valid_job(self):
        report=self.passed()
        for name in cc.ASSETS:(self.root/name).write_text(name)
        policy={'slice':[40,70],'content_check':cc.job_certificate(report,self.root,'a'*64)}
        self.c.setlist=self.root/'vertical_source.json'
        self.c.item=lambda name:self.item
        (self.root/'production_hold.json').write_text(json.dumps({'active':True,'reason':'human review pending'}))
        with patch.object(cc,'Concert',return_value=self.c):
            with self.assertRaisesRegex(cc.ContentCheckFailed,'human review pending'):
                cc.require_job(policy,self.root)

    def test_missing_guard_band_or_failed_asr_chunk_is_not_a_pass(self):
        evidence=json.loads((self.d/cc.EVIDENCE).read_text())
        evidence['contexts']=[{'start':40,'end':70,'status':'ok'}]
        self.put(cc.EVIDENCE,evidence)
        self.assertIn('incomplete_source_coverage',{i['kind'] for i in cc.check(self.c,self.item)['issues']})

    def test_input_changes_invalidate_existing_pass(self):
        targets=[self.source,self.d/'subs/lyrics_poetic.ass',self.d/'subs/lines.json',
                 self.d/'subs/translation/result.json',self.d/cc.EVIDENCE,self.d/cc.REVIEW,
                 self.c.song_dir(self.other)/'lyrics.txt']
        for p in targets:
            with self.subTest(path=p.name):
                self.passed()
                old=p.read_bytes()
                p.write_bytes(old+b' ')
                with self.assertRaises(cc.ContentCheckFailed):cc.require_passed(self.c,self.item)
                p.write_bytes(old)
                # Restoring media bytes does not restore its original stat identity.
                identity=cc.boundary_identity(self.c,self.item)
                for rel in (cc.EVIDENCE,cc.REVIEW):
                    record=json.loads((self.d/rel).read_text());record['input']=identity;self.put(rel,record)

    def test_changing_cut_invalidates_prior_report(self):
        self.passed()
        policy=json.loads((self.root/'vertical_source.json').read_text())
        policy['songs']['01_own']['slice']=[39,70]
        (self.root/'vertical_source.json').write_text(json.dumps(policy))
        with self.assertRaises(cc.ContentCheckFailed):cc.require_passed(self.c,self.item)

    def test_partial_or_empty_checks_cannot_authorize_a_job(self):
        report=self.passed()
        for name in cc.ASSETS:(self.root/name).write_text(name)
        cert=cc.job_certificate(report,self.root,'a'*64)
        policy={'slice':[40,70],'content_check':cert}
        cc.require_job(policy,self.root)
        policy['content_check']['checks']={}
        with self.assertRaises(cc.ContentCheckFailed):cc.require_job(policy,self.root)

    def test_changed_worker_subtitles_or_cut_are_blocked_before_encoding(self):
        report=self.passed()
        for name in cc.ASSETS:(self.root/name).write_text(name)
        cert=cc.job_certificate(report,self.root,'a'*64)
        policy={'slice':[40,70],'content_check':cert}
        (self.root/'landscape.ass').write_text('different subtitles')
        with self.assertRaises(cc.ContentCheckFailed):cc.require_job(policy,self.root)
        (self.root/'landscape.ass').write_text('landscape.ass')
        policy['slice']=[39,70]
        with self.assertRaises(cc.ContentCheckFailed):cc.require_job(policy,self.root)

    def test_real_encode_entry_rejects_unchecked_job_before_probe_or_decoder(self):
        from workflow.dual_platform import encode_job
        with patch('workflow.dual_platform.probe') as probe:
            with self.assertRaises(cc.ContentCheckFailed):
                encode_job({'slice':[40,70]},self.source,self.root,self.root,self.root)
            probe.assert_not_called()


if __name__=='__main__':unittest.main()
