from pathlib import Path
import subprocess, json
import numpy as np
from scipy.signal import correlate
from workflow.live.paths import Concert,read_json
c=Concert('dualipa_mexico2025')
source=c.load('info')['source_file']
def audio(path,start,dur):
 cmd=['ffmpeg','-nostdin','-v','error','-ss',str(start),'-i',str(path),'-t',str(dur),'-map','0:a:0','-vn','-ac','1','-ar','2000','-f','f32le','-']
 return np.frombuffer(subprocess.check_output(cmd),dtype='<f4')
def match(a,b):
 from scipy.signal import fftconvolve
 fit=correlate(a,b,'valid',method='fft')
 energy=np.maximum(fftconvolve(a*a,np.ones(len(b)),mode='valid'),1e-9)
 norm=np.abs(fit)/np.sqrt(energy*np.dot(b,b))
 k=np.argmax(norm);return k/2000,round(float(norm[k]),3)
def check(it):
 d=c.song_dir(it);s,e=read_json(d/'song.json')['slice']; hits=[]
 if not (d/'audio.flac').is_file():return dict(name=it['name'],slice=[s,e],hits=[])
 for t in (min(24,(e-s)*0.25),max(30,e-s-30)):
  a=max(0,s+t-90);offset,score=match(audio(source,a,190),audio(d/'audio.flac',t,7))
  hits.append([round(a+offset-t-s,3),score])
 return dict(name=it['name'],slice=[s,e],hits=hits)
if __name__=='__main__':
 from concurrent.futures import ThreadPoolExecutor
 with ThreadPoolExecutor(max_workers=3) as pool:
  rows=list(pool.map(check,c.song_items()))
 Path('work/mexico-review/alignment.json').write_text(json.dumps(rows,indent=2))
 print(rows)
