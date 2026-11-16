from pathlib import Path
import fcntl,json,subprocess,sys
b=Path(__file__).resolve().parent
name=sys.argv[1];prefix='resume_download_'+name
with (b/(prefix+'_followup.lock')).open('a') as guard:
 fcntl.flock(guard,fcntl.LOCK_EX|fcntl.LOCK_NB)
 with (b/(prefix+'.lock')).open('a') as original:
  fcntl.flock(original,fcntl.LOCK_EX)
  plan=json.loads((b/(prefix+'.json')).read_text())
  missing=[j for j in plan if not (b.parents[1]/j['dir']/'source.mp4').is_file()]
  if missing:
   key=prefix+'_retry2'
   (b/(key+'.json')).write_text(json.dumps(missing,indent=2))
   subprocess.run([sys.executable,'-u',str(b/'restore.py'),key],cwd=b.parents[1],check=True)
