import sys
from pathlib import Path
sys.path.insert(0,str(Path.cwd()))
from workflow.live.paths import read_json,write_json
from workflow.bili_title import for_post
from post_bili.upload import load_post
from post_bili.metadata_quality import fingerprint
root=Path('posts/bili_full_20261114');plan=read_json(root/'plan.json');changes=read_json(root/'title-boundary-corrections.json',[]);errors=[]
paths = list(Path("posts").glob("*/post/bili_upload.json")) + list(Path("posts").glob("*/*/post/bili_upload.json"))
directories = sorted({path.resolve().parent.parent for path in paths
                      if not any(part.startswith(".") for part in path.parts)
                      and ".storage-backups" not in path.resolve().parts})
for directory in directories:
 row = {"name": directory.name, "path": str(directory)}
 d=Path(row['path']);page=read_json(d/'post/bili_upload.json')
 try:title=for_post(d,load_post(d)[0])
 except (ValueError, SystemExit) as error:
  errors.append({'song':row['name'],'error':str(error)});continue
 if page['标题']==title:continue
 before=page['标题'];page.update({'标题':title,'标题字符数':len(title)})
 write_json(d/'post/bili_upload.json',page)
 bundle=d/'delivery_bundle.json'
 if bundle.exists():
  b=read_json(bundle)
  if b.get('bilibili'):
   b['bilibili'].update({'标题':title,'标题字符数':len(title)});write_json(bundle,b)
 policy=d/'metadata_policy.json'
 if policy.exists():
  b=read_json(policy);b['title_format']='reviewed_current';b['reviewed_fingerprint']=fingerprint(title,page['简介'],page['标签']);write_json(policy,b)
 changes.append({'song':row['name'],'before':before,'after':title,'path':row['path'],'published':bool(read_json(d/'post/publish.json'))})
changes = list({row['path']: row for row in changes}.values())
write_json(root/'title-boundary-corrections.json',changes)
write_json(root/'title-boundary-errors.json',errors)
print('全量检查',len(directories),'需更新',len(changes),'已投稿',sum(r['published'] for r in changes),'异常',errors,flush=True)
for r in changes:
 if r['song'] in ['emptiness_machine','03_green_light','03_green_light_','04_green_light']:
  print(r['song'],r['after'],len(r['after']),flush=True)
