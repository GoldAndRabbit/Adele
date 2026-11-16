import os,json,subprocess
from pathlib import Path
import numpy as np
from dotenv import load_dotenv
from workflow.live.asr_match import asr_words
load_dotenv('.env');b=Path('work/angel-hammersmith');p=b/'review-source.mp4'
for t,length in [(0,28),(281,29)]:
 wav=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-ss',str(t),'-i',str(p),'-t',str(length),'-vn','-ar','16000','-ac','1','-f','f32le','-']),dtype='<f4')
 words=asr_words(wav,16000,os.environ['ALIYUN_BAILIAN_API_KEY'],b/'extras-cache.json',t);(b/f'words-{t}.json').write_text(json.dumps(words))
 print(t, ' '.join(v['w'] for v in words))
