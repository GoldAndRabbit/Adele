import os,shutil,hashlib,json,time,subprocess
from pathlib import Path
root=Path('/Users/gold/repos/adele');external=Path('/Volumes/harddisk_5T/adele-workflow/local-offload-20261106');external.mkdir(exist_ok=True)
paths=[root/'work/grammy-source-policy/before',root/'work/grammy-ts-review/original-metadata',Path('/Users/gold/Downloads/Olivia Rodrigo - Live at Lollapalooza Brasil 2025 [2160p].mkv')]
report=[]
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
for src in paths:
 if src.is_symlink():continue
 dest=external/src.relative_to('/Users/gold');dest.parent.mkdir(parents=True,exist_ok=True)
 if dest.exists():raise RuntimeError(f'destination exists {dest}')
 # Never migrate files held by active or paused processes.
 files=[p for p in src.rglob('*') if p.is_file() and not p.is_symlink()]
 for p in files:
  if subprocess.run(['/usr/sbin/lsof','-t',str(p)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode==0:raise RuntimeError(f'File in use: {p}')
 t=time.monotonic();shutil.copytree(src,dest,symlinks=True)
 total=0
 for p in files:
  q=dest/p.relative_to(src)
  assert p.stat().st_size==q.stat().st_size and digest(p)==digest(q),(p,q)
  total+=p.stat().st_size
 # Replace the local directory with a link only after full byte verification.
 old=src.with_name(src.name+'.migration-verified');src.rename(old)
 try:src.symlink_to(dest,target_is_directory=True)
 except BaseException:old.rename(src);raise
 shutil.rmtree(old)
 report.append({'source':str(src),'destination':str(dest),'bytes':total,'seconds':time.monotonic()-t,'verified':'SHA256'})
 (root/'work/dual-dark-horse/migration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
 print('MIGRATED',src,total,flush=True)
