from pathlib import Path
import json,time,hashlib,shutil,fcntl,os
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workflow.storage import archive_root
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent;E=archive_root();lock=(B/'archive.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
entries=[(j['name'], Path(j['directory'])) for j in json.loads((B/'status.json').read_text())['items']]
names=[n for n, d in entries]
state={}
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for x in iter(lambda:f.read(4*1024*1024),b''):h.update(x)
 return h.digest()
while len(state)<len(names):
 for n,d in entries:
  if n in state:continue
  f=d/'post'/f'{n} 4K60FPS Sub-WaterMark.mp4'
  if not (d/'post/publish.json').exists() or not f.exists():continue
  try:
   assert E.parent.is_mount() and not os.statvfs(E).f_flag & os.ST_RDONLY
   if f.resolve().is_relative_to(E):state[n]={'status':'external','path':str(f.resolve())};continue
   dest=E/'outputs'/n/f.name;dest.parent.mkdir(parents=True,exist_ok=True)
   temp=dest.with_suffix('.copying.mp4');before=f.stat();shutil.copyfile(f,temp)
   assert before.st_size==temp.stat().st_size and sha(f)==sha(temp),'Checksum mismatch'
   assert f.stat().st_mtime_ns==before.st_mtime_ns,'Local file changed during copy'
   temp.replace(dest)
   backup=f.with_suffix('.local-backup.mp4');f.rename(backup)
   try:
    f.symlink_to(dest);assert f.stat().st_size==before.st_size
   except BaseException:
    if f.is_symlink():f.unlink()
    backup.rename(f);raise
   backup.unlink();state[n]={'status':'external','path':str(dest),'sha256_verified':True};print(n,'archived',flush=True)
  except Exception as ex:print(n,'archive deferred',repr(ex),flush=True)
 (B/'archive_status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
 if len(state)<len(names):time.sleep(20)
