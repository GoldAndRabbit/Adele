import json,time,subprocess as s,shutil,hashlib
from pathlib import Path
import numpy as np
ROOT=Path.cwd();W=Path('/Volumes/harddisk_5T/adele-workflow/products/grammys_2014/04_dark_horse/20261106');L=ROOT/'work/dual-dark-horse/cache';L.mkdir(exist_ok=True)
ff=['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y'];timings=[]
def mark(stage,t,**kwargs):
 timings.append({'stage':stage,'seconds':time.monotonic()-t,**kwargs});(W/'master-timings.json').write_text(json.dumps(timings,indent=2));print(timings[-1],flush=True)
t=time.monotonic();src=W/'native50.mkv'
if shutil.disk_usage(L).free < src.stat().st_size+3*1024**3:raise RuntimeError('Waiting for verified migration: need source size + 3 GiB free locally')
local=L/'native50.mkv';shutil.copy2(src,local)
# Copy size plus hash verification before using the local working input.
def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(8*1024*1024),b''):h.update(b)
 return h.hexdigest()
assert sha(local)==sha(src)
mark('stage_lossless_input_on_local_ssd',t,bytes=local.stat().st_size)
t=time.monotonic()
raw=s.check_output(ff+['-i',str(local),'-an','-vf','scale=64:36,format=gray','-f','rawvideo','-'])
frames=np.frombuffer(raw,np.uint8).reshape(-1,36,64).astype(np.float32);n=len(frames);diff=np.abs(np.diff(frames,axis=0)).mean(axis=(1,2));cuts=[]
for i in np.where(diff>22)[0]:
 # A brief flash returns to the previous scene: don't label that as a shot change.
 rebound=np.abs(frames[min(i+2,n-1)]-frames[i]).mean()
 if rebound<diff[i]*.5:continue
 if i>0 and diff[i]<diff[i-1]*.75:continue
 cuts.append(int(i+1))
(W/'cuts.json').write_text(json.dumps(cuts));mark('scene_boundary_detection',t,source_frames=n,cuts=len(cuts))
t=time.monotonic();out=round(n*60/50);dest=W/'master60.pending.mkv'
with (W/'master.log').open('w') as log:
 dec=s.Popen(ff+['-i',str(local),'-an','-pix_fmt','nv12','-f','rawvideo','-'],stdout=s.PIPE,stderr=log)
 inter=s.Popen([ROOT/'work/dual-dark-horse/interpolate',str(n),str(out),W/'cuts.json'],stdin=dec.stdout,stdout=s.PIPE,stderr=log);dec.stdout.close()
 enc=s.Popen(ff+['-f','rawvideo','-pixel_format','nv12','-video_size','1920x1080','-framerate','60','-i','-','-i',str(local),'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','ultrafast','-crf','0','-pix_fmt','yuv420p','-colorspace','bt709','-color_primaries','bt709','-color_trc','bt709','-color_range','tv','-c:a','copy','-progress',str(W/'master.progress'),str(dest)],stdin=inter.stdout,stderr=log);inter.stdout.close()
 codes=[enc.wait(),inter.wait(),dec.wait()];assert codes==[0,0,0],codes
mark('interpolate50to60_and_lossless_master',t,source_frames=n,output_frames=out,engine='Apple VideoToolbox quality, arbitrary phase, cut protected',output_fps=out/(time.monotonic()-t))
t=time.monotonic();probe=json.loads(s.check_output(['/opt/homebrew/bin/ffprobe','-v','error','-show_streams','-show_format','-of','json',str(dest)]));v=next(x for x in probe['streams'] if x['codec_type']=='video');assert v['avg_frame_rate']=='60/1';assert abs(float(probe['format']['duration'])-n/50)<.05
s.run(ff+['-i',str(dest),'-map','0:v:0','-f','null','-'],check=True)
dest.replace(W/'master60.mkv');mark('verify_master',t)
(W/'master-manifest.json').write_text(json.dumps({'source':str(src),'source_sha256':sha(src),'frames':out,'fps':60,'duration':n/50,'engine':'Apple VTFrameRateConversion quality','cut_frames':cuts,'timings':timings},indent=2))
print('MASTER READY',flush=True)
