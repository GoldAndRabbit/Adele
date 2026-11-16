import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from workflow.cover_visual_review import CHECKS, accepted
from workflow.fibo_dual_queue import reusable_stage, release_reviewed, run
from workflow.live.paths import write_json
from workflow.reviewed_cover import digest


class DualCoverTests(unittest.TestCase):
    def test_explicit_replacement_reselects_without_removing_old_release(self):
        from types import SimpleNamespace
        from workflow.live.paths import read_json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'song';ai=song/'covers/ai';ai.mkdir(parents=True)
            write_json(ai/'masters.json',[{'file':'old.png','review_hash':'old'}])
            write_json(root/'queue.json',[{'slug':'show','name':'song'}])
            write_json(root/'fibo-cover-plan.json',{'song':{'source_time':10}})
            stage=root/'stage';stage.mkdir();write_json(stage/'stage.json',{'slug':'show','name':'song'})
            c=SimpleNamespace(slug='show',dir=root,item=lambda key:{'name':'song'},song_dir=lambda it:song)
            def generate(*args,**kwargs):
                self.assertTrue(kwargs['replace_existing'])
                self.assertEqual(read_json(ai/'masters.json')[0]['file'],'old.png')
                return {'stage':str(stage)}
            with patch('workflow.fibo_dual_queue.Concert',return_value=c), \
                 patch('workflow.fibo_dual_queue.reviewed_revision',return_value=({'file':'old.png','review_hash':'old'},[])), \
                 patch('workflow.fibo_reference.reselect') as reselect, \
                 patch('workflow.fibo_dual_queue.reusable_stage') as old_stage, \
                 patch('workflow.fibo_dual_queue.generate_one',side_effect=generate) as render, \
                 patch('workflow.cover_visual_review.review',return_value={'status':'rejected','review_hash':digest(stage/'stage.json')}), \
                 patch('workflow.fibo_dual_queue.publish') as publish:
                run(root/'queue.json',root/'model',auto_review=True,replace_existing=True)
            reselect.assert_called_once_with(c, {'name':'song'}, excluded_times=[10])
            render.assert_called_once();old_stage.assert_not_called();publish.assert_not_called()
            self.assertEqual(read_json(ai/'masters.json')[0]['file'],'old.png')
            self.assertEqual(read_json(root/'dual-cover-status.json')['show/song']['status'],'visual_rejected')

    def test_resume_verifies_existing_release_without_regenerating(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);song=root/'song';song.mkdir();stage=root/'stage';stage.mkdir()
            write_json(stage/'stage.json',{'slug':'show','name':'song'})
            version=digest(stage/'stage.json')
            write_json(root/'queue.json',[{'slug':'show','name':'song'}])
            write_json(root/'visual-review.json',{'show/song':{'status':'approved','review_hash':version,'stage':str(stage)}})
            c=SimpleNamespace(slug='show',dir=root,item=lambda key:{'name':'song'},song_dir=lambda it:song)
            with patch('workflow.fibo_dual_queue.Concert',return_value=c), \
                 patch('workflow.fibo_dual_queue.reviewed_revision',return_value=({'file':'master.png','review_hash':version},[])), \
                 patch('workflow.fibo_dual_queue.release_reviewed',return_value=True) as verify, \
                 patch('workflow.fibo_dual_queue.generate_one') as generate:
                run(root/'queue.json',root/'model')
            verify.assert_called_once();generate.assert_not_called()
            self.assertEqual(__import__('json').loads((root/'dual-cover-status.json').read_text())['show/song']['status'],'released_verified')

    def test_visual_review_requires_every_explicit_check(self):
        good = {'pass':True, 'checks':dict.fromkeys(CHECKS, True), 'defects':[]}
        self.assertTrue(accepted(good))
        for key in CHECKS:
            bad = {**good, 'checks':{**good['checks'], key:False}}
            self.assertFalse(accepted(bad))
        self.assertFalse(accepted({**good, 'pass':'true'}))
        self.assertFalse(accepted({**good, 'defects':['新增背景人脸']}))

    def test_rejected_stage_stays_rejected_after_global_record_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp);stage = base/'show/song/version/attempt-001/cover-review'
            stage.mkdir(parents=True);(stage/'art.png').write_bytes(b'image')
            write_json(stage/'stage.json', {'name':'song'})
            write_json(stage/'visual-review.json', {'status':'rejected'})
            self.assertIsNone(reusable_stage(base, 'show', 'song', {}))
            write_json(stage/'visual-review.json', {'status':'approved'})
            self.assertEqual(reusable_stage(base, 'show', 'song', {}), stage)

    def test_modified_revision_cannot_use_previous_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp);write_json(d/'stage.json', {'slug':'show','name':'song'})
            approved = {'show/song':{'status':'approved', 'review_hash':digest(d/'stage.json')}}
            write_json(d/'stage.json', {'slug':'show','name':'song','changed':True})
            with patch('workflow.fibo_dual_queue.publish') as publish:
                self.assertFalse(release_reviewed(d,approved,'http://localhost'))
                publish.assert_not_called()
