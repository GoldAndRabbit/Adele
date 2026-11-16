from pathlib import Path
import json,subprocess,shutil,time,os,fcntl
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent
lock=(B/'resume.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def save(stage,**kw):
 (B/'resume_status.json').write_text(json.dumps(dict(pid=os.getpid(),stage=stage,**kw),ensure_ascii=False,indent=2))
for n in ['pink_just_give_reason_mv_opqfflbmepi_redo','pink_just_give_reason_live2013_b5qyglhl7qu_redo']:
 while shutil.disk_usage(R).free<35*2**30:
  save('waiting_for_space',name=n,free_gib=shutil.disk_usage(R).free/2**30)
  state=json.loads((B/'status.json').read_text())
  if state['status']=='finished':
   save('insufficient_space_after_archive',name=n);raise SystemExit(1)
  time.sleep(30)
 save('rendering',name=n)
 with (B/(n+'.log')).open('a') as f:
  p=subprocess.run([str(R/'.venv/bin/python'),'-u','-m','workflow.song.render','post:'+n,'--enc','hevc_hw'],cwd=R,stdout=f,stderr=subprocess.STDOUT)
 out=list((R/'posts'/n/'post').glob('*Sub-WaterMark.mp4'))
 if p.returncode or not out:
  save('render_failed',name=n);raise SystemExit(1)
save('complete')
