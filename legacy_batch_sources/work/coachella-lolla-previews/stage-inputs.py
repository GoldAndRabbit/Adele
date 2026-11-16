from pathlib import Path
import hashlib,shutil,json,os
from workflow.live.paths import read_json,write_json
base=Path('work/coachella-lolla-previews');scratch=Path('/private/tmp/adele-preview-inputs-20261110');scratch.mkdir(exist_ok=True)
jobs=read_json(base/'jobs.json')
for job in jobs:
 original=Path(job.get('original_source') or job['source']);target=scratch/(job['slug']+original.suffix)
 if not target.exists():
  if shutil.disk_usage(scratch).free<original.stat().st_size+8*1024**3:raise RuntimeError('Local staging space insufficient')
  partial=target.with_suffix(target.suffix+'.partial');digest=hashlib.sha256()
  with original.open('rb') as src,partial.open('wb') as dst:
   while chunk:=src.read(8*1024**2):dst.write(chunk);digest.update(chunk)
   dst.flush();os.fsync(dst.fileno())
  assert partial.stat().st_size==original.stat().st_size
  check=hashlib.sha256()
  with partial.open('rb') as f:
   while chunk:=f.read(8*1024**2):check.update(chunk)
  assert check.digest()==digest.digest()
  partial.replace(target)
  write_json(base/job['slug']/'staged-source.json',dict(original=str(original),local=str(target),size=target.stat().st_size,sha256=check.hexdigest()))
 job.update(original_source=str(original),source=str(target));write_json(base/'jobs.json',jobs)
 print('STAGED',job['slug'],target.stat().st_size,flush=True)
