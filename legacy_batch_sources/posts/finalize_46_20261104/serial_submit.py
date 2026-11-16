"""One immediate submission, with a persisted attempt count and per-item lock."""
import fcntl,json,subprocess,time
from pathlib import Path
from types import SimpleNamespace
from post_bili import upload
from post_bili.metadata_quality import issues
ARGS=SimpleNamespace(cover=None,source=None,at=None,tid=None,tid_v2=None,only_self=False)
def read(p):
 return json.loads(p.read_text()) if p.is_file() else {}
def atomic(p,a):
 tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(a,ensure_ascii=False,indent=2));tmp.replace(p)
def check_copy(d):
 cfg=upload.generate(d,ARGS);cfg['定时发布']=''
 return cfg,issues(upload.from_page(cfg),read(d/'metadata_policy.json'))
def submit_one(d,b):
 post=d/'post'
 with (post/'serial_submit.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX)
  rec=read(post/'publish.json')
  if rec.get('bvid'):return 'submitted',rec['bvid']
  if rec:return 'awaiting_platform_check','已有回执需核对 BV'
  cfg,errors=check_copy(d)
  if errors:return 'waiting_for_metadata','；'.join(errors)
  marker=post/'submit_attempt_pending.json';prev=read(marker);last=int(prev.get('attempt',0))
  if prev:
   # Each subsequent attempt needs a fresh, recorded platform-management check.
   evidence=read(post/f'platform_check_after_attempt_{last}.json')
   if not (evidence.get('confirmed_absent') is True and evidence.get('title')==prev.get('title') and evidence.get('checked_at',0)>prev.get('started',0)):
    return 'awaiting_platform_check','需在稿件管理核实上次尝试是否已有稿件'
   if not prev.get('failed_at'):return 'awaiting_platform_check','上次上传结果待核对'
   if last>=3:return 'retry_limit','三次上传失败，平台已查重'
  _,errs=upload.check(upload.from_page(cfg))
  if errs:return 'waiting_for_review_files','；'.join(errs)
  if prev:atomic(post/f'submit_attempt_{last}.json',prev)
  (post/'bili_upload.json').write_text(upload.dump(cfg))
  data={'started':time.time(),'title':cfg['标题'],'attempt':last+1}
  atomic(marker,data)
  with (b/(d.name+'_submit.log')).open('a') as log:
   r=subprocess.run([str(upload.ROOT/'.venv/bin/python'),'post_bili/upload.py',str(d),'--submit','--line','bda2'],cwd=upload.ROOT,stdout=log,stderr=subprocess.STDOUT)
  rec=read(post/'publish.json')
  if rec.get('bvid'):return 'submitted',rec['bvid']
  if r.returncode:data.update(failed_at=time.time(),exit_code=r.returncode);atomic(marker,data)
  return 'awaiting_platform_check','无 BV，先查重'
