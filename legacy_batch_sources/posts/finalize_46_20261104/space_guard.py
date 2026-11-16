from pathlib import Path
import os,json,time,shutil,signal,subprocess,fcntl
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent
lock=(B/'guard.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
stopped=set()
while True:
 free=shutil.disk_usage(R).free
 lines=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True).splitlines();procs={}
 for line in lines:
  parts=line.strip().split(None,2)
  if len(parts)==3:procs[int(parts[0])]=(int(parts[1]),parts[2])
 root=int((B/'pid').read_text());desc={root}
 for _ in range(20):
  add={pid for pid,(parent,cmd) in procs.items() if parent in desc};old=len(desc);desc|=add
  if len(desc)==old:break
 targets={pid for pid in desc if pid in procs and any(t in procs[pid][1].lower() for t in ['rife','ffmpeg'])}
 for pid in targets:
  try:
   if free<8*2**30 and pid not in stopped:os.kill(pid,signal.SIGSTOP);stopped.add(pid)
   elif free>16*2**30 and pid in stopped:os.kill(pid,signal.SIGCONT);stopped.remove(pid)
  except ProcessLookupError:stopped.discard(pid)
 stopped &= set(procs)
 (B/'space_guard_status.json').write_text(json.dumps({'pid':os.getpid(),'time':time.time(),'free_bytes':free,'paused_pids':sorted(stopped)}))
 time.sleep(10)
