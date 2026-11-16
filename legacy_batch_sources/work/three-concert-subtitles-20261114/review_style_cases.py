from pathlib import Path
import sys,fcntl
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from workflow.live.paths import read_json,write_json
from workflow.cover_visual_review import review
from workflow.fibo_dual_queue import release_reviewed
b=ROOT/'work/three-concert-subtitles-20261114'
for name in ['01_bloody_mary','02_abracadabra','04_schei_e','10_alejandro','11_the_beast']:
 key='gaga_coachella_2025/'+name;r=read_json(b/'visual-review.json')[key];d=Path(r['stage']);record=review(d)
 with (b/'.visual-review.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);rows=read_json(b/'visual-review.json');rows[key]=record;write_json(b/'visual-review.json',rows)
 ok=release_reviewed(d,rows,'http://127.0.0.1:8160');print('STYLE_REVIEW',name,ok,record['result'],flush=True)
