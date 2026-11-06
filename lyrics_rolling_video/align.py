import sys,json,re,os
from pathlib import Path
BASE=Path(__file__).resolve().parent
sys.path[:0]=[str(BASE.parent),str(BASE.parent/'workflow')]
import torch,numpy as np,soundfile as sf
from workflow.refine_timing import load_model,emission_full,romanize
p=BASE
config=json.loads((p/'config.json').read_text())
lines=[(x['fr'],x['zh']) for x in config['lines']]
torch.set_num_threads(4); y,sr=sf.read(p/'data/align.wav'); print('loading model',flush=True)
assert sr==16000 and y.ndim==1, '对齐输入须为 16 kHz 单声道'
assert abs(len(y)/sr-config['duration'])<.05, '音频不足配置时长，请检查起点、时长和源文件'
model,tok,aligner=load_model();em,fr=emission_full(model,y.astype(np.float32));print('emissions ready',flush=True)
words=['*']; owners=[None]
for li,(frtext,zh) in enumerate(lines):
 for m in re.finditer(r"[^\W\d_]+(?:[’'][^\W\d_]+)*",frtext):
  norm=romanize(m.group(),config['language'])
  if norm:words.append(norm[0]);owners.append((li,m.start(),m.end()))
 words.append('*');owners.append(None)
spans=aligner(em,tok(words));aligned=[]
for sp,own,word in zip(spans,owners,words):
 if own is None or not sp:continue
 aligned.append({'line':own[0],'char_start':own[1],'char_end':own[2],'start':sp[0].start/fr,'end':sp[-1].end/fr,'score':float(np.mean([x.score for x in sp]))})
result={'source_start':config['source_start'],'duration':config['duration'],'lines':[{'fr':a,'zh':b} for a,b in lines],'words':aligned,'method':'MMS forced alignment of user-provided lyrics; Qwen ASR used only to locate passage'}
(p/'alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
for li in range(len(lines)):
 w=[x for x in aligned if x['line']==li]; print(li,round(w[0]['start'],3),round(w[-1]['end'],3),round(np.mean([x['score'] for x in w]),3),flush=True)
