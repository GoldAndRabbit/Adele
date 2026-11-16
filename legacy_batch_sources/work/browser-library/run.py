import json,traceback,fcntl
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from workflow.live.paths import *
from workflow.browser_library import prepare_browser
from workflow.vertical_workflow import candidates
from workflow.vertical_cover import header_labels
from workflow.vertical_post import *
from workflow.song.watermark import ensure_song
from PIL import Image
base=ROOT/'work/browser-library'
items=[]
for group in sorted(CONCERTS.iterdir()):
 if not group.is_dir() or group.name in ['grammys_2014','an_audience_with_adele_2021']:continue
 c=Concert(group.name)
 for it in c.song_items():
  if not it.get('review_hidden'):items.append((c,it))

def process(pair):
 c,it=pair;d=c.song_dir(it);f=d/'vertical';status=base/'status'/f'{c.slug}--{it["name"]}.json'
 def state(value,**extra):write_json(status,{'status':value,'concert':c.slug,'name':it['name'],'title':it['title'],**extra})
 if read_json(status,{}).get('status')=='ready':return
 try:
  from workflow.vertical_cover import original_source
  try:original_source(c,it)
  except FileNotFoundError as e:state('missing_source',error=str(e));return
  if not any((d/'subs'/n).is_file() for n in ['lyrics_poetic.ass','lyrics_literal.ass','lyrics.ass']):state('missing_subtitles');return
  labels=header_labels(c,it);state('running');prepare_browser(c,it)
  ensure_song(c.slug,it['name'])
  f.mkdir(exist_ok=True)
  old=read_json(f/'candidates.json',[]);sel=read_json(f/'selected.json',{});chosen=next((r for r in old if r['file']==sel.get('cover')),None)
  backup=base/'before'/c.slug/it['name'];backup.mkdir(parents=True,exist_ok=True)
  if not (backup/'candidates.json').exists():write_json(backup/'candidates.json',old);write_json(backup/'selected.json',sel)
  if sel and not chosen:chosen=next((r for r in read_json(backup/'candidates.json',[]) if r['file']==sel.get('cover')),None)
  if sel and not chosen:raise ValueError('已选封面不在候选记录中，需恢复选帧信息')
  clicked=datetime.fromisoformat(sel['selected_at']) if sel.get('selected_at') else datetime.fromtimestamp((f/'selected.json').stat().st_mtime,SHANGHAI) if sel else None
  candidates(c,it,keep_existing=True)
  rows=read_json(f/'candidates.json');assert len(rows)==(1 if sel else 0) if c.has_cover_pool else len(rows)==18
  if chosen and not c.has_cover_pool:
   new=next(r for r in rows if abs(r['time']-chosen['time'])<.01)
   replace_cover_selection(c,it,new['file'],clicked)
  for r in rows:
   with Image.open(f/r['file']) as im:assert im.size==(1080,1440)
  draft,event,zh=posting_inputs(c,it,read_json(d/'post_draft.json'));post=submission(draft,event,zh);assert post and post['title_chars']<=30
  selection=read_json(f/'selected.json',{});post['cover']=cover_attachment(d,selection.get('cover'));write_json(f/'douyin_submission.json',post)
  state('ready',header=labels,candidates=len(rows),selected=bool(selection));print('READY',c.slug,it['name'],flush=True)
 except Exception:
  error=traceback.format_exc();state('failed',error=error);print('FAIL',c.slug,it['name'],error,flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(process,items))
print('BATCH_FINISHED',flush=True)
