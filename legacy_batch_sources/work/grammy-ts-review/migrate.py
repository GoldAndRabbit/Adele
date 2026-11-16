import json,copy,shutil,subprocess as sp,sys,re
from pathlib import Path
import pysubs2
from workflow.live.paths import Concert,read_json,write_json
from extract import bounds,S,D
C=Concert('grammys_2014')
work=Path('work/grammy-ts-review')
sync=read_json('work/grammy-ts60/sync.json')
# Each range is on the original full-song clock. Its offset maps to the TS broadcast clock.
maps={
'03_invisible':[(0,8.6,1245.028-2.16),(41.26,217.5,1228.324-2.16)],
'09_try_just_give_me_a_reason':[(42.32,345,3378.8116-4.12)],
'17_one':[(0,169.0,7373.728-89.24),(201.74,203.74,7341.248-89.24),(203.74,330.0,7341.696-89.24),(333.0,370.5,7338.848-89.24)],
'05_does_anybody_really_know_what_ti':[(0,260,2023.1212-7.66)],
}
# Audible opening-verse phrases use the new TS word timings.
manual=[
 (8.70,1251.66,1252.83),(11.84,1252.83,1255.45),
 (20.64,1257.22,1258.81),(24.32,1258.81,1260.35),
 (27.18,1260.38,1261.99),(30.28,1262.0,1265.05),
 (37.84,1265.78,1267.72),
]
def interval(name,a,b):
 start,end=bounds[name]
 if name=="09_try_just_give_me_a_reason" and a<42.32:return None
 if name=='03_invisible':
  for old,left,right in manual:
   if abs(a-old)<.20:return max(0,left-start),min(end-start,right-start),True
 pieces=[]
 for lo,hi,offset in maps[name]:
  aa,bb=max(a,lo),min(b,hi)
  if bb>aa:pieces.append((bb-aa,max(0,aa+offset-start),min(end-start,bb+offset-start)))
 pieces=[p for p in pieces if p[2]-p[1]>.08]
 if not pieces:return None
 _,aa,bb=max(pieces)
 return aa,bb,(b-a)-(bb-aa)>.12
