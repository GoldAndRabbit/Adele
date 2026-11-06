import tempfile,unittest,threading,json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
from workflow import dual_render
from workflow.live.paths import Concert
from workflow.song.render import DEFAULT_ENCODER,ENCODERS

class DualDeliveryTest(unittest.TestCase):
 def test_song_configuration_and_trim_are_not_dark_horse_constants(self):
  c=Concert('grammys_2014')
  for name,duration in [('01_drunk_in_love',304),('02_royals',238.9)]:
   with tempfile.TemporaryDirectory() as folder:
    dual_render.configure(c,c.item(name),folder)
    self.assertEqual(dual_render.D.name,name)
    self.assertAlmostEqual(dual_render.START+dual_render.DURATION,duration,places=3)
    with patch.object(dual_render,'draw_portrait_header') as draw:
     dual_render.assets()
     self.assertEqual(draw.call_args.args[1],c.item(name)['title'])
     self.assertNotEqual(draw.call_args.kwargs['song_zh'],'黑马')
 def test_final_encoder_is_existing_apple_default(self):
  self.assertEqual(dual_render.DEFAULT_ENCODER,DEFAULT_ENCODER)
  self.assertIs(dual_render.ENCODERS,ENCODERS)
  self.assertEqual(ENCODERS[DEFAULT_ENCODER][1],'hevc_videotoolbox')

class ParallelDeliveryTest(unittest.TestCase):
 def test_both_encodes_start_together_and_remain_pending(self):
  from workflow.dual_platform import render_pair
  barrier=threading.Barrier(2);seen=[]
  def fake(kind,commit,timing_metadata):
   self.assertFalse(commit);seen.append(timing_metadata)
   barrier.wait(timeout=3)
   return Path(kind+'.pending.mp4')
  with patch('workflow.dual_platform.render.render',side_effect=fake):
   result=render_pair()
  self.assertEqual([x[0] for x in result],['douyin','bilibili'])
  self.assertEqual(seen[0]['parallel_group'],seen[1]['parallel_group'])
 def test_parallel_timing_writes_preserve_both_results(self):
  with tempfile.TemporaryDirectory() as folder, patch.object(dual_render,'W',Path(folder),create=True):
   barrier=threading.Barrier(2)
   def write(i):
    barrier.wait(timeout=3);dual_render.timing(str(i),1)
   with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(write,[1,2]))
   self.assertEqual({r['stage'] for r in json.loads((Path(folder)/'timings.json').read_text())},{'1','2'})
 def test_failed_branch_prevents_pair_success(self):
  from workflow.dual_platform import render_pair
  def fake(kind,**kw):
   if kind=='landscape':raise RuntimeError('encode failed')
   return Path('portrait.pending.mp4')
  with patch('workflow.dual_platform.render.render',side_effect=fake):
   with self.assertRaises(RuntimeError):render_pair()

if __name__=='__main__':unittest.main()
