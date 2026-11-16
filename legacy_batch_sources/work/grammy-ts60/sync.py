import json,subprocess as sp
from pathlib import Path
import numpy as np
from scipy import signal
from workflow.live.paths import Concert
c=Concert('grammys_2014')
wd=Path('work/grammy-ts60')
ts=np.memmap('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/ts60-invisible/ts-track.s16',dtype='<i2',mode='r')
records={}
for name,rec in json.loads((wd/'alignment.json').read_text()).items():
    dur=rec['duration']; begin=rec['begin']
    anchors=np.array(rec['anchors']); offsets=anchors[anchors[:,2]>.68,1]
    if not len(offsets): offsets=anchors[:,1]
    g=max(offsets,key=lambda o:np.count_nonzero(abs(offsets-o)<.2))
    guess=np.median(offsets[abs(offsets-g)<.2])
    audio=np.frombuffer(sp.check_output(['ffmpeg','-v','error','-ss',str(begin),'-i',c.load('info')['source_file'],'-t',str(dur),'-vn','-ar','8000','-ac','1','-f','s16le','-']),'<i2').astype('float32')/32768
    scan=[]
    for t in sorted(set([0,*range(2,int(dur)-2,2),max(0,int(dur)-3)])):
        y=audio[t*8000:(t+2)*8000]; start=round((guess+t-.5)*8000)
        x=ts[start:start+len(y)+8000].astype(np.float64)/32768
        if len(x)<len(y): continue
        z=signal.correlate(x,y,mode='valid',method='fft'); pw=np.r_[0.,np.cumsum(x*x)]
        z/=np.sqrt(np.maximum((pw[len(y):]-pw[:-len(y)])*(y*y).sum(),1e-10)); k=abs(z).argmax(); scan.append([t, round((start+k)/8000-t,4),round(abs(z[k]),3)])
    m=[b for t,b,q in scan if q>=.34]
    offset=round(float(np.median(m)),4) if m else guess
    bad=[t for t,b,q in scan if q<.25 or abs(b-offset)>.12]; records[name]={**{k:rec[k] for k in ('begin','lead','duration')},'offset':offset,'bad':bad,'scan':scan}
    print(name,offset,'bad',bad,flush=True)
(wd/'sync.json').write_text(json.dumps(records,indent=1))
