import mlx_whisper,numpy as np,json
from scipy.signal import resample_poly
from pathlib import Path
p=Path('work/grammy-ts60')
pcm=np.memmap('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/ts60-invisible/ts-track.s16',dtype='<i2',mode='r')
model=str(Path.home()/'.cache/whisper/mlx-large-v3')
for name,t,dur in [('invisible',1235,50),('pink',3375,75),('one',7444,35),('chicago',2260,19)]:
 arr=resample_poly(pcm[t*8000:(t+dur)*8000].astype(np.float32)/32768,2,1)
 result=mlx_whisper.transcribe(arr,path_or_hf_repo=model,language='en',word_timestamps=True,condition_on_previous_text=False)
 (p/(name+'.words.json')).write_text(json.dumps(result['segments'],indent=1,default=float))
 print(name,[(round(t+s['start'],1),s['text']) for s in result['segments']],flush=True)
