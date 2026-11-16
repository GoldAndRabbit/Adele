from pathlib import Path
from workflow.preview_batch import visible
from workflow.live.paths import read_json,write_json
from workflow.bili_title import for_post, VERSION
from workflow.vertical_post import posting_inputs
rows=[]
for c,it in visible():
 d=c.song_dir(it);draftp=d/'post_draft.json';srcp=d/'post'/f"{it['name']}.json"
 draft=read_json(draftp,{}) or {};src=read_json(srcp,{}) or {}
 if not draft and not src:continue
 post={**src,**draft,'song':{**src.get('song',{}),**draft.get('song',{})},'performance':{**src.get('performance',{}),**draft.get('performance',{})}}
 special=it['name'].startswith('the_angel')
 if special:post['song']['title_song']='The Angel (North London Forever) 阿森纳队歌'
 title=for_post(d,post);full=for_post(d,post,limit=None)
 assert title and len(title)<=80
 row=dict(concert=c.slug,name=it['name'],old=draft.get('title') or src.get('title'),title=title,full=full,characters=len(title),version=VERSION)
 rows.append(row)
 if all(not obj or (obj.get("title")==title and obj.get("title_full")==full) for obj in (draft,src)):
  continue
 for p,obj in [(draftp,draft),(srcp,src)]:
  if not obj:continue
  if special:obj.setdefault('song',{})['title_song']=post['song']['title_song']
  overrides=obj.get('posting_titles',{})
  overrides.pop('bilibili',None)
  obj.update(title=title,title_full=full,title_chars=len(title),bili_title_version=VERSION)
  write_json(p,obj)
 p=d/'post/bili_upload.json';obj=read_json(p)
 if obj:
  obj.update(标题=title,标题字符数=len(title));write_json(p,obj)
 p=d/'delivery_bundle.json';obj=read_json(p)
 if obj:
  obj.setdefault('bilibili',{}).update(title=title,title_full=full,title_characters=len(title),needs_title_shortening=False)
  write_json(p,obj)
 # Reviewed titles also feed the actual publication entry.
 rv=read_json(c.review,{})
 entry=rv.get('songs',{}).get(it['name'],{})
 if 'title' in entry:
  entry['title']=title;write_json(c.review,rv)
write_json(Path('work/bili-title-20261114/audit.json'),rows)
print('已更新',len(rows),'超长',sum(r['characters']>80 for r in rows))
for r in rows:
 if 'sound_of_silence' in r['name'] or r['name'].startswith('the_angel'):print(r['name'],r['characters'],r['title'])
