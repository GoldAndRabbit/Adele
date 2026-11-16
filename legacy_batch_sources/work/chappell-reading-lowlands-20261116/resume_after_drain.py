"""Resume the scoped queue only after its current songs and children drain."""
import fcntl,subprocess,sys,time
from pathlib import Path
import psutil
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from workflow.live.paths import read_json,write_json
BASE=Path(__file__).resolve().parent
OLD=int(sys.argv[1]);MARKER='Drain first songs safely before applying verified location refinements.\n'
SLUGS=('chappell_reading_2025','chappell_lowlands_2025')
with (BASE/'resume.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 (BASE/'resume.pid').write_text(str(__import__('os').getpid()))
 while True:
  active=[]
  for proc in psutil.process_iter(['cmdline']):
   try:
    args=proc.info['cmdline'] or [];joined=' '.join(args)
    if proc.pid==OLD or (any(slug in joined for slug in SLUGS) and any(
        part in args for part in ('workflow.song.run',str(ROOT/'workflow/separate_roformer.py'),'ffmpeg','/opt/homebrew/bin/ffmpeg'))):
     if proc.status()!=psutil.STATUS_ZOMBIE:active.append(proc.pid)
   except (psutil.NoSuchProcess,psutil.AccessDenied):pass
  if not active:break
  time.sleep(3)
 marker=BASE/'PAUSED'
 if marker.exists():
  if marker.read_text()!=MARKER:
   print('Preserving a later user pause; no restart',flush=True);raise SystemExit(0)
  marker.unlink()
 for attempt in range(2):
  if (BASE/'PAUSED').exists():break
  with (BASE/'pipeline.log').open('a',buffering=1) as log:
   print('RESUME_PASS',attempt+1,flush=True)
   proc=subprocess.Popen([str(ROOT/'.venv/bin/python'),'-u',str(BASE/'pipeline.py')],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
   proc.wait()
  status=read_json(BASE/'status.json',{})
  retry=[k for k,r in status.items() if not k.endswith('/_concert') and r.get('status')=='needs_repair']
  write_json(BASE/'continuation.json',{'pass':attempt+1,'return_code':proc.returncode,'pending_repairs':retry})
  if not retry:break
