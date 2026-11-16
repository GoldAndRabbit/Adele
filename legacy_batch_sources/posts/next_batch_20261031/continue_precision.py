from pathlib import Path
import json,subprocess,time,os,fcntl
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent;P=R/'.venv/bin/python'
f=(B/'precision.lock').open('a');fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
s={'pid':os.getpid(),'status':'waiting_for_audio_and_references','jobs':{}}
def save():s['at']=time.time();(B/'precision_status.json').write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
jobs=json.loads((B/'manifest.json').read_text())['jobs'];save()
while len(s['jobs'])<len(jobs):
 for j in jobs:
  n=j['name'];d=R/'posts'/n
  if n in s['jobs'] or not (d/'lyrics.txt').exists() or not (d/'post'/f'{n}.json').exists():continue
  a=json.loads((B/'audio_status.json').read_text())
  if a['jobs'].get(n,{}).get('stage')!='audio_ready':continue
  s.update(status='precision_and_review',current=n);save()
  with (B/'precision_run.log').open('a') as log:r=subprocess.run([str(P),'-u',str(B/'run.py'),'--prepare-now','--only',n],cwd=R,stdout=log,stderr=log)
  result=json.loads((B/'status.json').read_text())['jobs'].get(n,{})
  s['jobs'][n]=result;s.update(status='waiting_for_audio_and_references',current=None);save()
 time.sleep(15)
s['status']='finished';save()
