import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from workflow.cover_pool_quality import assess
class CoverQualityTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.path=Path(self.tmp.name)/'frame.jpg';Image.new('RGB',(100,80),'#783344').save(self.path)
  self.good={'id':1,'face_visible':True,'real_singer':True,'center_x':.5,'subject_large':True,'monochrome':False,'awkward_angle':False,'edge_clipped':False,'clear':True,'score':8,'why':'正面居中'}
 def run_case(self,**changes):
  with patch('workflow.cover_pool_quality.vision_json',return_value={'items':[{**self.good,**changes}]}):
   return assess([(self.path,'digest')])[self.path.name]['approved']
 def test_centered_front_color_passes(self):self.assertTrue(self.run_case())
 def test_hard_exclusions_override_high_score(self):
  for issue in [{'face_visible':False},{'center_x':.8},{'real_singer':False},{'monochrome':True},{'awkward_angle':True},{'edge_clipped':True}]:
   with self.subTest(issue=issue):self.assertFalse(self.run_case(**issue,score=10))
 def test_missing_answer_fails_closed(self):
  with patch('workflow.cover_pool_quality.vision_json',return_value={'items':[]}):self.assertFalse(assess([(self.path,'digest')])[self.path.name]['approved'])
 def test_grayscale_rejected_without_model(self):
  Image.new('RGB',(100,80),'gray').save(self.path)
  with patch('workflow.cover_pool_quality.vision_json') as call:
   self.assertFalse(assess([(self.path,'digest')])[self.path.name]['approved']);call.assert_not_called()
