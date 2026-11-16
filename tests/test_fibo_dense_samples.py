from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from workflow.fibo_dense_samples import refine
from workflow.live.paths import read_json,write_json


class DenseSourceTests(unittest.TestCase):
    def test_absolute_times_use_selected_frame_pts_not_jpeg_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);concert_dir=root/'concert';concert_dir.mkdir()
            browser=root/'browser';browser.mkdir();(browser/'source.mp4').write_bytes(b'fixture')
            folder=root/'show/selection/song';folder.mkdir(parents=True)
            write_json(concert_dir/'vertical_source.json',{'songs':{'song':{'directory':str(browser),'slice':[100,130]}}})
            concert=SimpleNamespace(slug='show',dir=concert_dir)
            def extract(args,**kwargs):
                for i in range(8):Image.new('RGB',(1280,720),'blue').save(args[-1]%(i+1))
                return SimpleNamespace(stderr='\n'.join(f'n: {i} pts: {i*60000} pts_time:{i*2}' for i in range(8)))
            face=dict(width=.2,left_eye=.25,right_eye=.25,check_closed=False)
            with patch('workflow.fibo_dense_samples.BASE',root), \
                 patch('workflow.fibo_dense_samples.sample'), \
                 patch('workflow.fibo_dense_samples.subprocess.run',side_effect=extract), \
                 patch('workflow.fibo_dense_samples.inspect_eyes',return_value=[face]):
                self.assertEqual(refine(concert,{'name':'song'}),4)
            self.assertEqual([r[1] for r in read_json(folder/'times.json')],[102,106,110,114])
