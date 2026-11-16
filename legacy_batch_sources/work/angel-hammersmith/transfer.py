import json,copy
from pathlib import Path
from workflow.live.paths import read_json as rd,write_json as wr
from workflow.song.song_translation_workflow import build_outputs
import pysubs2
base=Path('work/angel-hammersmith');parent=Path('posts/the_angel_gunnertv');d=Path('posts/the_angel_hammersmith_5gu277dbf8i');src=parent/'subs';out=d/'subs';(out/'translation').mkdir(parents=True,exist_ok=True)
offsets=rd(base/'offset.json');assert len(offsets)==266 and all(abs(o-23.565)<.002 and q>.5 for t,o,q in offsets)
ms=23565
R=rd(src/'translation/result.json');L=rd(src/'lines.json')
for u in R['units']:u['start']+=ms;u['end']+=ms
for line in L:
 for k in ('start_ms','end_ms'):
  if line.get(k)!=None:line[k]+=ms
W=rd(base/'words-0.json')
extra=[(0,15,'This song I wrote in my bedroom as a little love letter to my hometown.','我在卧室里写下这首歌，当作献给家乡的一封小情书。'),(15,27,"What it’s gone on to be is nothing to do with me.",'它后来能走到今天，功劳不在我。'),(27,35,"And it’s all to do with you lot.",'这全是因为你们。'),(35,44,'So thank you from the bottom of my heart.','所以，我打心底里谢谢你们。'),(44,50,'Thank you all for being here.','谢谢大家来到这里。'),(50,61,'This has been one of the best nights of my life.','这是我一生中最美好的夜晚之一。'),(61,65,'I’ll never forget it.','我永远不会忘记。'),(65,69,'Be lucky, Hammersmith.','哈默史密斯，祝你们好运。'),(69,73,'I’ll see you soon.','我们很快再见。')]
notes={u['i']:R.get('final_notes',{}).get(str(u['i'])) for u in R['units']}
for start,end,en,zh in extra:
 words=W[start:end];t0=round(words[0]['s']*1000);t1=round(words[-1]['e']*1000);heard=' '.join(w['w'] for w in words)
 R['units'].append(dict(i=-1,start=t0,end=t1,orig=en,heard=heard,type='讲话',verdict='ok',v1=zh,v2=zh,v3=zh,issues=[]))
 L.append(dict(start_ms=t0,end_ms=t1,text=en,genius='',qwen=heard,lang='en',speech=True,removed=False,style='speech',verdict='ok',strategy='本场片头讲话，按原声识别单独对齐'))
R['units'].sort(key=lambda u:u['start']);new_notes={}
for i,u in enumerate(R['units']):
 note=notes.get(u['i'])
 if note:new_notes[str(i)]=note
 u['i']=i
R.update(notes=new_notes,final_notes=new_notes);wr(out/'translation/result.json',R);wr(out/'lines.json',sorted(L,key=lambda r:r['start_ms']))
prof=rd(src/'profile.json');prof.update(alignment_source='与 GunnerTV 配乐逐秒核对后复用，片头讲话单独识别',audio_offset_ms=ms);wr(out/'profile.json',prof)
build_outputs(d,out)
for f in ('lyrics.srt','speech.srt'):
 s=pysubs2.load(src/f);s.shift(ms=ms)
 if f=='speech.srt':
  for u in R['units'][:len(extra)]:s.append(pysubs2.SSAEvent(start=u['start'],end=u['end'],text=u['orig']))
 s.sort();s.save(out/f)
