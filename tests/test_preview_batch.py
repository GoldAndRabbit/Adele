import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from workflow.live.paths import write_json
from workflow.preview_batch import one_cover, enable_browser

class PreviewBatchTest(unittest.TestCase):
    def test_existing_master_never_requests_another(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);ai=root/'covers/ai';ai.mkdir(parents=True)
            (ai/'master.png').write_bytes(b'existing')
            write_json(ai/'masters.json',[{'file':'master.png'}])
            c=SimpleNamespace(song_dir=lambda _:root)
            with patch('workflow.seedream_cover.generate_trial') as generate:
                self.assertEqual(one_cover(c,{}),'reused');generate.assert_not_called()

    def test_prior_failed_attempt_is_not_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);run=root/'covers/ai/runs/abc';run.mkdir(parents=True)
            write_json(run/'candidate-1.json',{'status':'failed'})
            c=SimpleNamespace(song_dir=lambda _:root)
            with patch('workflow.seedream_cover.generate_trial') as generate:
                self.assertEqual(one_cover(c,{}),'prior_attempt_needs_review');generate.assert_not_called()

    def test_selected_source_policy_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);clip=root/'source.mp4';clip.write_bytes(b'cached')
            source=root/'original.ts';source.write_bytes(b'original')
            selection={'source':str(source),'kind':'ts','slice':[10,20],'directory':str(root)}
            policy={'source':str(source),'songs':{'song':selection}}
            write_json(root/'vertical_source.json',policy)
            write_json(root/'source.json',{'source':str(source),'mtime':source.stat().st_mtime_ns,'slice':[10,20]})
            c=SimpleNamespace(dir=root,song_dir=lambda _:root)
            with patch('workflow.preview_batch.original_source',return_value=source),patch('workflow.portrait_browser.preview_data'),patch('workflow.browser_library.prepare_browser') as prepare:
                enable_browser(c,{'name':'song'})
                prepare.assert_not_called()
            from workflow.live.paths import read_json
            self.assertEqual(read_json(root/'vertical_source.json'),policy)
