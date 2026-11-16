"""Drain current workers, then repair rejected covers in the same two-Mac queue."""
from pathlib import Path
import fcntl,sys,time
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from workflow.fibo_dual_queue import run
from workflow.live.paths import Concert,read_json,write_json
from workflow.ai_cover import reviewed_revision
b=ROOT/'work/three-concert-subtitles-20261114'
with (b/'cover-followup.lock').open('a') as own:
 fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
 with (b/'dual-cover.lock').open('a') as current:
  fcntl.flock(current,fcntl.LOCK_EX)
 # The song audit still has its own bounded serial queue; do not duplicate it.
 with (b/'killah-recovery.lock').open('a') as audio:
  fcntl.flock(audio,fcntl.LOCK_EX)
 for attempt in range(2):
  if (b/'PAUSED').exists():break
  missing=[r for r in read_json(b/'dual-cover-queue.json') if not reviewed_revision(Concert(r['slug']).song_dir(Concert(r['slug']).item(r['name']))/'covers/ai')]
  if not missing:break
  print('REPAIR_PASS',attempt+1,'remaining',len(missing),flush=True)
  run(b/'dual-cover-queue.json',Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4'),b/'remote-fibo.json',auto_review=True,reselect_rejected=True)
 missing=[r for r in read_json(b/'dual-cover-queue.json') if not reviewed_revision(Concert(r['slug']).song_dir(Concert(r['slug']).item(r['name']))/'covers/ai')]
 write_json(b/'cover-unresolved.json',missing)
 print('FOLLOWUP_DONE remaining',len(missing),flush=True)
