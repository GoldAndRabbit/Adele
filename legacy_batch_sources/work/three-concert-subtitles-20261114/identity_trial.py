"""Same-frame facial detail trial, using standard FIBO and release functions."""
from pathlib import Path
import sys,fcntl
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from workflow.live.paths import Concert,read_json,write_json
from workflow.fibo_concert import generate_one
from workflow.cover_visual_review import review
from workflow.fibo_dual_queue import release_reviewed
b=ROOT/'work/three-concert-subtitles-20261114';c=Concert('gaga_coachella_2025');it=c.item('01_bloody_mary');ai=c.song_dir(it)/'covers/ai'
with (ai/'.generation.lock').open('a') as job:
 fcntl.flock(job,fcntl.LOCK_EX)
 spec=read_json(c.dir/'fibo-cover-plan.json')[it['name']]
 r=generate_one(c,it,spec,ROOT/'work/fibo-batch'/c.slug,Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4'),worker=b/'remote-fibo.json')
 d=Path(r['stage']);record=review(d)
 with (b/'.visual-review.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX);allrows=read_json(b/'visual-review.json');allrows[c.slug+'/'+it['name']]=record;write_json(b/'visual-review.json',allrows)
 ok=release_reviewed(d,allrows,'http://127.0.0.1:8160');print('IDENTITY_TRIAL_RELEASED',ok,record,flush=True)
