import json,subprocess,shutil,time,fcntl,os
from pathlib import Path
R=Path('/Users/gold/repos/adele'); B=Path(__file__).resolve().parent
lock=(B/'download.lock').open('w'); fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
s={'pid':os.getpid(),'jobs':{},'status':'running'}
def save():
 t=B/'download_worker_status.tmp';t.write_text(json.dumps(s,ensure_ascii=False,indent=2));t.replace(B/'download_worker_status.json')
for j in json.loads((B/'manifest.json').read_text())['jobs']:
 n=j['name'];p=R/'posts'/n;p.mkdir(exist_ok=True);s['current']=n;save()
 try:
  if not (p/'source.mp4').exists():
   if shutil.disk_usage(R).free<12*1024**3:raise RuntimeError('内置盘低于12GiB，需先归档释放空间')
   s['jobs'][n]={'stage':'downloading'};save()
   with (B/'logs'/f'{n}_proxy_download.log').open('a') as f:
    # Only prepare the source; the shared entry point handles PO Tokens and external storage.
    subprocess.run([str(R/'.venv/bin/python'),str(R/'workflow/make_mv.py'),'--name',n,'--url',j['url'],'--to','download','--proxy','http://127.0.0.1:7890','--cookies-from-browser','chrome'],stdout=f,stderr=subprocess.STDOUT,check=True,timeout=3600)
  v=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(p/'source.mp4')],text=True,timeout=30))
  assert {'audio','video'} <= {x['codec_type'] for x in v['streams']}
  (p/'source_validation.json').write_text(json.dumps(v,indent=2));duration=float(v['format']['duration'])
  if (p/'source.info.json').exists():
   d=json.loads((p/'source.info.json').read_text());(p/'meta.json').write_text(json.dumps({k:d.get(k) for k in ('title','channel','duration','language','track','artist','upload_date','description','tags','webpage_url')},ensure_ascii=False,indent=2))
  s['jobs'][n]={'stage':'source_verified','duration':duration,'needs_concert_review':duration>900}
 except Exception as e:s['jobs'][n]={'stage':'blocked','reason':str(e)}
 save()
s['status']='finished';s['current']=None;save()
