"""Versioned, fail-closed visual admission for shared original-frame cover pools."""
import io,hashlib,subprocess
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import numpy as np
from PIL import Image,ImageOps
from workflow.live.paths import read_json,write_json
from workflow.live.cover_pool import frames,pool_dir
from workflow.vertical_cover import original_source,cover_ffmpeg
from workflow.llm import vision_json
VERSION='centered-color-front-v1'
PROMPT='''逐张检查演唱会原片候选封面，不能因画质高或灯光好忽略硬伤。主角应是歌手本人（不是背景大屏），正脸或能看到大半张脸、上半身清晰、位置适合居中。
必须拒绝：1明显背影/后脑勺/侧后方；2主角贴左或贴右，主体横向中心在画面0.28到0.72范围之外，或脸/身体被边缘切断，无法自然居中；3纯舞台/观众/大屏，无足够大的真人歌手（舞台小人不算）；4黑白或近乎无色画面；5夸张低机位仰拍、俯视/舞台边缘偷拍、严重歪斜/扭曲、奇怪截断或难以辨认的姿态；6模糊、过暗、脸严重遮挡。普通正面正常高度、平视或轻微侧面的稳定镜头可以通过。舞台彩色灯光的单色照明不自动算黑白。
每张返回：id数字、face_visible布尔、real_singer布尔、center_x(主角横向中心0到1)、subject_large布尔、monochrome布尔、awkward_angle布尔、edge_clipped布尔、clear布尔、score(0到10)、why中文理由。任何项不确定，不能通过。输出JSON {"items":[...]}。'''

def assess(batch):
 payload=[];answers={}
 for index,(path,digest) in enumerate(batch,1):
  im=Image.open(path).convert('RGB');small=np.asarray(im.resize((96,54)),dtype=np.float32)
  if float(np.mean(np.max(small,axis=2)-np.min(small,axis=2)))<4:
   answers[path.name]={'approved':False,'reason':'黑白/近乎无色画面','digest':digest,'version':VERSION};continue
  b=io.BytesIO();ImageOps.contain(im,(768,512)).save(b,'JPEG',quality=88);payload.append((f'图{index}',b.getvalue()))
 if payload:
  result=vision_json('你是严格的演唱会封面筛选员。',PROMPT,payload,label='封面硬条件筛选')
  by_id={str(x.get('id','')).replace('图',''):x for x in result.get('items',[])}
  for index,(path,digest) in enumerate(batch,1):
   if path.name in answers:continue
   x=by_id.get(str(index),{});cx=x.get('center_x');ok=(all(x.get(k) is True for k in ['face_visible','real_singer','subject_large','clear']) and all(x.get(k) is False for k in ['monochrome','awkward_angle','edge_clipped']) and isinstance(cx,(int,float)) and .28<=cx<=.72 and float(x.get('score',0))>=6)
   answers[path.name]={'approved':ok,'reason':x.get('why','判定缺失，未通过'),'detail':x,'digest':digest,'version':VERSION}
 return answers

def inspect(c):
 out=pool_dir(c);report=read_json(out/'quality.json',{'version':VERSION,'frames':{}});report['version']=VERSION;report['stage']='checking';write_json(out/'quality.json',report)
 pending=[]
 for row in frames(c,include_rejected=True):
  p=out/row['file'];digest=hashlib.sha256(p.read_bytes()).hexdigest();old=report['frames'].get(p.name,{})
  if old.get('version')!=VERSION or old.get('digest')!=digest or old.get('error'):pending.append((p,digest))
 with ThreadPoolExecutor(max_workers=3) as pool:
  jobs={pool.submit(assess,pending[i:i+8]):pending[i:i+8] for i in range(0,len(pending),8)}
  for job in as_completed(jobs):
   try:report['frames'].update(job.result())
   except Exception as e:
    for p,digest in jobs[job]:report['frames'][p.name]={'approved':False,'error':str(e),'digest':digest,'version':VERSION}
   write_json(out/'quality.json',report)
 report['stage']='ready';write_json(out/'quality.json',report)
 return len(frames(c))

def supplement(c,round_index,count=180):
 out=pool_dir(c);report=read_json(out/'quality.json');report['stage']='extracting';write_json(out/'quality.json',report); existing=frames(c,include_rejected=True);times=[r['t'] for r in existing]
 source=original_source(c,c.song_items()[0]);segs=[r for r in (c.load('segments') or {}).get('items',[]) if r.get('kind','song')=='song' and r.get('start') is not None and r.get('end',0)>r['start']]
 import json
 video=json.loads(subprocess.check_output([str(Path(cover_ffmpeg()).with_name('ffprobe')),'-v','error','-select_streams','v:0','-show_entries','stream=field_order','-of','json',str(source)]))['streams'][0]
 image_filter=('bwdif=mode=send_frame:parity=auto:deint=all,' if video.get('field_order') in ('tt','bb','tb','bt') else '')+'scale=1440:-2'
 if not segs:raise ValueError('缺少可用演唱范围，不能盲目截取问答或片尾')
 length=sum(r['end']-r['start'] for r in segs);points=[]
 for j in range(count):
  pos=length*(j+(round_index+1)/5)/count
  for seg in segs:
   duration=seg['end']-seg['start']
   if pos<duration:
    t=seg['start']+pos
    if all(abs(t-old)>1 for old in times):points.append(t)
    break
   pos-=duration
 def extract(t):
  name=f'frame_half_{round_index+50:02d}_{t:.3f}s.jpg';dest=out/name
  subprocess.run([cover_ffmpeg(),'-nostdin','-v','error','-ss',str(t),'-i',str(source),'-frames:v','1','-vf',image_filter,'-q:v','2',str(dest)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
  return name
 with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(extract,points))
 print('EXTRACTED',c.slug,len(points),flush=True)

def upgrade(c,target=100):
 count=inspect(c);print('SCREENED',c.slug,count,flush=True)
 for round_index in range(4):
  if count>=target:break
  supplement(c,round_index);count=inspect(c);print('SCREENED',c.slug,count,flush=True)
 if count<target:raise ValueError(f'当前仅 {count} 张通过，不用不合格画面凑数')
 return count
