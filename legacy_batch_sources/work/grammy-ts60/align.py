import json
from pathlib import Path
import subprocess
import numpy as np
from scipy import signal
from workflow.live.paths import Concert,read_json
base=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014')
pcm=np.memmap(base/'ts60-invisible/ts-track.s16',dtype='<i2',mode='r')
def features(y):
    w=np.lib.stride_tricks.sliding_window_view(y,512)[::400]
    bins=np.round(np.geomspace(50,3800,19)/(8000/512)).astype(int)
    rows=[]
    for j in range(0,len(w),2048):
        ft=np.abs(np.fft.rfft(w[j:j+2048]*np.hanning(512),axis=1))
        band=np.stack([np.log1p(ft[:,a:max(a+1,b)].mean(axis=1)) for a,b in zip(bins,bins[1:])],axis=1)
        rows.append(band-band.mean(axis=1,keepdims=True))
    return np.concatenate(rows).astype('float32')
X=np.concatenate([features(np.asarray(pcm[s:s+4800112],np.float32)/32768) for s in range(0,len(pcm)-512,4800000)])
c=Concert('grammys_2014')
src=c.load('info')['source_file']
results={}
for p in sorted(c.dir.glob('songs/*/song.json')):
    song=read_json(p); name=song['name']; a,b=song['slice']; lead=read_json(p.parent/'vertical/release.json')['start']
    a+=lead; dur=b-a
    audio=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-ss',str(a),'-i',src,'-t',str(dur),'-vn','-ar','8000','-ac','1','-f','s16le','-']),'<i2').astype(np.float32)/32768
    # Search within the neighbouring broadcast segment. A wide window covers the known differences between edits.
    lo=max(0,int((a-900)*20)); hi=min(len(X),int((b+900)*20)); seg=X[lo:hi]; pw=np.r_[0,np.cumsum((seg**2).sum(axis=1),dtype='float64')]
    anchors=[]
    for t in sorted(set([0,1,4,*range(8,int(dur)-4,8),int(dur)-5])):
        y=features(audio[t*8000:(t+4)*8000]); n=len(y)
        z=sum(signal.correlate(seg[:,j],y[:,j],method='fft',mode='valid') for j in range(18))
        energy=pw[n:]-pw[:-n]; z/=np.sqrt(np.maximum(energy*(y*y).sum(),1e-8))
        k=int(z.argmax()); anchors.append([t,round((k+lo)/20-t,3),round(float(z[k]),3)])
    results[name]=dict(begin=a,duration=dur,lead=lead,anchors=anchors)
    out=Path('work/grammy-ts60/alignment.json'); tmp=out.with_suffix('.tmp'); tmp.write_text(json.dumps(results,indent=1));tmp.replace(out)
    from collections import Counter
    print(name,Counter(round(offset,1) for _,offset,q in anchors if q>=.79).most_common(3),flush=True)
