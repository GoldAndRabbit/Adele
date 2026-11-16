from pathlib import Path
import subprocess,numpy as np,json
from scipy.signal import correlate
def wave(p):
 return np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(p),'-vn','-ac','1','-ar','4000','-f','f32le','-']),dtype='<f4')
a=wave('work/angel-hammersmith/review-source.mp4');b=wave('posts/the_angel_gunnertv/audio.flac');rows=[]
for t in range(1,267):
 s=b[t*4000:(t+1)*4000];o=(t+23)*4000;h=a[o:o+8000];z=correlate(h,s,'valid',method='fft');i=np.argmax(z);q=z[i]/(np.linalg.norm(s)*np.linalg.norm(h[i:i+len(s)])+1e-8);rows.append([t,23+i/4000,round(float(q),3)])
print('accurate windows',sum(r[2]>.5 for r in rows),len(rows),'offsets',np.percentile([r[1] for r in rows if r[2]>.5],[0,50,100]),'weak',[(r[0],r[2]) for r in rows if r[2]<.4][:60])
Path('work/angel-hammersmith/offset.json').write_text(json.dumps(rows))
