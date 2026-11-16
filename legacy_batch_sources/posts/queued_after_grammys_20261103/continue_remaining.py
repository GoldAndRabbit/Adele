import json,time,subprocess,fcntl,os
from pathlib import Path
R=Path('/Users/gold/repos/adele');B=Path(__file__).resolve().parent
lock=(B/'continue_remaining.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
s={'pid':os.getpid(),'status':'waiting_download','jobs':{}}
def save(): (B/'continue_remaining_status.json').write_text(json.dumps(s,ensure_ascii=False,indent=2))
remaining=['queued_20261103_e_d9dkp134e','queued_20261103_yzo50fzagaq'];deadline=time.monotonic()+1800
while remaining and time.monotonic()<deadline:
 for n in list(remaining):
  p=R/'posts'/n
  if not (p/'source.mp4').exists():continue
  try:
   v=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(p/'source.mp4')],text=True,timeout=30));assert {'audio','video'}<={x['codec_type'] for x in v['streams']}
   (p/'source_validation.json').write_text(json.dumps(v,indent=2));m=json.loads((p/'source.info.json').read_text());(p/'meta.json').write_text(json.dumps({k:m.get(k) for k in ('title','channel','duration','language','track','artist','upload_date','description','tags','webpage_url')},ensure_ascii=False,indent=2))
   # Wait for the existing preparation runner; do not overlap queue ownership.
   q=(B/'queue.lock').open('a');fcntl.flock(q,fcntl.LOCK_EX);fcntl.flock(q,fcntl.LOCK_UN);q.close()
   s['status']='preparing';s['current']=n;save()
   with (B/(n+'_continuation.log')).open('a') as f:r=subprocess.run([str(R/'.venv/bin/python'),'-u',str(B/'run.py'),'--only',n],cwd=R,stdout=f,stderr=subprocess.STDOUT)
   s['jobs'][n]={'runner_exit':r.returncode};remaining.remove(n);save()
  except Exception as e:s['jobs'][n]={'error':str(e)};save()
 if remaining:time.sleep(15)
s['status']='finished' if not remaining else 'downloads_still_missing';s['remaining']=remaining;save()
