"""Render only the ten checked broadcast performances, leaving guest interaction out."""
import time
import subprocess
import traceback
from pathlib import Path
import pysubs2
from PIL import Image
from workflow.live.paths import *
from workflow.storage import archive_root
from workflow.song.watermark import ensure_song
from workflow.vertical_workflow import prepare
from workflow.vertical_cover import header_labels
from workflow.portrait_validation import preview_problem
c=Concert('an_audience_with_adele_2021');base=ROOT/'work/vertical-batch'
verified=read_json(c.segments)['items']
todo={it['name']:it for it in c.song_items()}
assert len(todo)==10 and len(verified)==11 and (c.dir/'inspection/分割核验.csv').is_file() and (c.dir/'inspection/首尾分割复核.mp4').is_file()
from concurrent.futures import ThreadPoolExecutor

def process(entry):
 n,it=entry
 d=c.song_dir(it);folder=d/'vertical'
 captions=d/'subs/lyrics_poetic.ass'
 while not captions.is_file() or not (d/'watermark.json').is_file() or (base/'PAUSED').exists():
  time.sleep(10)
 status=base/'status'/(c.slug+'--'+n+'.json')
 try:
  span=read_json(d/'song.json')['slice'];a,b=span
  assert (a,b)==next((r['start'],r['end']) for r in verified if r['name']==n)
  assert any(e.style=='Default' and e.end>e.start for e in pysubs2.load(str(captions)))
  if not folder.exists():
   dest=archive_root()/'vertical-reviews'/c.slug/n;dest.mkdir(parents=True,exist_ok=True);folder.symlink_to(dest,target_is_directory=True)
  write_json(status,dict(title=it['title'],status='running'))
  ensure_song(c.slug,n);prepare(c,it)
  f=folder/'full.mp4';ss=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-of','json',str(f)]))['streams'];v=next(x for x in ss if x['codec_type']=='video')
  assert abs(float(v['duration'])-b+a)<.15 and (v['width'],v['height'],v['avg_frame_rate'])==(1080,1920,'30/1') and any(x['codec_type']=='audio' for x in ss)
  assert not preview_problem(c,it,f)
  rows=read_json(folder/'candidates.json');assert len({x['pool_frame'] for x in rows})==18
  for row in rows:
   with Image.open(folder/row['file']) as im:assert im.size==(1080,1920);im.verify()
  write_json(status,dict(title=it['title'],status='ready',header=header_labels(c,it),cover_source='pool'))
  print('READY',n,flush=True)
 except Exception:
  write_json(status,dict(title=it['title'],status='failed',error=traceback.format_exc()));print('FAILED',n,traceback.format_exc(),flush=True)

with ThreadPoolExecutor(max_workers=2) as pool:
 list(pool.map(process,todo.items()))
