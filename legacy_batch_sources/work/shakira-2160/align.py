import json,subprocess
from pathlib import Path
import numpy as np
from scipy import signal
from workflow.live.paths import *
base=ROOT/'work/shakira-2160';c=Concert('shakira_madrid_2026')
old=Path(c.load('info')['source_file']);new=Path('/Volumes/harddisk_5T/thunder_downloads/Shakira Live From Madrid (2026) [2160p].mkv/Shakira Live From Madrid (2026) [2160p].mkv')
def features(y):
 w=np.lib.stride_tricks.sliding_window_view(y,512)[::400];bins=np.round(np.geomspace(50,3800,19)/(8000/512)).astype(int);rows=[]
 for j in range(0,len(w),2048):
  ft=np.abs(np.fft.rfft(w[j:j+2048]*np.hanning(512),axis=1));band=np.stack([np.log1p(ft[:,a:max(a+1,b)].mean(axis=1)) for a,b in zip(bins,bins[1:])],axis=1);rows.append(band-band.mean(axis=1,keepdims=True))
 return np.concatenate(rows).astype('float32')
for label,src in [('old',old),('new',new)]:
 target=base/(label+'.s16')
 if not target.exists():subprocess.run(['/opt/homebrew/bin/ffmpeg','-v','error','-i',str(src),'-vn','-ar','8000','-ac','1','-f','s16le',str(target)],check=True)
 target=base/(label+'.npy')
 if not target.exists():
  pcm=np.memmap(base/(label+'.s16'),dtype='<i2',mode='r');np.save(target,features(np.asarray(pcm,dtype=np.float32)/32768))
X=np.load(base/'new.npy');Y=np.load(base/'old.npy');results={}
for it in c.song_items():
 d=c.song_dir(it);info=read_json(d/'song.json');a,b=info['slice'];lo=max(0,int((a-500)*20));hi=min(len(X),int((b+500)*20));seg=X[lo:hi];pw=np.r_[0,np.cumsum((seg**2).sum(axis=1),dtype='float64')];anchors=[]
 for t in sorted(set([a+1,a+5,*np.arange(a+10,b-5,10),b-5])):
  y=Y[round(t*20):round(t*20)+80];n=len(y)
  z=sum(signal.correlate(seg[:,j],y[:,j],method='fft',mode='valid') for j in range(18));energy=pw[n:]-pw[:-n];z/=np.sqrt(np.maximum(energy*(y*y).sum(),1e-8));k=int(z.argmax());new_t=(lo+k)/20
  anchors.append({'old':round(t,3),'new':round(new_t,3),'delta':round(new_t-t,3),'score':round(float(z[k]),3)})
 good=[x['delta'] for x in anchors if x['score']>.85]
 results[it['name']]={'title':it['title'],'old_slice':[a,b],'anchors':anchors,'median_delta':round(float(np.median(good)),3) if good else None,'spread':round(float(np.ptp(good)),3) if good else None}
 write_json(base/'alignment.json',results);print(it['name'],results[it['name']]['median_delta'],results[it['name']]['spread'],len(good),'/',len(anchors),flush=True)
