"""Configured delivery: confirmed source -> Apple 60 -> selected HEVC outputs.

The standard workflow invokes encode_job through workflow.delivery.
This entry point does not publish or select a cover. AI cover generation is an explicit plan step.
"""
import json,shutil,subprocess as sp,time,uuid
from concurrent.futures import ThreadPoolExecutor
from platform import node as hostname
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from workflow.runtime import sha
from workflow import dual_render as render
from workflow.encoding import DEFAULT_ENCODER,ENCODERS
from workflow.delivery_config import render_platforms, single_channel_pipeline
ROOT=Path(__file__).resolve().parents[1]
FF=['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y']
def probe(p):return json.loads(sp.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
def render_pair(parallel=True, platforms=None):
 """One shared master, two independent ffmpeg processes; never commit partial outputs."""
 selected=render_platforms(platforms)
 jobs=[(kind,platform) for kind,platform in [('portrait','douyin'),('landscape','bilibili')] if platform in selected]
 if len(jobs)==1:parallel=False
 if not parallel:return [(platform,render.render(kind,commit=False)) for kind,platform in jobs]
 group=uuid.uuid4().hex;origin=time.monotonic()
 def branch(job):
  kind,platform=job
  metadata={'parallel_group':group,'group_offset_seconds':time.monotonic()-origin}
  return platform,render.render(kind,commit=False,timing_metadata=metadata)
 with ThreadPoolExecutor(max_workers=2) as pool:
  # Exiting the pool waits for both branches, including after a failure.
  return list(pool.map(branch,jobs))

def encode_job(policy, source, w, cache, directory, parallel=True):
 """Encode prepared overlays on the executing Mac; record its actual hostname."""
 from workflow.content_check import require_job
 require_job(policy,w,source)
 original = policy['kind'] != 'ts' or policy.get('fps') != 50
 selected=render_platforms(policy.get('delivery_platforms'))
 parallel=parallel and len(selected)>1
 name=directory.name
 render.W=w;render.D=directory;render.START=0
 render.DURATION=policy['slice'][1]-policy['slice'][0]
 manifest={'status':'running','items':[],'render_host':hostname(),
           'started_at':datetime.now().astimezone().isoformat(),
           'engine':'Apple VideoToolbox · 共享一次50→60插帧 · 苹果HEVC编码',
           'delivery_platforms':list(selected)}
 def status(text):
  manifest['stage']=text;render.save(w/'products.json',manifest)
  print(datetime.now().astimezone().isoformat(),manifest['render_host'],name,text,flush=True)
 def mark(stage,t,**kw):render.timing(stage,time.monotonic()-t,**kw)
 if len(selected)==1 and policy.get('single_channel_pipeline',single_channel_pipeline())=='stream':
  from workflow.stream_delivery import encode
  manifest.update(engine='Apple 单渠道流式插帧与合成编码',pipeline='stream',intermediate_video=False)
  pending_outputs=encode(policy,source,w,cache,selected[0],probe,FF,status)
  status('确认所选平台成品规格')
  finish_outputs(w,policy,manifest,pending_outputs,False)
  return
 local=cache/'native50.mkv'
 native=local;master=cache/'master60.mkv';master_meta=cache/'master-manifest.json'
 render.MASTER_DIR=cache
 duration=policy['slice'][1]-policy['slice'][0]
 if original:
  native=cache/'native.mkv'
  manifest['engine']='按原片帧率制作共享60fps母版 · 苹果HEVC双平台编码'
 if master_meta.exists():
  cached=json.loads(master_meta.read_text())
  if cached['source']!=policy:raise ValueError('Cached master belongs to a different source or slice; use a new output run')
 if original and not master_meta.exists():
  from workflow.original_master import prepare
  import tempfile
  status('按原始帧率和色彩制作共享60fps母版');t=time.monotonic()
  with tempfile.TemporaryDirectory(prefix='source-',dir=cache) as folder:
   scratch=Path(folder)
   prepare(source,policy['slice'][0],duration,scratch,probe,FF,log_dir=w,
           input_color_matrix=policy.get('input_color_matrix'),audio_decoder=policy.get('audio_decoder'))
   info=probe(scratch/'master60.mkv')
   if next(v for v in info['streams'] if v['codec_type']=='video')['avg_frame_rate']!='60/1' or abs(float(info['format']['duration'])-duration)>.08:
    raise ValueError('共享母版帧率或片长不符')
   (scratch/'native.mkv').replace(native);(scratch/'master60.mkv').replace(master)
  render.save(master_meta,{'source':policy,'fps':60,'duration':duration})
  mark('prepare_original_master',t)
 elif not master_meta.exists():
  if not native.exists():
   status('原片解码、去隔行50fps、无损保存');t=time.monotonic();pending=cache/'native50.pending.mkv'
   with (w/'decode.log').open('w') as log:
    sp.run(FF+['-i',str(source),'-ss',str(policy['slice'][0]),'-t',str(duration),'-map','0:v:0','-map','0:a:0','-vf','bwdif=mode=send_field:parity=tff:deint=all,setsar=1','-r','50','-fps_mode','cfr','-c:v','libx264','-preset','ultrafast','-crf','0','-pix_fmt','yuv420p','-c:a','flac',str(pending)],stdout=log,stderr=log,check=True)
   v=next(x for x in probe(pending)['streams'] if x['codec_type']=='video');assert (v['width'],v['height'],v['avg_frame_rate'])==(1920,1080,'50/1')
   pending.replace(native);mark('source_decode_deinterlace_lossless',t,source=policy)
  if shutil.disk_usage(cache).free < native.stat().st_size * 1.2 + 2 * 1024**3:
   raise RuntimeError('内置盘剩余空间不足以生成 60fps 母版')
  status('切镜检测');t=time.monotonic()
  raw=sp.check_output(FF+['-i',str(local),'-an','-vf','scale=64:36,format=gray','-f','rawvideo','-'])
  frames=np.frombuffer(raw,np.uint8).reshape(-1,36,64).astype(np.float32);n=len(frames);diff=np.abs(np.diff(frames,axis=0)).mean(axis=(1,2));cuts=[]
  for i in np.where(diff>22)[0]:
   rebound=np.abs(frames[min(i+2,n-1)]-frames[i]).mean()
   if rebound<diff[i]*.5 or (i>0 and diff[i]<diff[i-1]*.75):continue
   cuts.append(int(i+1))
  render.save(cache/'cuts.json',cuts);mark('scene_boundary_detection',t)
  binary=cache/'apple_interpolate';src=ROOT/'workflow/native/apple_interpolate.m'
  if not binary.exists() or binary.stat().st_mtime<src.stat().st_mtime:
   sp.run(['clang','-O2','-fobjc-arc','-framework','Foundation','-framework','VideoToolbox','-framework','CoreMedia','-framework','CoreVideo',str(src),'-o',str(binary)],check=True)
  status('共享一次苹果50→60插帧');t=time.monotonic();out=round(n*60/50);pending=cache/'master60.pending.mkv'
  with (w/'master.log').open('w') as log:
   dec=sp.Popen(FF+['-i',str(local),'-an','-pix_fmt','nv12','-f','rawvideo','-'],stdout=sp.PIPE,stderr=log)
   inter=sp.Popen([binary,str(n),str(out),cache/'cuts.json'],stdin=dec.stdout,stdout=sp.PIPE,stderr=log);dec.stdout.close()
   enc=sp.Popen(FF+['-f','rawvideo','-pixel_format','nv12','-video_size','1920x1080','-framerate','60','-i','-','-i',str(local),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','ultrafast','-crf','0','-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-color_range','tv','-c:a','copy','-progress',str(w/'master.progress'),str(pending)],stdin=inter.stdout,stderr=log);inter.stdout.close()
   codes=[enc.wait(),inter.wait(),dec.wait()];assert codes==[0,0,0],codes
  mark('interpolate50to60_and_lossless_master',t,source_frames=n,output_frames=out)
  status('共享母版完整解码校验');t=time.monotonic();info=probe(pending);v=next(x for x in info['streams'] if x['codec_type']=='video');assert v['avg_frame_rate']=='60/1';assert abs(float(info['format']['duration'])-duration)<.05
  sp.run(FF+['-i',str(pending),'-map','0:v:0','-f','null','-'],check=True);pending.replace(master);mark('verify_master',t)
  render.save(master_meta,{'source':policy,'frames':out,'fps':60,'duration':duration,'native_sha256':sha(native),'engine':'Apple VTFrameRateConversion quality','cuts':cuts})

 status('B站横屏：苹果HEVC合成编码' if selected==('bilibili',) else '所选平台：苹果HEVC合成编码')
 pending_outputs=render_pair(parallel,selected)
 status('确认所选平台成品规格')
 finish_outputs(w, policy, manifest, pending_outputs, parallel)
 if original:
  master_meta.unlink(missing_ok=True);native.unlink(missing_ok=True);master.unlink(missing_ok=True)

def finish_outputs(w, policy, manifest, pending_outputs, parallel=True):
 from workflow.content_check import require_job
 require_job(policy,w)
 selected=render_platforms(policy.get('delivery_platforms'))
 if len(pending_outputs)!=len(selected) or {platform for platform,_ in pending_outputs}!=set(selected):
  raise ValueError('所选平台成品不完整')
 duration = policy['slice'][1] - policy['slice'][0]
 checks=[];items=[]
 for platform,p in pending_outputs:
  info=probe(p);v=next((x for x in info['streams'] if x['codec_type']=='video'),None);a=next((x for x in info['streams'] if x['codec_type']=='audio'),None);size=(3840,2160) if platform=='bilibili' else (1080,1920)
  if v is None or a is None:
   raise ValueError(f'{platform} 成品缺少有效视频或音轨，保留待修复文件，不交付')
  if platform == 'bilibili':
   from workflow.media import check_hires
   check_hires(p)
  assert (v['width'],v['height'],v['avg_frame_rate'],v['codec_name'])==(*size,'60/1','hevc')
  assert abs(float(v['duration'])-duration)<.035 and abs(float(a['duration'])-duration)<.04
  checks.append({'platform':platform,'specifications':'passed','audio_codec':a['codec_name'],'frames':v['nb_frames']})
  dest=p.with_name(p.name.replace('.pending',''))
  sec=next(x['seconds'] for x in reversed(json.loads((w/'timings.json').read_text())) if x['stage']==dest.stem+'_render_encode')
  items.append({'platform':platform,'file':dest.name,'width':size[0],'height':size[1],'fps':60,'status':'ready','duration':float(v['duration']),'render_seconds':sec,'bit_rate':int(v['bit_rate']),'start':0,'codec':'hevc','encoder':'hevc_videotoolbox'})
 for platform,p in pending_outputs:
  dest=p.with_name(p.name.replace('.pending',''))
  if dest.exists():dest.rename(dest.with_name(dest.stem+'-previous-'+str(time.time_ns())+'.mp4'))
  p.replace(dest)
 manifest.update(status='ready',stage='所选平台成品已验证',items=items,validation=checks,timings=json.loads((w/'timings.json').read_text()),created_local=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),encoding={'source':'workflow.encoding','preset':DEFAULT_ENCODER,'args':ENCODERS[DEFAULT_ENCODER]},source_policy=policy,delivery_platforms=list(selected),encode_schedule='parallel' if parallel else 'serial')
 render.save(w/'products.json',manifest);print(w.name,'COMPLETE',flush=True)
