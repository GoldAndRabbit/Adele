from pathlib import Path
from workflow.preview_batch import visible
from workflow.live.paths import read_json,write_json
from workflow.vertical_post import posting_inputs,submission
base=Path('work/douyin-titles-20261114')
rows=[]
for c,it in visible():
 d=c.song_dir(it);draft=read_json(d/'post_draft.json',{}) or {}
 try:
  args=posting_inputs(c,it,draft);post=submission(*args)
  assert post and post['title_chars']<=30
  for p in [d/'vertical/douyin_submission.json',d/'delivery_bundle.json']:
   obj=read_json(p,{})
   if not obj:continue
   dst=obj.setdefault('douyin',{}) if p.name=='delivery_bundle.json' else obj
   for key in ('title','title_full','title_chars'):dst[key]=post[key]
   write_json(p,obj)
  rows.append(dict(concert=c.slug,name=it['name'],song=it['title'],artist=args[0]['song']['artist'],title=post['title'],characters=post['title_chars']))
 except Exception as e:rows.append(dict(concert=c.slug,name=it['name'],error=str(e)))
write_json(base/'audit.json',rows)
print('检查',len(rows),'失败',[r for r in rows if r.get('error')])
print('少于24字符',[(r['name'],r.get('title')) for r in rows if r.get('characters',30)<24])
