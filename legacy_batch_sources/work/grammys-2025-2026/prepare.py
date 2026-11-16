import sys,json,traceback,subprocess,os
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
ROOT=Path('/Users/gold/repos/adele');sys.path[:0]=[str(ROOT),str(ROOT/'workflow')];os.chdir(ROOT)
from workflow.live.paths import Concert,read_json,write_json
from workflow.live.lyrics import fetch_part,guess_lang
from workflow.live.segment import stage_segment
from llm import load_env
import requests
load_env();base=ROOT/'work/grammys-2025-2026'
def state(y,**kw):write_json(base/f'{y}-status.json',dict(year=y,updated=datetime.now().isoformat(),**kw))
for year in (2025,2026):
 c=Concert(f'grammys_{year}');fail=[]
 session=requests.Session();session.headers['User-Agent']='Mozilla/5.0'
 for it in c.song_items():
  if (base/'PAUSED').exists():sys.exit(0)
  d=c.song_dir(it);state(year,stage='reference_lyrics',song=it['title'],failures=fail)
  if (d/'lyrics.txt').exists():continue
  lookup=it.get('lyrics_lookup_artist')
  if not lookup:fail.append({'song':it['name'],'reason':'tribute needs per-part performer/reference mapping'});continue
  try:
   texts=[];secs=[];urls=[];facts=[]
   for title in it['parts']:
    url,plain,sec,fact=fetch_part(session,title,lookup);texts.append(plain);secs.append(sec);urls.append(url);facts.append(fact)
   (d/'lyrics.txt').write_text('\n\n\n'.join(texts)+'\n');(d/'lyrics_sections.txt').write_text('\n\n'.join(secs)+'\n');(d/'lyrics_source').write_text('reference')
   song=read_json(d/'song.json',{});song.update(genius_urls=urls,genius=facts,lang=guess_lang('\n'.join(texts)));write_json(d/'song.json',song)
   print(year,it['name'],'reference ready',flush=True)
  except Exception as e:
   fail.append({'song':it['name'],'reason':str(e)});print(year,it['name'],'FAILED',str(e),flush=True)
 state(year,stage='locating_broadcast_boundaries',failures=fail)
 try:stage_segment(c,SimpleNamespace(force=False,songs=None))
 except Exception as e:fail.append({'stage':'segment','reason':str(e)});traceback.print_exc()
 state(year,stage='awaiting_boundary_verification',failures=fail)
 print(year,'initial segmentation complete; NOT yet approved',flush=True)
