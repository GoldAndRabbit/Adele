from pathlib import Path
import subprocess as sp,sys,time,json,fcntl
wd=Path('work/grammy-ts60')
lock=(wd/'batch.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
songs=json.loads((wd/'sync.json').read_text())
# The first Royals sample already has its own worker.
order=[n for n in songs if n!='02_royals']
order.sort(key=lambda n:any(b-a<=2 for a,b in zip(songs[n]['bad'],songs[n]['bad'][1:])))
for name in order:
    if (wd/'PAUSED').exists():break
    with (wd/(name+'.log')).open('a') as log:
        print('START',name,flush=True)
        code=sp.call([sys.executable,wd/'render.py',name],stdout=log,stderr=sp.STDOUT)
        print('READY' if not code else 'ERROR',name,code,flush=True)
