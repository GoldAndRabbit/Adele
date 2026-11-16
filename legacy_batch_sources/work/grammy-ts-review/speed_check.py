import subprocess as sp, numpy as np,json
from scipy.signal import correlate,resample
from pathlib import Path
from workflow.live.paths import Concert
c=Concert('grammys_2014')
old=Path(c.load('info')['source_file'])
src=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/ts-reviews/03_invisible/source.mp4')
full=Path('posts/grammys_2014/03_invisible/vertical/full.mp4')
def audio(p,t,d):
 return np.frombuffer(sp.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',p,'-t',str(d),'-vn','-ac','1','-ar','8000','-f','s16le','-']),'<i2').astype(float)/32768
x=audio(src,9,18);f=audio(full,9,18);print('clean-to-final audio correlation',np.corrcoef(x[:min(len(x),len(f))],f[:min(len(x),len(f))])[0,1],flush=True)
for t in (5,10,15,20,25,32,45):
 y=audio(old,1246.5+t,1.8); scores=[]
 for speed in [1,1.25,1.5,1.75,2,2.5]:
  yy=resample(y,round(len(y)/speed))
  z=correlate(x,yy,mode='valid',method='fft')
  pw=np.r_[0.,np.cumsum(x*x)];z/=np.sqrt(np.maximum((pw[len(yy):]-pw[:-len(yy)])*(yy*yy).sum(),1e-10));i=abs(z).argmax();scores.append((speed,round(float(abs(z[i])),3),round(9+i/8000,3)))
 print(t,sorted(scores,key=lambda t:t[1],reverse=True),flush=True)
