"""Reuse existing Apple delivery preset and already verified 60 fps master."""
import sys,json,time,subprocess as sp,hashlib
from pathlib import Path
from datetime import datetime
sys.path.insert(0,str(Path.cwd()))
from render_products import W,render,save,timing,DURATION,ENCODERS,DEFAULT_ENCODER
p=W/'products.json';manifest=json.loads(p.read_text());old=json.loads(p.read_text())
invariants={n:hashlib.sha256((W/n).read_bytes()).hexdigest() for n in ['portrait.ass','landscape.ass','header.png']}
master_stat=(W/'master60.mkv').stat();validation=[];new=[];verify_seconds=0
save(W/'before-hardware-products.json',old)
try:
 for kind,platform,size in [('portrait','douyin',(1080,1920)),('landscape','bilibili',(3840,2160))]:
  manifest.update(status='running',stage=f'{platform}：沿用苹果 HEVC 硬件编码，共享母版不重复插帧')
  save(p,manifest)
  pending=render(kind,commit=False);t=time.monotonic()
  info=json.loads(sp.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-of','json',str(pending)]))
  v=next(x for x in info['streams'] if x['codec_type']=='video');a=next(x for x in info['streams'] if x['codec_type']=='audio')
  assert (v['width'],v['height'],v['avg_frame_rate'],v['codec_name'],v['codec_tag_string'])==(*size,'60/1','hevc','hvc1'),v
  assert abs(float(v['duration'])-DURATION)<.02 and abs(float(a['duration'])-DURATION)<.04
  with (W/f'{platform}-hardware-validation.log').open('w') as log:sp.run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-xerror','-i',str(pending),'-f','null','-'],stderr=log,check=True)
  dest=W/(pending.name.replace('.pending',''))
  def audiohash(path):return sp.check_output(['/opt/homebrew/bin/ffmpeg','-v','error','-i',str(path),'-map','0:a:0','-c','copy','-f','hash','-hash','sha256','-']).decode().strip()
  assert audiohash(pending)==audiohash(dest),'audio changed'
  verify_seconds+=time.monotonic()-t
  validation.append({'platform':platform,'full_decode':'passed','audio':'identical to previously clock-verified output','codec':'hevc','tag':'hvc1','frames':v['nb_frames'],'duration':v['duration']})
  new.append((pending,dest,platform,v))
 for n,h in invariants.items():assert hashlib.sha256((W/n).read_bytes()).hexdigest()==h
 assert (W/'master60.mkv').stat().st_mtime_ns==master_stat.st_mtime_ns
 for pending,dest,platform,v in new:
  backup=dest.with_name(dest.stem+'-x264-before-hardware.mp4')
  if not backup.exists():dest.rename(backup)
  pending.replace(dest)
  rows=json.loads((W/'timings.json').read_text());sec=next(x['seconds'] for x in reversed(rows) if x['stage']==dest.stem+'_render_encode')
  for item in manifest['items']:
   if item['platform']==platform:item.update(codec='hevc',encoder='hevc_videotoolbox',encoder_preset=DEFAULT_ENCODER,render_seconds=sec,bit_rate=int(v['bit_rate']),previous=False)
 timing('verify_both_outputs_decode_and_audio_clock',verify_seconds)
 # Keep historical records; latest canonical entries are selected once by UI.
 manifest['timings']=old['timings']+json.loads((W/'timings.json').read_text())[-3:]
 manifest.update(status='ready',stage='苹果 HEVC 两版已验证',created_local=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),encoding={'preset_source':'workflow.song.render.ENCODERS[DEFAULT_ENCODER]','preset':DEFAULT_ENCODER,'args':ENCODERS[DEFAULT_ENCODER]},hardware_validation=validation)
 save(p,manifest);save(W/'hardware-validation.json',validation)
 env=json.loads((W/'environment.json').read_text());env['previous_encoding']=env.get('encoding');env['encoding']=manifest['encoding'];env['delivery_encoding']=manifest['encoding'];save(W/'environment.json',env)
 print('HARDWARE BOTH READY',[(x['platform'],x['render_seconds']) for x in manifest['items']],flush=True)
except Exception as e:
 old.update(stage='苹果编码重做失败，保留原成品',hardware_error=str(e));save(p,old);raise
