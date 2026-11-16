"""Map recognized word times to lyric lines; leave unsupported lines untimed."""
import json,re
from pathlib import Path
from rapidfuzz.distance import Levenshtein
from opencc import OpenCC
from pypinyin import lazy_pinyin
cc=OpenCC('t2s');norm=lambda s:''.join(re.findall(r'[\u4e00-\u9fffA-Za-z0-9]',cc.convert(s).replace('33','三十三').replace('13','十三').replace('10','十'))).lower()
root=Path('/Users/gold/.codex/visualizations/2026/11/04/01a1a53c-553d-7a60-bb22-c5e7c5f7f7da/angel-local/dist')
rows=json.loads((root/'recordings.json').read_text())
for t in rows:
 uid=t['url'].split('/')[-1];p=Path(__file__).parent/(uid+'-asr.json')
 if not p.exists():continue
 asr=json.loads(p.read_text());chars=[];times=[]
 for seg in asr['segments']:
  for w in seg.get('words',[]):
   for c in norm(w['word']):chars.append(c);times.append((w['start'],w['end']))
 lines=[x.strip() for x in t['generation']['lyrics'].splitlines() if x.strip() and not x.startswith('[')]
 ref=''.join(norm(x) for x in lines);heard=''.join(chars);mapping={}
 for op in Levenshtein.opcodes(lazy_pinyin(ref),lazy_pinyin(heard)):
  if op.tag=='equal':
   for a,b in zip(range(op.src_start,op.src_end),range(op.dest_start,op.dest_end)):mapping[a]=b
 result=[];cursor=0
 for line in lines:
  s=norm(line);hits=[mapping[i] for i in range(cursor,cursor+len(s)) if i in mapping];coverage=len(hits)/max(1,len(s));entry={'text':line,'coverage':round(coverage,3)}
  if hits and coverage>=.6:
   start=times[hits[0]][0];end=times[hits[-1]][1]
   if .25<end-start<20:entry.update(start=start,end=end)
  result.append(entry);cursor+=len(s)
 t['timings']=result;t['timingMethod']='mlx-whisper large-v3 word timestamps + sequential lyric matching'
 (Path(__file__).parent/(uid+'-alignment.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2))
 print(t['title'],sum('start'in x for x in result),'/',len(result))
 for x in result:print(x.get('start','?'),x.get('end','?'),x['coverage'],x['text'])
(root/'recordings.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2))
