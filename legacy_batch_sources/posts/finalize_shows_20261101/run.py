from pathlib import Path
import sys,os,json,subprocess,datetime,time,shutil,hashlib,fcntl
R=Path('/Users/gold/repos/adele');sys.path.insert(0,str(R));os.chdir(R)
from workflow.song.render import render,ENCODERS
from workflow.make_mv import check_hires
from post_bili import upload
from types import SimpleNamespace
B=Path(__file__).parent;P=R/'.venv/bin/python';L=R/'posts/.local-render'
lock=(R/'posts/additional_batch_20261030/finalize/queue.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
m=json.loads((R/'posts/next_batch_20261031/manifest.json').read_text())
entries=[(x['name'],R/'posts'/x['name']) for x in m['jobs']]
state={'pid':os.getpid(),'status':'running','items':[{'name':n,'directory':str(d),'status':'submitted' if (d/'post/publish.json').exists() else 'queued'} for n,d in entries]}
def save(row,stage,**kw):
 row.update(status=stage,**kw);state['current']=row['name'];(B/'status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');print(row['name'],stage,kw,flush=True)
def probe(f):
 p=subprocess.run(['ffprobe','-v','error','-show_entries','stream=width,height,avg_frame_rate:format=duration','-select_streams','v:0','-of','json',str(f)],capture_output=True,text=True,check=True);return json.loads(p.stdout)
def valid(f):
 if not f.exists():return False
 try:
  v=probe(f)['streams'][0];a,b=map(int,v['avg_frame_rate'].split('/'));return v['width']==3840 and v['height']==2160 and a/b>=59
 except Exception:return False
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
 return h.digest()
def interpolation_ok(w):
 v=w/'video_1080.mp4'
 if not v.exists():return False
 info=probe(v);expected=round(float(info['format']['duration'])*60)
 fs=sorted(x for x in (w/'frames_out').glob('*.jpg') if x.stem.isdigit())
 return abs(len(fs)-expected)<=3 and len(fs)>0 and [int(x.stem) for x in fs]==list(range(1,len(fs)+1)) and all(x.stat().st_size>1000 for x in fs)
for row in state['items']:
 d=Path(row['directory']);n=row['name'];save(row,row['status'])
 if (d/'post/publish.json').exists():continue
 try:
  if n=='olivia_deja_vu_mv_cii6ruuycqa':
   save(row,'awaiting_platform_check',reason='Three failed attempts; fresh platform check and retry resolution required');continue
  assert [p for p in (d/'post').glob(f'{n}_cover_picked_*.png') if not p.name.startswith('._')],'选定封面未保存'
  w=L/n;w.mkdir(parents=True,exist_ok=True);local=w/f'{n} 4K60FPS Sub-WaterMark.mp4';target=d/'post'/local.name
  if not valid(target):
   if not valid(local):
    save(row,'preparing_local')
    if not (w/'source.mp4').exists() or (w/'source.mp4').stat().st_size == 0:shutil.copyfile(d/'source.mp4',w/'source.mp4')
    if (not (w/'video_1080.mp4').exists() or (w/'video_1080.mp4').stat().st_size == 0) and (d/'video_1080.mp4').exists():shutil.copyfile(d/'video_1080.mp4',w/'video_1080.mp4')
    if not interpolation_ok(w):
     save(row,'interpolating_local')
     subprocess.run([P,'-u','workflow/make_mv.py','--name',n,'--from','interp','--to','interp','--frame-format','jpg'],env=dict(os.environ,ADELE_POSTS=str(L)),check=True)
     info=probe(w/'video_1080.mp4');a,b=map(int,info['streams'][0]['avg_frame_rate'].split('/'))
     assert a/b>=59 or interpolation_ok(w),'插帧产物不完整或存在空帧'
    save(row,'encoding_local');render(d,w,local,enc=ENCODERS['hevc_hw'],log=B/f'{n}_encode.log')
    assert valid(local),'成片规格不符';check_hires(local)
   save(row,'copying_verified_final');temp=target.with_suffix('.copying.mp4');shutil.copyfile(local,temp)
   assert local.stat().st_size==temp.stat().st_size and sha(local)==sha(temp),'成片复制哈希不一致'
   temp.replace(target)
  check_hires(target)
  marker=d/'post/submit_attempt_pending.json'
  assert not marker.exists(),'Previous submission attempt requires platform verification before retry'
  args=SimpleNamespace(cover=None,source=None,at=None,tid=None,tid_v2=None,only_self=False)
  config=upload.generate(d,args)
  # Use the latest reviewed title and selected cover, while retaining other saved options.
  cf=d/'post/bili_upload.json'
  if cf.exists():
   previous=json.loads(cf.read_text())
   for key in ['视频文件','封面16:9','封面4:3','标题','简介','标签']:
    if key in config:previous[key]=config[key]
   config=previous
  config['定时发布']=datetime.datetime.fromtimestamp(time.time()+15000).strftime('%Y-%m-%d %H:%M')
  cf.write_text(json.dumps(config,ensure_ascii=False,indent=2)+'\n')
  _,errors=upload.check(upload.from_page(config));assert not errors,'; '.join(errors)
  marker.write_text(json.dumps({'started':time.time(),'title':config['标题'],'authorization':'user approved full production and upload'}))
  save(row,'uploading');subprocess.run([P,'post_bili/upload.py',d,'--submit','--line','bda2'],check=True)
  assert (d/'post/publish.json').exists(),'未取得回执，需核对平台后重试以免重复'
  receipt=json.loads((d/'post/publish.json').read_text());save(row,'submitted',bvid=receipt.get('bvid'))
  # Only disposable working copies are cleaned; original sources and the verified final remain.
  shutil.rmtree(w,ignore_errors=True)
 except Exception as ex:
  save(row,'blocked',reason=str(ex));print(repr(ex),flush=True)
  if 'w' in locals():
   for part in ['frames_in','frames_out']:shutil.rmtree(w/part,ignore_errors=True)
state['status']='finished';state['current']=None;(B/'status.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
print('New batch finished; failed items require platform deduplication before retry.',flush=True)
