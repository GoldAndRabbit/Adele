import sys,json,re,os
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'workflow')]
import torch,numpy as np,soundfile as sf
from workflow.refine_timing import load_model,emission_full,romanize
p=Path('work/lyrics-bubble')
lines=[('Passement de jambe','跨步假动作'),('Crochet à gauche, à droite','向左变向，再向右'),('Kylian Mbappé','基利安·姆巴佩'),('Accélération, virgule,','加速、甩牛尾巴'),('petit-pont, frappe','穿裆，射门'),('Kylian Mbappé','基利安·姆巴佩'),("J’sais plus si j’suis gaucher",'我已分不清自己惯用左脚'),('ou droitier','还是右脚'),('Je tire des deux pieds,','我双脚都能射门'),('Ousmane Dembélé','奥斯曼·登贝莱')]
torch.set_num_threads(4); y,sr=sf.read(p/'align.wav'); print('loading model',flush=True)
model,tok,aligner=load_model();em,fr=emission_full(model,y.astype(np.float32));print('emissions ready',flush=True)
words=['*']; owners=[None]
for li,(frtext,zh) in enumerate(lines):
 for m in re.finditer(r"[^\W\d_]+(?:[’'][^\W\d_]+)*",frtext):
  norm=romanize(m.group(),'fr')
  if norm:words.append(norm[0]);owners.append((li,m.start(),m.end()))
 words.append('*');owners.append(None)
spans=aligner(em,tok(words));aligned=[]
for sp,own,word in zip(spans,owners,words):
 if own is None or not sp:continue
 aligned.append({'line':own[0],'char_start':own[1],'char_end':own[2],'start':sp[0].start/fr,'end':sp[-1].end/fr,'score':float(np.mean([x.score for x in sp]))})
result={'source_start':70.5,'duration':13.4,'lines':[{'fr':a,'zh':b} for a,b in lines],'words':aligned,'method':'MMS forced alignment of user-provided lyrics; Qwen ASR used only to locate passage'}
(p/'alignment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
for li in range(len(lines)):
 w=[x for x in aligned if x['line']==li]; print(li,round(w[0]['start'],3),round(w[-1]['end'],3),round(np.mean([x['score'] for x in w]),3),flush=True)
