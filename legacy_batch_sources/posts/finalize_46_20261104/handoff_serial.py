import os,signal,subprocess,sys,time,json,fcntl
from pathlib import Path
R=Path(__file__).resolve().parents[2];B=Path(__file__).resolve().parent;sys.path.insert(0,str(R))
from serial_submit import submit_one,read
lock=(B/'handoff.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
old=int((B/'pid').read_text())
def ps(*a):return subprocess.run(['ps',*a],text=True,capture_output=True).stdout.strip()
assert 'finalize_46_20261104/run.py' in ps('-p',str(old),'-o','command=') and 'T' in ps('-p',str(old),'-o','stat=')
try:
 for row in read(B/'status.json')['items']:
  if row['status']!='waiting_for_metadata':continue
  d=Path(row['directory'])
  if (d/'post'/f'{d.name} 4K60FPS Sub-WaterMark.mp4').is_file():
   print('drain',d.name,flush=True);stage,v=submit_one(d,B);print(stage,v,flush=True)
   if stage=='awaiting_platform_check':break
finally:
 # The old renderer retains its current interpolation worker until that worker exits.
 while any('Z' not in line for line in ps('-o','stat=','-P',str(old)).splitlines()):time.sleep(3)
 os.kill(old,signal.SIGTERM);os.kill(old,signal.SIGCONT)
 while ps('-p',str(old),'-o','pid='):time.sleep(.2)
 with (B/'run.log').open('ab') as f:q=subprocess.Popen([sys.executable,'-u',str(B/'run.py')],stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
 (B/'pid').write_text(str(q.pid));print('new runner',q.pid,flush=True)
