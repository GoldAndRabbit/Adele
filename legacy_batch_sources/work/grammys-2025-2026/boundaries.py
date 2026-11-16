import sys,re,json
from pathlib import Path
sys.path[:0]=[str(Path.cwd()),str(Path.cwd()/'workflow')]
import pysubs2
from workflow.live.paths import Concert,read_json,write_json
from workflow.live.lyrics import guess_lang
ranges={2025:[(172,350),(720,944),(1164,1436),(2500,2785),(3105,3184),(3280,3468),(3476,3658),(3660,3822),(3825,4008),(4010,4160),(4683,4860),(5246,5500),None,(7363,7600),(8125,8395),(9400,9675)],2026:[(0,195),(651,880),(1273,1404),(1446,1555),(1555,1710),(1725,1826),(1838,1980),(1980,2115),(2115,2241),(2241,2380),(2883,3080),(3813,4060),(4458,4690),(5487,5811),(6443,6697),(6740,7000),None,(8672,8904)]}
for y,spans in ranges.items():
 c=Concert(f'grammys_{y}');subs=pysubs2.load(c.captions);items=c.load('setlist');segs=[]
 for it,span in zip(items['items'],spans):
  if not span:continue
  a,b=span;d=c.song_dir(it);song=read_json(d/'song.json');song.update(slice=[a,b],preview=[a,b],source_file=c.load('info')['source_file'],source_review='pending',boundary_evidence='embedded broadcast captions; padded provisional range; review intro/outro')
  write_json(d/'song.json',song)
  # The embedded closed-caption track is a source-owned reference, not generated lyrics.
  events=[e for e in subs if a*1000<=e.start<b*1000];out=[];prev=[]
  for e in events:
   text=e.plaintext
   if '♪' not in text and '♫' not in text:continue
   text=re.sub(r'\[[^]]*\]','',text)
   text=re.split(r'>>\s*[A-Za-z][A-Za-z .]*:',text)[0]
   if '>>' in text:
    pieces=text.split('>>');text=' '.join(p for p in pieces if '♪' in p or '♫' in p)
   text=re.sub(r'[♪♫]',' ',text);cur=text.split()
   overlap=next((n for n in range(min(len(prev),len(cur)),0,-1) if prev[-n:]==cur[:n]),0)
   fresh=cur[overlap:]
   if fresh:out.append(' '.join(fresh))
   if cur:prev=cur
  if not (d/'lyrics.txt').is_file():
   (d/'lyrics.txt').write_text('\n'.join(out)+'\n');(d/'lyrics_sections.txt').write_text('\n'.join(out)+'\n');(d/'lyrics_source').write_text('broadcast_closed_captions')
   write_json(d/'caption_reference.json',dict(source=str(c.captions),range=[a,b],human_approved=False,note='Broadcast captions may contain omissions or transcription errors. Verify against original audio; not a completed subtitle.'))
   song['lang']=guess_lang('\n'.join(out));write_json(d/'song.json',song)
  segs.append(dict(idx=it['idx'],name=it['name'],title=it['title'],kind='song',start=a,end=b,confidence=0.5,review='pending',boundary_locked=True,flags=['根据片源字幕初步定位，首尾和联唱分界待人工复核']))
 write_json(c.segments,dict(items=segs,gaps=[]))
 print(y,'provisional ranges',len(segs))
