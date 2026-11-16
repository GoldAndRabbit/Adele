import json,hashlib
from pathlib import Path
from workflow.live.paths import Concert,read_json,write_json
from workflow.vertical_post import posting_inputs,submission
base=Path('work/description-research')
rows=[]
for item in read_json(base/'inventory.json'):
 if not item['needs_copy']:continue
 slug,name=item['id'].split('--',1);c=Concert(slug);d=c.song_dir(c.item(name));draft=read_json(d/'post_draft.json',{});intro=draft.get('intro') or {};body=draft.get('intro_text','')
 ok=all(intro.get(k) for k in ('song','performance','lyrics')) and body=='\n\n'.join(intro[k] for k in ('song','performance','lyrics')) and 1800<=len(body)<=2000
 rows.append(dict(id=item['id'],characters=len(body),valid=bool(ok)))
 if ok:
  p=posting_inputs(c,c.item(name),draft)[0];assert p['bili_intro'].strip()==body
write_json(base/'three-part-audit.json',rows)
print('合格',sum(r['valid'] for r in rows),'总数',len(rows))
print('未完成',[r['id'] for r in rows if not r['valid']][:12])
