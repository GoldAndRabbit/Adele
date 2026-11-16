"""Prepare references, then serialize heavy work after existing Eminem queue."""
import os,subprocess,time,json,fcntl
from pathlib import Path
ROOT=Path('/Users/gold/repos/adele');B=ROOT/'posts/additional_batch_20261030';PY=ROOT/'.venv/bin/python'
lock=(B/'supervisor.lock').open('w')
try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
except BlockingIOError:raise SystemExit('Supervisor already active')
subprocess.run([str(PY),'-u',str(B/'run.py'),'--references-only'],cwd=ROOT,check=True)
print('References prepared; waiting for existing Eminem queue PID 66663.',flush=True)
while True:
 r=subprocess.run(['ps','-p','66663','-o','command='],capture_output=True,text=True)
 if r.returncode or 'eminem_batch_20261030' not in r.stdout:break
 time.sleep(20)
print('Starting additional 12-video queue.',flush=True)
subprocess.run([str(PY),'-u',str(B/'run.py'),'--remaining-only'],cwd=ROOT,check=True)
