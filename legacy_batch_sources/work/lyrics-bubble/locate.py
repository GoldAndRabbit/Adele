import sys,os,json
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'workflow')]
import soundfile as sf
from workflow.live.asr_match import asr_words
p=Path('work/lyrics-bubble');y,sr=sf.read(p/'first60.wav')
w=asr_words(y,sr,os.environ['ALIYUN_BAILIAN_API_KEY'],p/'asr_cache.json')
(p/'words.json').write_text(json.dumps(w,ensure_ascii=False,indent=2))
print('recognized words',len(w))
for x in w:
 if any(k in x['w'].lower() for k in ['passe','crochet','kylian','acc','virg','tire','gauch','ousmane']): print(x)
