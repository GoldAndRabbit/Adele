"""Prepare original-frame comparisons for the completed Chappell subtitle batch."""
import sys,fcntl
from pathlib import Path
sys.path.insert(0,'/Users/gold/repos/adele')
from workflow.fibo_library import sample
from workflow.live.paths import Concert,read_json,write_json
base=Path(__file__).resolve().parent
with (base/'cover-preparation.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 c=Concert('chappell_lolla_brasil_2026');status={}
 for it in c.song_items():
  try:
   print('SAMPLING',c.slug,it['name'],flush=True);sample(c,it);status[it['name']]='frames_ready_for_selection'
  except Exception as exc:status[it['name']]='failed: '+str(exc)
  write_json(base/'cover-preparation-status.json',status)
 print('REFERENCE_SAMPLING_DONE',flush=True)
