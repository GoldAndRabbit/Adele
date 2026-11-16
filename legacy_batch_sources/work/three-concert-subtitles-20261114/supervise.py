"""Bounded recovery of unfinished jobs, without duplicating active workers."""
import fcntl,psutil,subprocess,time,json
from pathlib import Path
root=Path('/Users/gold/repos/adele');base=root/'work/three-concert-subtitles-20261114'
with (base/'supervisor.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for attempt in range(5):
  while True:
   alive=[]
   for p in psutil.process_iter(['cmdline']):
    args=p.info['cmdline'] or []
    if any(a.endswith('three-concert-subtitles-20261114/run.py') for a in args):alive.append(p)
   if not alive:break
   time.sleep(10)
  if (base/'PAUSED').exists():break
  status=json.loads((base/'status.json').read_text())
  retry=[k for k,v in status.items() if v.get('status')=='failed' and 'No supported performance boundary' not in v.get('error','')]
  if not retry:break
  with (base/'run.log').open('a') as out:
   proc=subprocess.Popen([str(root/'.venv/bin/python'),'-u',str(base/'run.py')],cwd=root,stdout=out,stderr=subprocess.STDOUT)
   print('RECOVER',attempt+1,proc.pid,'failed_jobs',len(retry),flush=True);proc.wait()
  time.sleep(15)
