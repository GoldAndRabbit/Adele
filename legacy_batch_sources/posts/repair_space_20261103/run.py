from pathlib import Path
import os,json,shutil,hashlib,time,fcntl
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workflow.storage import archive_root
R=Path('/Users/gold/repos/adele'); B=Path(__file__).parent; E=archive_root()
lock=(B/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
files=[p for p in (R/'concerts/singles/songs').glob('*/preview.mp4') if not p.is_symlink() and p.is_file() and (R/'posts'/p.parent.name/'post/publish.json').exists()]
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
