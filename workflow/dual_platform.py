"""Explicit two-platform delivery: TS 1080i25 -> clean 50 -> shared Apple 60 -> two HEVC files.

python -m workflow.dual_platform CONCERT SONG
This entry point does not publish or select a cover. AI cover generation is an explicit plan step.
"""
import argparse,hashlib,json,os,shutil,subprocess as sp,time,uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np
from scipy.signal import correlate,correlation_lags
from workflow.live.paths import Concert
from workflow import dual_render as render
from workflow.song.render import DEFAULT_ENCODER,ENCODERS
ROOT=Path(__file__).resolve().parents[1]
FF=['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y']
def probe(p):return json.loads(sp.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(p)]))
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for block in iter(lambda:f.read(8*1024**2),b''):h.update(block)
 return h.hexdigest()
def render_pair(parallel=True):
 """One shared master, two independent ffmpeg processes; never commit partial outputs."""
 jobs=[('portrait','douyin'),('landscape','bilibili')]
 if not parallel:return [(platform,render.render(kind,commit=False)) for kind,platform in jobs]
 group=uuid.uuid4().hex;origin=time.monotonic()
 def branch(job):
  kind,platform=job
  metadata={'parallel_group':group,'group_offset_seconds':time.monotonic()-origin}
  return platform,render.render(kind,commit=False,timing_metadata=metadata)
 with ThreadPoolExecutor(max_workers=2) as pool:
  # Exiting the pool waits for both branches, including after a failure.
  return list(pool.map(branch,jobs))

