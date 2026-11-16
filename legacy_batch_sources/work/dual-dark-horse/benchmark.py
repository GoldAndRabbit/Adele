import subprocess as s,time,json,tempfile,os
from pathlib import Path
ROOT=Path.cwd();w=Path('/Volumes/harddisk_5T/adele-workflow/products/grammys_2014/04_dark_horse/20261106');ff=['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-y'];results=[]
def apple(start,duration,out):
 t=time.monotonic()
 with (w/'apple-benchmark.log').open('a') as log:
  dec=s.Popen(ff+['-ss',str(start),'-i',str(w/'native50.mkv'),'-frames:v',str(round(duration*50)),'-an','-pix_fmt','nv12','-f','rawvideo','-'],stdout=s.PIPE,stderr=log)
  inter=s.Popen([ROOT/'work/dual-dark-horse/interpolate',str(round(duration*50)),str(round(duration*60))],stdin=dec.stdout,stdout=s.PIPE,stderr=log);dec.stdout.close()
  enc=s.Popen(ff+['-f','rawvideo','-pixel_format','nv12','-video_size','1920x1080','-framerate','60','-i','-','-c:v','libx264','-preset','ultrafast','-crf','0',out],stdin=inter.stdout,stderr=log);inter.stdout.close()
  codes=[enc.wait(),inter.wait(),dec.wait()];assert codes==[0,0,0],codes
 return time.monotonic()-t
for start in [50,90,180]:
 elapsed=apple(start,3,str(w/f'apple-{start}.mkv'));results.append({'engine':'Apple quality','start':start,'duration':3,'seconds':elapsed});print(results[-1],flush=True)
(w/'benchmark.json').write_text(json.dumps(results,indent=2))
# RIFE same 3-second sample, including a following source frame for interpolation.
with tempfile.TemporaryDirectory(prefix='rife-bench-',dir=w) as tmp:
 a,b=Path(tmp)/'in',Path(tmp)/'out';a.mkdir();b.mkdir();t=time.monotonic()
 s.run(ff+['-ss','90','-i',str(w/'native50.mkv'),'-frames:v','151','-compression_level','1',str(a/'%08d.png')],check=True)
 extract=time.monotonic()-t;t=time.monotonic()
 with (w/'rife-benchmark.log').open('w') as log:s.run([ROOT/'bin/rife-ncnn-vulkan','-i',a,'-o',b,'-m',ROOT/'models/rife-v4.6','-n','181','-j','2:3:2','-f','%08d.png'],stdout=log,stderr=log,check=True)
 elapsed=time.monotonic()-t
 s.run(ff+['-framerate','60','-i',str(b/'%08d.png'),'-frames:v','180','-c:v','libx264','-preset','ultrafast','-crf','0',str(w/'rife-90.mkv')],check=True)
 results.append({'engine':'RIFE4.6','start':90,'duration':3,'seconds':elapsed,'extract_seconds':extract});(w/'benchmark.json').write_text(json.dumps(results,indent=2));print(results[-1],flush=True)
