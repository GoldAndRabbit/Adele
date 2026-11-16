import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from workflow.live.paths import write_json
from workflow.preview import enable_browser

class PreviewBatchTest(unittest.TestCase):


    def test_selected_source_policy_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);clip=root/'source.mp4';clip.write_bytes(b'cached')
            source=(root/'original.ts').resolve();source.write_bytes(b'original')
            selection={'source':str(source),'kind':'ts','slice':[10,20],'directory':str(root)}
            policy={'source':str(source),'songs':{'song':selection}}
            write_json(root/'vertical_source.json',policy)
            write_json(root/'source.json',{'source':str(source),'mtime':source.stat().st_mtime_ns,'slice':[10,20]})
            c=SimpleNamespace(dir=root,song_dir=lambda _:root)
            with patch('workflow.preview.original_source',return_value=source),patch('workflow.portrait_browser.preview_data'),patch('workflow.browser_library.prepare_preview_crop'),patch('workflow.browser_library.prepare_browser') as prepare:
                enable_browser(c,{'name':'song'})
                prepare.assert_not_called()
            from workflow.live.paths import read_json
            self.assertEqual(read_json(root/'vertical_source.json'),policy)

    def test_audio_decoder_change_invalidates_cached_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);source=(root/'original.mkv').resolve();source.write_bytes(b'original')
            (root/'source.mp4').write_bytes(b'cached')
            selection={'source':str(source),'kind':'original','slice':[10,20],
                       'directory':str(root),'audio_decoder':'eac3_at'}
            write_json(root/'vertical_source.json',{'source':str(source),'songs':{'song':selection}})
            marker={'source':str(source),'mtime':source.stat().st_mtime_ns,'slice':[10,20]}
            write_json(root/'source.json',marker)
            c=SimpleNamespace(dir=root,song_dir=lambda _:root)
            with patch('workflow.preview.original_source',return_value=source),patch('workflow.portrait_browser.preview_data'),patch('workflow.browser_library.prepare_preview_crop'),patch('workflow.browser_library.prepare_browser') as prepare:
                enable_browser(c,{'name':'song'})
                prepare.assert_called_once()
                prepare.reset_mock()
                write_json(root/'source.json',{**marker,'audio_decoder':'eac3_at'})
                enable_browser(c,{'name':'song'})
                prepare.assert_not_called()
