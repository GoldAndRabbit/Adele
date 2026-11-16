from pathlib import Path
import os,json,shutil,hashlib,time,fcntl
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workflow.storage import archive_root
R=Path('/Users/gold/repos/adele'); B=Path(__file__).parent; E=archive_root()
lock=(B/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
current=json.loads((R/'posts/upload_batch_20261031/status.json').read_text())['items']
managed={str(Path(x['directory'])/'post'/f"{x['name']} 4K60FPS Sub-WaterMark.mp4") for x in current}
active={x['name'] for x in current if not (Path(x['directory'])/'post/publish.json').exists()}
files=[]
for root in ['posts','concerts']:
 for base,dirs,names in os.walk(R/root,followlinks=False):
  dirs[:]=[x for x in dirs if not x.startswith('.') and x not in ['frames_in','frames_out'] and not Path(base,x).is_symlink()]
  for name in names:
   p=Path(base,name)
   if p.is_symlink() or name.startswith('._') or p.suffix.lower() not in ['.mp4','.mkv','.mov']:continue
   if any(x in active or x.startswith('next_20261031_') for x in p.relative_to(R).parts):continue
   if str(p) in managed:continue
   if name=='preview.mp4' or '4K' in name or (name=='source.mp4' and ('concerts' in p.parts or '_eminem_detroit_concert_source' in p.parts)):
    if p.stat().st_size:files.append(p)
files.sort(key=lambda p:p.stat().st_size,reverse=True)
state={'pid':os.getpid(),'status':'running','total':len(files),'planned_bytes':sum(p.stat().st_size for p in files),'freed_bytes':0,'items':[]}
def save():
 state['at']=time.time();tmp=B/'status.tmp';tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');tmp.replace(B/'status.json')
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for chunk in iter(lambda:f.read(8*1024**2),b''):h.update(chunk)
 return h.hexdigest()
save()
for p in files:
 state['current']=str(p);save()
 try:
  assert E.parent.is_mount() and not os.statvfs(E).f_flag & os.ST_RDONLY
  if p.is_symlink():continue
  before=p.stat();dest=E/'library'/p.relative_to(R);dest.parent.mkdir(parents=True,exist_ok=True)
  tmp=dest.with_name(dest.name+'.copying');shutil.copyfile(p,tmp)
  digest=sha(p);assert tmp.stat().st_size==before.st_size and sha(tmp)==digest
  assert p.stat().st_mtime_ns==before.st_mtime_ns
  if dest.exists():assert sha(dest)==digest
  tmp.replace(dest)
  backup=p.with_name(p.name+'.archive-backup');assert not backup.exists();p.rename(backup)
  try:
   p.symlink_to(dest);assert p.stat().st_size==before.st_size
  except BaseException:
   if p.is_symlink():p.unlink()
   backup.rename(p);raise
  backup.unlink();state['freed_bytes']+=before.st_size
  state['items'].append({'source':str(p),'target':str(dest),'bytes':before.st_size,'sha256':digest,'status':'archived'})
  print('archived',p,flush=True)
 except Exception as exc:state['items'].append({'source':str(p),'status':'failed','reason':str(exc)})
 save()
state['status']='finished';state['current']=None;save()
