"""Reload the coordinator only between local subprocesses; retain all disk results."""
import psutil,time,subprocess
from pathlib import Path
root=Path('/Users/gold/repos/adele');base=root/'work/three-concert-subtitles-20261114'
old=psutil.Process(41418)
while old.is_running():
 old.suspend()
 try:
  live=[p for p in old.children(recursive=True) if p.is_running()]
  if live:
   old.resume();time.sleep(2);continue
  old.terminate();old.resume();old.wait(timeout=20);break
 except Exception:
  if old.is_running():old.resume()
  raise
with (base/'run.log').open('a') as log:
 p=subprocess.Popen([str(root/'.venv/bin/python'),'-u',str(base/'run.py')],cwd=root,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
print('resumed',p.pid,flush=True)
