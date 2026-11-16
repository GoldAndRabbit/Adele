from pathlib import Path
import os,json,time,shutil,hashlib,fcntl,subprocess,signal
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workflow.storage import archive_root
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent;E=archive_root()
lock=(B/'maintenance.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def read(p,default):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return default
state=read(B/'archive_status.json',{'items':[]});state['pid']=os.getpid()
def save():
 state['updated']=time.time();p=B/'archive_status.tmp';p.write_text(json.dumps(state,ensure_ascii=False,indent=2));p.replace(B/'archive_status.json')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024**2),b''):h.update(b)
 return h.hexdigest()
def migrate(p):
 if p.is_symlink() or not p.is_file():return
 assert archive_root() == E, '归档盘已更换'
 before=p.stat();dest=E/'library'/p.relative_to(R);dest.parent.mkdir(parents=True,exist_ok=True)
 tmp=dest.with_name(dest.name+'.finalize46.copying');shutil.copyfile(p,tmp)
 digest=sha(p);assert tmp.stat().st_size==before.st_size and sha(tmp)==digest
 assert p.stat().st_mtime_ns==before.st_mtime_ns
 if dest.exists():assert sha(dest)==digest
 tmp.replace(dest);link=p.with_name(p.name+'.finalize46.link');link.symlink_to(dest);os.replace(link,p)
 state['items'].append({'source':str(p),'target':str(dest),'bytes':before.st_size,'sha256':digest});save()
while True:
 batch=read(B/'status.json',{});rows=batch.get('items',[])
 for row in rows:
  if row.get('status')!='submitted':continue
  d=Path(row['directory']).resolve();receipt=read(d/'post/publish.json',{})
  if not receipt.get('bvid'):continue
  try:
   p=d/'post'/f'{d.name} 4K60FPS Sub-WaterMark.mp4';state.update(current=str(p),stage='archiving');save();migrate(p)
  except Exception as e:state.update(stage='archive_error',reason=str(e));save()
 # Extra space: the old migration explicitly excludes these new queue sources.
 if shutil.disk_usage(R).free<40*2**30:
  for p in (R/'posts').glob('queued_20261103_*/source.mp4'):
   if p.is_symlink():continue
   try:
    state.update(current=str(p),stage='moving_source_for_space');save();migrate(p)
   except Exception as e:state.update(stage='archive_error',reason=str(e));save()
   if shutil.disk_usage(R).free>=40*2**30:break
 if batch.get('status')=='complete':state.update(stage='complete',current=None);save();break
 state.update(stage='monitoring',free_bytes=shutil.disk_usage(R).free);save();time.sleep(60)
