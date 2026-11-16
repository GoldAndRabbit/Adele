"""Drain both owned workers before reloading fixes; never orphan an encode."""
from pathlib import Path
import subprocess
import time
import fcntl
import os
import signal
from workflow.live.paths import ROOT,read_json,write_json
from workflow.priority_delivery import existing_workers

BASE=Path(__file__).parent
TOKEN='Internal audio-clock/cache fix reload; resume after both current songs finish.\n'

if __name__=='__main__':
    with (BASE/'reload.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        pause=BASE/'PAUSED'
        if pause.exists():raise SystemExit('Existing pause belongs to the user; leave untouched')
        pause.write_text(TOKEN)
        pid=int((BASE/'scheduler.pid').read_text())
        for _ in range(1800):
            if pause.read_text()!=TOKEN:raise SystemExit('Pause changed externally; leave paused')
            try:os.kill(pid,0)
            except ProcessLookupError:break
            time.sleep(2)
        else:raise SystemExit('Drain timeout; leave paused and preserve workers')
        if existing_workers():raise SystemExit('A worker still exists; no second scheduler launched')
        pause.unlink()
        with (BASE/'scheduler.log').open('a') as log:
            child=subprocess.Popen(['caffeinate','-is',str(ROOT/'.venv/bin/python'),'-u','-m',
                'workflow.priority_delivery','--batch',str(BASE)],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,
                start_new_session=True)
        (BASE/'scheduler_launcher.pid').write_text(str(child.pid))
        (BASE/'scheduler.pid').write_text(str(child.pid))
        print('Safely reloaded dispatcher',child.pid,flush=True)
