from pathlib import Path
from runpy import run_path
from workflow.live.paths import Concert,read_json,write_json
trim=run_path('/tmp/trim-seven-reviews.py')['trim']
c=Concert('dualipa_mexico2025')
cuts={2:25,7:58,8:55,9:33,10:54,11:12,13:22,14:121,15:26,16:39,17:25,18:122,19:67,20:23,21:6,22:22}
path=Path(__file__).with_name('mexico-trims.json')
if not path.exists():
 jobs=[]
 for it in c.song_items():
  if it['idx'] in cuts:
   key=it['name'];a,b=c.load('song' if False else 'segments')['items'][it['idx']-1]['start'],read_json(c.song_dir(it)/'song.json')['slice'][1]
   jobs.append([c.slug,key,a,cuts[it['idx']]])
 assert len(jobs)==16
 write_json(path,jobs)
for row in read_json(path):trim(row)
