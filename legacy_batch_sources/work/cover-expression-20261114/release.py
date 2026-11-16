from workflow.reviewed_cover import *
from workflow.live.paths import ROOT
from workflow.posting_cover import active_cover_set
import workflow.reviewed_cover as rc
import sys
open_url=rc.urlopen;rc.urlopen=lambda url,timeout=45:open_url(url,timeout=180)
b=ROOT/'work/cover-expression-20261114';c=Concert('singles');out=[]
for n in sys.argv[1:]:
 d=b/n/'stage';s=read_json(d/'stage.json');print(n,publish(d,digest(d/'stage.json')),flush=True)
 for attempt in range(3):
  try:receipt=verify_release(d,'singles','http://127.0.0.1:8160');break
  except ValueError as e:
   if 'older' not in str(e) or attempt==2:raise
   time.sleep(11)
 selection=read_json(d.parent/'selection.json');p=c.dir/'fibo-cover-plan.json';plan=read_json(p,{});spec=plan.get(n)
 if spec is not None:
  spec.update(source_time=s['source_time'],reference=s['master']['reference'],original_reference='references/source-'+digest(Path(s['raw']))[:16]+Path(s['raw']).suffix,review_framing=s['framing'],lead_face_x=s['framing']['focus'][0],prompt_override=selection['prompt_override'],scene_note=selection['scene_note'],reference_lock=dict(source_time=s['source_time'],reference_sha256=digest(Path(s['input']))),expression_review=dict(preference='natural, relaxed, subtle smile; no enlarged lips or exaggerated mouth',reference_time=s['source_time'],review_hash=receipt['review_hash']))
  write_json(p,plan)
 files=active_cover_set(c.song_dir(c.item(n)));song=c.song_dir(c.item(n));bili=read_json(song/'post/bili_upload.json');dy=read_json(song/'vertical/douyin_submission.json');bundle=read_json(song/'delivery_bundle.json')
 for key,p in [(('bili-ai','16x9'),bili['封面16:9']),(('bili-ai','4x3'),bili['封面4:3']),(('douyin-ai','3x4'),dy['selected_cover']['path']),(('douyin-ai','4x3'),dy['selected_cover']['wide_path'])]:
  assert digest(Path(p))==digest(files[key])
  with Image.open(files[key]) as im:assert im.size==SIZES[key] and has_left_brand(im)
 for v in bundle['ai_variants']:
  if (v['platform'],v['ratio']) in files:assert digest(Path(v['path']))==digest(files[v['platform'],v['ratio']])
 receipt['posting_json_verified']=True;receipt['bundle_json_verified']=True;write_json(d.parent/'verified.json',receipt);out.append(receipt);print(receipt,flush=True)
write_json(b/'verified.json',out)
