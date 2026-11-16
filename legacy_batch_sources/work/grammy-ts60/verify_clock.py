"""Compare audio decoded from the finished release with the sequential TS timebase."""
import subprocess
import numpy as np
from scipy.signal import correlate
from pathlib import Path
PCM=Path('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/ts60-invisible/ts-track.s16')
def verify_audio_clock(path,start,duration):
    ts=np.memmap(PCM,dtype='<i2',mode='r')
    for t in [2,duration*.25,duration*.52,duration*.77,duration-5]:
        raw=subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(path),'-vn','-t','2','-ac','1','-ar','8000','-f','s16le','-'])
        y=np.frombuffer(raw,'<i2').astype(float)/32768
        sample=round((start+t-.25)*8000)
        x=ts[sample:sample+len(y)+4000].astype(float)/32768
        pw=np.r_[0.,np.cumsum(x*x)]
        scores=correlate(x,y,mode='valid',method='fft')/np.sqrt(np.maximum((pw[len(y):]-pw[:-len(y)])*(y*y).sum(),1e-12))
        k=int(np.argmax(scores)); error=k/8000-.25
        if scores[k]<.65 or abs(error)>.08:
            raise ValueError(f'TS audio check at {t:.2f}s, offset {error:.3f}s, correlation {scores[k]:.3f}')