def migrate(name):
 song=C.song_dir(C.item(name));bak=work/'original-metadata'/name
 if (song/'ts-review-migrated.json').exists():return
 if not (D/name/'source.mp4').is_file():raise ValueError('Clean TS input not ready')
 bak.mkdir(exist_ok=True,parents=True)
 for f in ['song.json','watermark.json','content_box.json']:
  if (song/f).exists() and not (bak/f).exists():shutil.copy2(song/f,bak/f)
 if not (bak/'subs').exists():shutil.copytree(song/'subs',bak/'subs')
 old=read_json(bak/'song.json'); start,end=bounds[name];duration=end-start
 ass=pysubs2.load(str(bak/'subs/lyrics_poetic.ass'))
 new_events=[];mapping={}
 for i,event in enumerate(ass):
  if event.is_comment or event.plaintext.startswith('《'):continue
  iv=interval(name,event.start/1000,event.end/1000)
  if iv is None:continue
  aa,bb,partial=iv; e=event.copy();e.start=round(aa*1000);e.end=round(bb*1000)
  if e.end<=e.start:continue
  mapping[event.start]=(e.start,e.end,partial)
  new_events.append(e)
 if name=='09_try_just_give_me_a_reason':
  new_events.insert(0,pysubs2.SSAEvent(start=1200,end=3890,text="Doesn't mean you're gonna die"+r"\N"+"也不意味着你会死去"))
 new_events.sort(key=lambda e:e.start);ass.events=new_events
 for variant in ['lyrics.ass','lyrics_literal.ass','lyrics_poetic.ass']:
  src=pysubs2.load(str(bak/'subs'/variant));events=[]
  for e in src:
   if e.start not in mapping:continue
   a,b,_=mapping[e.start];n=e.copy();n.start=a;n.end=b;events.append(n)
  if name=='09_try_just_give_me_a_reason':events.insert(0,new_events[0].copy())
  src.events=sorted(events,key=lambda e:e.start);src.save(str(song/'subs'/variant))
 ass.save(str(song/'subs/lyrics.srt'))
 words=[]
 for f in sorted(work.glob(name+'-*.qwen.json')):
  words+=read_json(f)
 words.sort(key=lambda w:w['s'])
 for word in words:
  word['s']-=start;word['e']-=start;word['src']='TS-Qwen'
 rows=[];oldrows=read_json(bak/'subs/lines.json',[])
 for e in new_events:
  text=e.plaintext.splitlines()[0].strip()
  original=next((r for r in oldrows if (r.get('text') or '').strip()==text),{})
  row=copy.deepcopy(original)
  row.update(start_ms=e.start,end_ms=e.end,text=text,genius=original.get('genius',text),
             qwen=' '.join(w['w'] for w in words if e.start/1000-.2<=w['s']<e.end/1000),
             lang='en',removed=False,anchor=False,agree=[],conf=None,verdict='unconfirmed',
             strategy='以新TS音轨重排，待人工审核；保留原翻译。',source='56th_TS',speech=original.get('speech',False))
  if name=='03_invisible' and 8<e.start/1000<26:row['strategy']='TS剪接处逐句识别重排，词句完整性请人工核对。'
  if name=='09_try_just_give_me_a_reason' and e.start<3500:row['strategy']='TS从半句切入，只保留实际听到的后半句，待人工审核。'
  rows.append(row)
 write_json(song/'subs/lines.json',rows)
 for f in (song/'subs').glob('asr_words_*.json'):f.unlink()
 write_json(song/'subs/asr_words_1.json',words)
 profile=read_json(bak/'subs/profile.json',{});profile.update(reads=1,cut_sets=[],rounds=[],source='56th_TS',review='pending')
 write_json(song/'subs/profile.json',profile)
 tr=read_json(bak/'subs/translation/result.json',{})
 units=[]
 for u in tr.get('units',[]):
  iv=interval(name,u['start']/1000,u.get('end',u['start']+1000)/1000)
  if not iv:continue
  v=copy.deepcopy(u);v['start']=round(iv[0]*1000);v['end']=round(iv[1]*1000);units.append(v)
 tr['units']=units;tr['ts_review']='pending';write_json(song/'subs/translation/result.json',tr)
 for f in ['crowd.json','crowd_vision.json','talk_sentences.json']:
  path=song/'subs'/f
  if path.exists():path.unlink()
 wm=read_json(bak/'watermark.json',{});items=[]
 for m in wm.get('items',[]):
  iv=interval(name,m['t'],m['t']+m['dur'])
  if iv:
   m=copy.deepcopy(m);m['t']=iv[0];m['dur']=iv[1]-iv[0];items.append(m)
 wm['items']=items;write_json(song/'watermark.json',wm)
 info=copy.deepcopy(old);info.update(slice=[start,end],preview=[start,end],source_file=str(S),vertical_preview_fps=50,source_review='pending',source_note='TS片源 · 字幕已重新对齐 · 待人工审核')
 # Remove just the requested old-source previews. Existing published releases stay outside this review.
 for path in [song/'preview.mp4',song/'vertical/full.mp4',*list((song/'vertical').glob('preview-*.mp4'))]:
  path.unlink(missing_ok=True)
 (song/'preview.mp4').symlink_to(D/name/'source.mp4')
 # Avoid future use of the old audio by the subtitle pipeline.
 for path in [song/'audio.flac',song/'vocals.wav']:
  if path.exists() or path.is_symlink():shutil.move(str(path),str(bak/path.name))
 sp.run(['ffmpeg','-v','error','-y','-i',D/name/'source.mp4','-vn','-c:a','flac',song/'audio.flac'],check=True)
 write_json(song/'song.json',info)
 write_json(song/'ts-review-migrated.json',{'source':str(S),'source_slice':[start,end],'original_metadata':str(bak.resolve()),'review':'pending'})
 print('MIGRATED',name,len(rows),'rows',duration,flush=True)
if __name__=='__main__':migrate(sys.argv[1])
