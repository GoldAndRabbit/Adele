from pathlib import Path
import os,sys,json,time,subprocess,shutil,fcntl,datetime
from types import SimpleNamespace
R=Path('/Users/gold/repos/adele');os.chdir(R);sys.path.insert(0,str(R))
from workflow.song.render import song_of,disk_need,song_seconds,one
from workflow.song import render as render_module
from estimate_space import estimate
original_disk_need = disk_need
def measured_disk_need(d, seconds):
 data=read(d/"space_estimate.json",{}) or {}
 signature=data.get("signature",[])
 if len(signature)==5 and abs(signature[3]-seconds)<0.01:
  src=d/"source.mp4"
  st=src.stat()
  if signature[:3]==[str(src.resolve()),st.st_size,st.st_mtime_ns]:return data["required_bytes"]
 return original_disk_need(d,seconds)
render_module.disk_need=measured_disk_need
from workflow.live.paths import Concert
from post_bili import upload
B=Path(__file__).parent;P=R/'.venv/bin/python'
lock=(B/'lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def read(p,default=None):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return default
specs=['post:'+x['name'] for x in read(R/'posts/queued_after_grammys_20261103/manifest.json')['jobs'][1:]]
for slug in ['olivia_acl_lclxvyamuce','grammys_2014']:
 specs += ['song:'+slug+':'+x['name'] for x in Concert(slug).song_items()]
specs += ['post:'+x.name for x in sorted((R/'posts').glob('pink_just_give_reason*redo')) if x.is_dir()]
assert len(specs)==46
state=read(B/'status.json',{'started':time.time(),'deadline':time.time()+20*3600,'items':[{'spec':s,'status':'queued'} for s in specs]})
state.update(pid=os.getpid(),status='running',publication_mode='immediate')
def save(row=None,stage=None,**kw):
 if row is not None:row.update(status=stage,**kw);state['current']=row['spec']
 state['updated']=time.time();state['local_free_bytes']=shutil.disk_usage(R).free
 tmp=B/'status.tmp';tmp.write_text(json.dumps(state,ensure_ascii=False,indent=2));tmp.replace(B/'status.json')
 if row is not None:print(row['spec'],stage,kw,flush=True)
def receipt(d):return (read(d/'post/publish.json',{}) or {}).get('bvid')
def valid(out):
 if not out.exists():return False
 try: return not upload.check_spec(out)[1]
 except Exception:return False
from serial_submit import submit_one, check_copy
while True:
 pending=False;progress=False
 backlog=[]
 for candidate in state['items']:
  if candidate['status'] in ('submitted','retry_limit'):continue
  folder=Path(candidate['directory'])
  if (folder/'post'/f'{folder.name} 4K60FPS Sub-WaterMark.mp4').is_file() or (folder/'post/submit_attempt_pending.json').exists():
   backlog.append(candidate)
 backlog.sort(key=lambda x:x['status'] in ('waiting_for_metadata','waiting_for_review_files'))
 for row in (backlog or state['items']):
  if row['status'] in ['submitted','failed','retry_limit']:continue
  spec=row['spec'];pending=True;d=None
  try:
   d,span,_=song_of(spec);out=d/'post'/f'{d.name} 4K60FPS Sub-WaterMark.mp4'
   row['directory']=str(d)
   if receipt(d):save(row,'submitted',bvid=receipt(d));progress=True;continue
   if spec.startswith('song:grammys_2014:') and (d.name.startswith('01_') or d.name.startswith('20_')) and not read(d/'repair_verified.json',{}).get('approved_for_render'):
    if row['status']!='needs_content_repair':save(row,'needs_content_repair',reason='已知切点/字幕问题，修复并核验后自动接续')
    continue

   if out.exists() and not valid(out):
    out.rename(out.with_suffix('.invalid.'+str(int(time.time()))+'.mp4'))
   if not valid(out):
    _,copy_errors=check_copy(d)
    if copy_errors:
     save(row,'waiting_for_metadata',reason='；'.join(copy_errors));continue
    src=d/'source.mp4'
    if span and not src.is_file():
     concert_src=Concert(spec.split(':')[1]).source
     if concert_src.is_file() and not src.exists() and not src.is_symlink():
      src.symlink_to(concert_src)
    if not src.is_file() or not src.stat().st_size:
     if row['status']!='waiting_for_source':save(row,'waiting_for_source',reason='原片补回并校验后自动接续')
     continue
    if d.stat().st_dev != R.stat().st_dev:
     raise RuntimeError('工作目录必须在内置盘')
    if not (d/'subs/lyrics_literal.ass').is_file() or not (d/'watermark.json').is_file():
     if row['status']!='waiting_for_review_files':save(row,'waiting_for_review_files',reason='等待定稿字幕及水印')
     continue
    required=measured_disk_need(d,song_seconds(d,span))
    if not (d/'space_estimate.json').exists():required+=8*2**30
    free=shutil.disk_usage(R).free
    (B/(d.name+'_space_preflight.json')).write_text(json.dumps({'time':time.time(),'free':free,'required':required}))
    if free<required:
     if row['status']!='waiting_for_space':save(row,'waiting_for_space',required_bytes=required,reason='等待已授权历史素材校验迁移释放空间')
     continue
    save(row,'rendering',required_bytes=required,reason='本地制作')
    # One encoder/interpolator at a time, using the reviewed subtitles and watermark plan.
    one(spec,enc='hevc_hw')
    assert valid(out),'4K60成片规格检查未通过'
   save(row,'rendered',video=str(out));progress=True
   save(row,'checking_submission')
   stage,detail=submit_one(d,B)
   if stage=='submitted':save(row,stage,bvid=detail,reason='已取得立即投稿回执')
   else:
    save(row,stage,reason=detail)
    if stage in ('waiting_for_metadata','waiting_for_review_files'):continue
   break  # Recompute the backlog before selecting any new render.
  except (Exception,SystemExit) as e:
   save(row,'awaiting_platform_check' if d is not None and (d/'post/submit_attempt_pending.json').is_file() else 'failed',reason=str(e))
 if all(x['status']=='submitted' for x in state['items']):state.update(status='complete',current=None);save();break
 state['status']='running' if progress else 'waiting_for_space_or_repairs';save()
 time.sleep(60)
