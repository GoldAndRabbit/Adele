import tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
from workflow.live.paths import write_json,read_json
from workflow.portrait_pool import pool_candidates,apply_pool_assignment
from datetime import datetime
from workflow.vertical_post import SHANGHAI
class PoolSelectionTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.root=Path(self.tmp.name);self.d=self.root/'song';self.d.mkdir();(self.root/'cover_pool').mkdir()
  self.c=SimpleNamespace(dir=self.root,song_dir=lambda it:self.d)
  self.it={'name':'song','title':'Hello'}
  self.frame='frame_half_01_10.0s.jpg';Image.new('RGB',(320,180),'blue').save(self.root/'cover_pool'/self.frame)
  write_json(self.d/'post_draft.json',{'song':{'title_song':'Hello'}})
  self.rows=[{'file':self.frame,'t':10.,'marked':True}]
  self.addCleanup(patch.stopall)
  patch('workflow.portrait_pool.frames',return_value=self.rows).start()
  patch('workflow.portrait_pool.header_labels',return_value={'en':'Adele','zh':'阿黛尔','event':'演唱会'}).start()
  patch('workflow.portrait_pool.cover_image',return_value=Image.new('RGB',(1080,1440),'purple')).start()
 def test_no_preselection_even_with_old_assignment(self):
  write_json(self.root/'cover_pool/assigned.json',{'songs':{'song':{'frame':self.frame}}})
  self.assertEqual(pool_candidates(self.c,self.it),[])
  self.assertFalse(list((self.d/'vertical').glob('*.jpg')))
 def test_explicit_frame_only(self):
  rows=pool_candidates(self.c,self.it,assigned=self.frame)
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['pool_frame'],self.frame)
 def test_failed_pair_restores_manifest(self):
  (self.d/'vertical').mkdir();write_json(self.d/'vertical/candidates.json',[])
  with patch('workflow.vertical_post.replace_cover_selection',side_effect=OSError('fixture')):
   with self.assertRaises(OSError):apply_pool_assignment(self.c,self.it,self.frame,datetime.now(SHANGHAI))
  self.assertEqual(read_json(self.d/'vertical/candidates.json'),[])
