import sys,time,json,subprocess as sp,shutil
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,str(Path.cwd()));sys.path.insert(0,str(Path('work/dual-dark-horse').resolve()))
from render_products import W,render,save,DURATION
begin=time.time();manifest=json.loads((W/'products.json').read_text());manifest['status']='running';manifest['stage']='仅重排横版：去除左右填充边，字幕字号与位置不变'
for x in manifest['items']:
 if x['platform']=='bilibili':x['previous']=True
save(W/'products.json',manifest)
old=W/'bilibili-4k60-side-fill-v1.mp4'
if not old.exists():shutil.copy2(W/'bilibili-4k60.mp4',old)
render('landscape');t=time.monotonic();path=W/'bilibili-4k60.mp4'
probe=json.loads(sp.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-of','json',str(path)]));v=next(x for x in probe['streams'] if x['codec_type']=='video');assert (v['width'],v['height'],v['avg_frame_rate'])==(3840,2160,'60/1');assert abs(float(v['duration'])-DURATION)<.02
with (W/'bilibili-v2-validation.log').open('w') as log:sp.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-xerror','-i',str(path),'-f','null','-'],stderr=log,check=True)
validation=time.monotonic()-t;rows=json.loads((W/'timings.json').read_text());seconds=next(x['seconds'] for x in reversed(rows) if x['stage']=='bilibili-4k60_render_encode')
for item in manifest['items']:
 if item['platform']=='bilibili':
  item.update(previous=False,render_seconds=seconds,bit_rate=int(v['bit_rate']),revision=2,crop='scale 3840x2160 then crop 3840x2054 centered; no distortion')
manifest.update(status='ready',created_local=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'))
manifest['timings'] += [{'stage':'bilibili_revision2_render','label':'横版第二版：去除侧边（未重复插帧）','seconds':seconds},{'stage':'bilibili_revision2_verify','label':'横版第二版完整解码验证','seconds':validation}]
manifest['revision2_seconds']=time.time()-begin;manifest['stage']='横竖成品均已验证';save(W/'products.json',manifest)
print('LANDSCAPE V2 READY',seconds,validation,flush=True)
