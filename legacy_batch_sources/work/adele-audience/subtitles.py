"""Use the broadcast's synchronized English captions as the source text for the reviewed cut."""
from workflow.live.paths import *
from workflow.song.song_translation_workflow import translate
from workflow.song.watermark import ensure_song
import pysubs2
from concurrent.futures import ThreadPoolExecutor
import re,traceback,sys
c=Concert('an_audience_with_adele_2021')
segments={i['name']:i for i in c.load('segments')['items']}
items=[c.item(x) for x in sys.argv[1:]] if len(sys.argv)>1 else c.song_items()
captions=list(pysubs2.load(str(c.captions)))
for it in items:
 d=c.song_dir(it);(d/'subs').mkdir(exist_ok=True);seg=segments[it['name']]
 a,b=seg['start'],seg['end']
 draft={'song':{'title':it['title'],'artist':'Adele','artist_zh':'阿黛尔'},'performance':{'event':'2021年阿黛尔伦敦帕拉迪姆剧院现场','date':'2021-11-06'},'title':f"阿黛尔 {it['title']} 2021伦敦现场",'intro_text':f"阿黛尔在伦敦帕拉迪姆剧院演唱《{it['title']}》，选自 ITV 节目《An Audience with Adele》。"}
 write_json(d/'post_draft.json',draft)
 singing=False;rows=[];ly=pysubs2.SSAFile();sp=pysubs2.SSAFile()
 for e in captions:
  if not a<=e.start/1000<b:continue
  t=e.plaintext.strip()
  if t.startswith('♪'):singing=True
  is_lyric=singing and not t.isupper() and not t.startswith(('MUSIC','CHEERING','APPLAUSE','WHISTLING'))
  if t.endswith('♪'):singing=False
  if not is_lyric and (t.isupper() or t.startswith(('MUSIC:',"(", 'CHEERING','APPLAUSE'))):continue
  text=t.replace('♪','').strip()
  if not text:continue
  start=e.start-round(a*1000);end=min(e.end,round(b*1000))-round(a*1000)
  if end<=start:continue
  (ly if is_lyric else sp).events.append(pysubs2.SSAEvent(start=start,end=end,text=text))
  rows.append({'start_ms':start,'end_ms':end,'genius':'','qwen':'','text':text,'lang':'en','speech':not is_lyric,'verdict':'live' if is_lyric else 'speech','removed':False,'agree':['ITV'],'style':'sing' if is_lyric else 'talk','anchor':is_lyric,'strategy':'原片 ITV 同步播出字幕，已按本曲验证范围换算时间'})
 assert len(ly)>10,(it['name'],len(ly))
 ly.save(str(d/'subs/lyrics.srt'))
 if len(sp):sp.save(str(d/'subs/speech.srt'))
 else:(d/'subs/speech.srt').unlink(missing_ok=True)
 write_json(d/'subs/lines.json',rows)
 write_json(d/'subs/profile.json',{'source':'ITV English broadcast captions','main':'en','langs':['en'],'reads':0,'rounds':[]})
 (d/'lyrics.txt').write_text('\n'.join(e.plaintext for e in ly)+'\n')
def make(it):
 d=c.song_dir(it);out=d/'subs'
 try:
  if not (out/'lyrics_poetic.ass').exists():
   translate(d,out,(d/'lyrics.txt').read_text().splitlines(),f"《{it['title']}》 Adele")
  ev=pysubs2.load(str(out/'lyrics_poetic.ass'))
  assert any(e.style=='Default' and re.search(r'[\u3400-\u9fff]',e.text) for e in ev)
  ensure_song(c.slug,it['name'])
  print('SUB_READY',it['name'],flush=True)
 except Exception:print('SUB_FAIL',it['name'],traceback.format_exc(),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(make,items))
