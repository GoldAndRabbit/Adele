from datetime import datetime
from pathlib import Path
import json,sys
from workflow.live.paths import Concert,read_json,write_json
from workflow.vertical_workflow import candidates
from workflow.vertical_post import replace_cover_selection,posting_inputs,submission,cover_attachment,SHANGHAI
from workflow.vertical_cover import COVER_STYLE_VERSION
from PIL import Image
slug=sys.argv[1];c=Concert(slug);report=[]
for it in c.song_items():
 d=c.song_dir(it);f=d/'vertical';old=read_json(f/'candidates.json',[]);sel=read_json(f/'selected.json',{});chosen=next((r for r in old if r['file']==sel.get('cover')),None)
 backup=Path('work/cover-berry/before')/slug/it['name'];backup.mkdir(parents=True,exist_ok=True)
 
 if not (backup/'candidates.json').exists():
  write_json(backup/'candidates.json',old);write_json(backup/'selected.json',sel)
 if sel and not chosen:
  chosen=next((r for r in read_json(backup/'candidates.json',[]) if r['file']==sel.get('cover')),None)
 clicked=datetime.fromisoformat(sel['selected_at']) if sel.get('selected_at') else datetime.fromtimestamp((f/'selected.json').stat().st_mtime,SHANGHAI) if sel else None
 candidates(c,it,keep_existing=True,redraw=False)
 rows=read_json(f/'candidates.json');assert len(rows)==18
 if chosen and not c.has_cover_pool:
  match=next(r for r in rows if abs(r['time']-chosen['time'])<.01)
  replace_cover_selection(c,it,match['file'],clicked)
 for row in rows:
  with Image.open(f/row['file']) as im:assert im.size==(1080,1440)
 draft,event,zh=posting_inputs(c,it,read_json(d/'post_draft.json'))
 post=submission(draft,event,zh);assert post and post['title_chars']<=30
 selected=read_json(f/'selected.json',{});post['cover']=cover_attachment(d,selected.get('cover'))
 write_json(f/'douyin_submission.json',post)
 report.append({'name':it['name'],'candidates':len(rows),'selected':bool(selected),'submission':post})
 write_json(Path('work/cover-berry')/(slug+'-report.json'),report)
 print('READY',it['name'],post['title'],flush=True)
