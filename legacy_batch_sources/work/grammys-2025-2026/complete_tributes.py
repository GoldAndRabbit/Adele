import sys,re
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'workflow')]
import pysubs2
from workflow.live.paths import Concert,read_json,write_json
for year,idx,a,b in [(2025,13,5860,7026),(2026,17,7024,7750)]:
 c=Concert(f'grammys_{year}');it=c.item(idx);d=c.song_dir(it);data=c.load('segments');segments=data['items']
 if not any(s['name']==it['name'] for s in segments):
  segments.append(dict(idx=idx,name=it['name'],title=it['title'],kind='song',start=a,end=b,confidence=0.8,review='pending',flags=['已核对广播字幕与边界画面；完整保留致敬串烧及段内介绍，待人工审核']))
 if year==2026:
  for s in segments:
   if s['idx']==16:s['end']=7024;s['flags']=['已延长至完整吉他尾奏后，待人工审核']
  war=c.song_dir(c.item(16));info=read_json(war/'song.json');info.update(slice=[6740,7024],preview=[6740,7024]);write_json(war/'song.json',info)
 segments.sort(key=lambda s:s['idx']);write_json(c.segments,data)
 info=read_json(d/'song.json');info.update(slice=[a,b],preview=[a,b],source_file=c.load('info')['source_file'],lang='en',source_review='pending');write_json(d/'song.json',info)
 out=[];prev=[]
 for e in pysubs2.load(c.captions):
  if not a*1000<=e.start<b*1000:continue
  text=e.plaintext
  if '♪' not in text and '♫' not in text:continue
  text=re.sub(r'\[[^]]*\]','',text);text=re.split(r'>>\s*[A-Za-z][A-Za-z .]*:',text)[0]
  if '>>' in text:text=' '.join(p for p in text.split('>>') if '♪' in p or '♫' in p)
  cur=re.sub(r'[♪♫]',' ',text).split();k=next((n for n in range(min(len(prev),len(cur)),0,-1) if prev[-n:]==cur[:n]),0)
  if cur[k:]:out.append(' '.join(cur[k:]))
  if cur:prev=cur
 for f in ['lyrics.txt','lyrics_sections.txt']:(d/f).write_text('\n'.join(out)+'\n')
 (d/'lyrics_source').write_text('broadcast_closed_captions')
 write_json(d/'caption_reference.json',dict(source=str(c.captions),range=[a,b],human_approved=False,note='Broadcast caption reference; ASR must verify lyrics and segment introductions.'))
 status=Path('work/grammys-2025-2026/status')/f'{c.slug}--{it["name"]}.json';r=read_json(status,{});r.update(status='queued',stage='boundary_frames_checked',boundary_review='pending');write_json(status,r)
 print(year,it['name'],a,b,len(out),'reference fragments')
