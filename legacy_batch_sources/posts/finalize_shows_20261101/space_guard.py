import os,time,signal,subprocess,shutil,json
from pathlib import Path
b=Path(__file__).parent;paused=set()
while True:
 free=shutil.disk_usage('/Users/gold/repos/adele').free/1024**3
 lines=subprocess.run(['pgrep','-f','rife-ncnn-vulkan -i /Users/gold/repos/adele/posts/.local-render/'],capture_output=True,text=True).stdout.split()
 for x in lines:
  pid=int(x)
  if free<8 and pid not in paused:
   os.kill(pid,signal.SIGSTOP);paused.add(pid)
 for pid in list(paused):
  try:
   os.kill(pid,0)
   if free>16:os.kill(pid,signal.SIGCONT);paused.remove(pid)
  except ProcessLookupError:paused.remove(pid)
 (b/'space_guard_status.json').write_text(json.dumps({'free_gib':free,'paused_rife':list(paused),'time':time.time()}))
 time.sleep(5)
