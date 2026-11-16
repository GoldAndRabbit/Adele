from pathlib import Path
import subprocess,numpy as np
from scipy.signal import correlate,fftconvolve
b=Path('work/angel-hammersmith');d=Path('posts/the_angel_hammersmith_5gu277dbf8i')
def wave(p):
 return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-vn','-ac','1','-ar','2000','-f','f32le','-']),dtype='<f4')
subprocess.run(['ffmpeg','-y','-v','error','-i',str(b/'251.media'),'-ar','48000','-ac','2',str(d/'audio.flac')],check=True)
a=wave(d/'audio.flac')
for name in ('the_angel_live','the_angel_gunnertv'):
 v=wave(Path('posts')/name/'audio.flac');print(name,flush=True)
 for t in [10,40,90,130,190,220]:
  s=v[t*2000:(t+6)*2000];norm=abs(correlate(a,s,'valid',method='fft'))/np.sqrt(np.maximum(fftconvolve(a*a,np.ones(len(s)),mode='valid'),1e-6)*np.dot(s,s));j=np.argmax(norm);print(t,round(j/2000,3),round(norm[j],3),flush=True)