def produce(slug,name,parallel=True):
 c=Concert(slug);item=c.item(name);d=c.song_dir(item)
 policy=json.loads((c.dir/'vertical_source.json').read_text())['songs'][name]
 if policy['kind']!='ts' or policy['fps']!=50:raise ValueError('This verified pipeline currently accepts TS 1080i25 -> 50fps only')
 source=Path(policy['source']);assert source.is_file()
 w=Path('/Volumes/harddisk_5T/adele-workflow/products')/slug/name/'apple-shared60-v1';w.mkdir(parents=True,exist_ok=True)
 link=d/'products'
 if not link.exists() and not link.is_symlink():link.symlink_to(w)
 elif link.resolve()!=w:raise ValueError(f'Preserve existing product directory: {link}')
 render.configure(c,item,w);manifest={'status':'running','items':[],'stage':'准备原片','engine':'Apple VideoToolbox · 共享一次50→60插帧 · 苹果HEVC编码'}
 def status(text):
  manifest['stage']=text;render.save(w/'products.json',manifest);print(name,text,flush=True)
 def mark(stage,t,**kw):render.timing(stage,time.monotonic()-t,**kw)
 cache=ROOT/'work/dual-platform-cache'/name;cache.mkdir(parents=True,exist_ok=True);local=cache/'native50.mkv'
 native=w/'native50.mkv';master=w/'master60.mkv';master_meta=w/'master-manifest.json'
 duration=policy['slice'][1]-policy['slice'][0]
 if master_meta.exists():
  cached=json.loads(master_meta.read_text())
  if cached['source']!=policy:raise ValueError('Cached master belongs to a different source or slice; use a new output run')
 if not master_meta.exists():
  if not native.exists():
   status('原片解码、去隔行50fps、无损保存');t=time.monotonic();pending=w/'native50.pending.mkv'
   with (w/'decode.log').open('w') as log:
    sp.run(FF+['-i',str(source),'-ss',str(policy['slice'][0]),'-t',str(duration),'-map','0:v:0','-map','0:a:0','-vf','bwdif=mode=send_field:parity=tff:deint=all,setsar=1','-r','50','-fps_mode','cfr','-c:v','libx264','-preset','ultrafast','-crf','0','-pix_fmt','yuv420p','-c:a','flac',str(pending)],stdout=log,stderr=log,check=True)
   v=next(x for x in probe(pending)['streams'] if x['codec_type']=='video');assert (v['width'],v['height'],v['avg_frame_rate'])==(1920,1080,'50/1')
   pending.replace(native);mark('source_decode_deinterlace_lossless',t,source=policy)
  if not local.exists():
   status('迁入本地插帧工作区并校验');t=time.monotonic()
   if shutil.disk_usage(cache).free<native.stat().st_size+2*1024**3:raise RuntimeError('Local SSD needs source size + 2 GiB; no automatic deletion')
   shutil.copy2(native,local);assert sha(local)==sha(native);mark('stage_lossless_input_on_local_ssd',t)
  status('切镜检测');t=time.monotonic()
  raw=sp.check_output(FF+['-i',str(local),'-an','-vf','scale=64:36,format=gray','-f','rawvideo','-'])
  frames=np.frombuffer(raw,np.uint8).reshape(-1,36,64).astype(np.float32);n=len(frames);diff=np.abs(np.diff(frames,axis=0)).mean(axis=(1,2));cuts=[]
  for i in np.where(diff>22)[0]:
   rebound=np.abs(frames[min(i+2,n-1)]-frames[i]).mean()
   if rebound<diff[i]*.5 or (i>0 and diff[i]<diff[i-1]*.75):continue
   cuts.append(int(i+1))
  render.save(w/'cuts.json',cuts);mark('scene_boundary_detection',t)
  binary=ROOT/'work/dual-platform-cache/apple_interpolate';src=ROOT/'workflow/native/apple_interpolate.m'
  if not binary.exists() or binary.stat().st_mtime<src.stat().st_mtime:
   sp.run(['clang','-O2','-fobjc-arc','-framework','Foundation','-framework','VideoToolbox','-framework','CoreMedia','-framework','CoreVideo',str(src),'-o',str(binary)],check=True)
  status('共享一次苹果50→60插帧');t=time.monotonic();out=round(n*60/50);pending=w/'master60.pending.mkv'
  with (w/'master.log').open('w') as log:
   dec=sp.Popen(FF+['-i',str(local),'-an','-pix_fmt','nv12','-f','rawvideo','-'],stdout=sp.PIPE,stderr=log)
   inter=sp.Popen([binary,str(n),str(out),w/'cuts.json'],stdin=dec.stdout,stdout=sp.PIPE,stderr=log);dec.stdout.close()
   enc=sp.Popen(FF+['-f','rawvideo','-pixel_format','nv12','-video_size','1920x1080','-framerate','60','-i','-','-i',str(local),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','ultrafast','-crf','0','-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-color_range','tv','-c:a','copy','-progress',str(w/'master.progress'),str(pending)],stdin=inter.stdout,stderr=log);inter.stdout.close()
   codes=[enc.wait(),inter.wait(),dec.wait()];assert codes==[0,0,0],codes
  mark('interpolate50to60_and_lossless_master',t,source_frames=n,output_frames=out)
  status('共享母版完整解码校验');t=time.monotonic();info=probe(pending);v=next(x for x in info['streams'] if x['codec_type']=='video');assert v['avg_frame_rate']=='60/1';assert abs(float(info['format']['duration'])-duration)<.05
  sp.run(FF+['-i',str(pending),'-map','0:v:0','-f','null','-'],check=True);pending.replace(master);mark('verify_master',t)
  render.save(master_meta,{'source':policy,'frames':out,'fps':60,'duration':duration,'native_sha256':sha(native),'engine':'Apple VTFrameRateConversion quality','cuts':cuts})
  local.unlink()  # Verified disposable local copy; external native and master retained.
 render.assets()
 status('双路并行：苹果HEVC合成编码' if parallel else '双路串行：苹果HEVC合成编码')
 pending_outputs=render_pair(parallel)
 status('完整解码、帧数与音频时钟校验');t=time.monotonic();checks=[];items=[]
 def pcm(p,t):return np.frombuffer(sp.check_output(FF+['-ss',str(t),'-i',str(p),'-t','4','-vn','-ac','1','-ar','8000','-f','f32le','-']),np.float32)
 for platform,p in pending_outputs:
  info=probe(p);v=next(x for x in info['streams'] if x['codec_type']=='video');a=next(x for x in info['streams'] if x['codec_type']=='audio');size=(3840,2160) if platform=='bilibili' else (1080,1920)
  assert (v['width'],v['height'],v['avg_frame_rate'],v['codec_name'])==(*size,'60/1','hevc')
  assert abs(float(v['duration'])-render.DURATION)<.035 and abs(float(a['duration'])-render.DURATION)<.04
  with (w/f'{platform}-validation.log').open('w') as log:sp.run(FF+['-xerror','-i',str(p),'-f','null','-'],stderr=log,check=True)
  offsets=[]
  for point in [5,render.DURATION/2,render.DURATION-8]:
   ref=pcm(native,point+render.START);actual=pcm(p,point);corr=correlate(actual,ref,mode='full',method='fft');lags=correlation_lags(len(actual),len(ref));valid=np.abs(lags)<=400;lag=int(lags[valid][np.argmax(corr[valid])]);offsets.append(lag/8000)
  assert max(abs(x) for x in offsets)<=1/60,offsets
  checks.append({'platform':platform,'full_decode':'passed','audio_offsets_seconds':offsets,'frames':v['nb_frames']})
  dest=p.with_name(p.name.replace('.pending',''))
  sec=next(x['seconds'] for x in reversed(json.loads((w/'timings.json').read_text())) if x['stage']==dest.stem+'_render_encode')
  items.append({'platform':platform,'file':dest.name,'width':size[0],'height':size[1],'fps':60,'status':'ready','duration':float(v['duration']),'render_seconds':sec,'bit_rate':int(v['bit_rate']),'start':render.START,'codec':'hevc','encoder':'hevc_videotoolbox'})
 mark('verify_both_outputs_decode_and_audio_clock',t)
 for platform,p in pending_outputs:
  dest=p.with_name(p.name.replace('.pending',''))
  if dest.exists():dest.rename(dest.with_name(dest.stem+'-previous-'+str(time.time_ns())+'.mp4'))
  p.replace(dest)
 manifest.update(status='ready',stage='双平台成品已验证',items=items,validation=checks,timings=json.loads((w/'timings.json').read_text()),created_local=datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m-%d %H:%M:%S'),encoding={'source':'workflow.song.render','preset':DEFAULT_ENCODER,'args':ENCODERS[DEFAULT_ENCODER]},source_policy=policy,encode_schedule='parallel' if parallel else 'serial')
 render.save(w/'products.json',manifest);print(name,'COMPLETE',flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('concert');p.add_argument('song')
 p.add_argument('--serial-encode',action='store_true',help='Diagnostic fallback; default is two concurrent Apple HEVC encodes')
 p.add_argument('--ai-cover-plan',type=Path,help='Explicit approved 1–3 composition plan; same master derives platform covers')
 p.add_argument('--skip-failed-covers',action='store_true',help='Explicitly continue unattempted candidates, never retry failed/uncertain requests')
 p.add_argument('--covers-only',action='store_true',help='Run the AI cover stage without re-encoding existing products')
 a=p.parse_args()
 if a.covers_only and not a.ai_cover_plan:p.error('--covers-only requires --ai-cover-plan')
 if not a.covers_only:produce(a.concert,a.song,parallel=not a.serial_encode)
 from workflow.delivery_bundle import write_bundle
 bundle_concert=Concert(a.concert)
 try:
  if a.ai_cover_plan:
   from workflow.seedream_cover import generate_trial
   generate_trial(bundle_concert,bundle_concert.item(a.song),a.ai_cover_plan,skip_failed=a.skip_failed_covers)
 finally:
  write_bundle(bundle_concert,bundle_concert.item(a.song))
