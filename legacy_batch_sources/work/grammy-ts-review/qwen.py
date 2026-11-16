import os,json
from pathlib import Path
from dotenv import load_dotenv
from scipy.signal import resample_poly
import numpy as np
from openai import OpenAI
from workflow.qwen_asr import transcribe,ENDPOINT
from workflow.live.asr_match import asr_words
from concurrent.futures import ThreadPoolExecutor
load_dotenv()
pcm=np.memmap('/Volumes/harddisk_5T/adele-workflow/vertical-reviews/grammys_2014/ts60-invisible/ts-track.s16',dtype='<i2',mode='r')
out=Path('work/grammy-ts-review')
key=os.environ['ALIYUN_BAILIAN_API_KEY']
def job(item):
 n,t,d=item;y=resample_poly(pcm[round(t*8000):round((t+d)*8000)].astype(np.float32)/32768,2,1)
 words=asr_words(y,16000,key,out/(n+'.qwen-cache.json'),t0=t)
 (out/(n+'.qwen.json')).write_text(json.dumps(words,indent=1))
 print(n,' '.join(w['w'] for w in words),flush=True)
with ThreadPoolExecutor(max_workers=3) as ex:
 list(ex.map(job,[('invisible-head',1243,30),('one-intro',7284.488,45),('one-join1',7448,20),('one-join2',7578,15),('pink-head',3415,20)]))
