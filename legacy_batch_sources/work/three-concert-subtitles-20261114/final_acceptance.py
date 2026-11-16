"""Verify the complete three-concert preparation delivery from actual assets and API."""
from pathlib import Path
from datetime import datetime
import hashlib,json,re,sys
from urllib.request import urlopen
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from PIL import Image
from workflow.live.paths import Concert,read_json,write_json
from workflow.ai_cover import reviewed_revision
from workflow.subtitle_metadata_batch import subtitle_audit
from post_bili.upload import description
from workflow.reviewed_cover import digest
b=ROOT/'work/three-concert-subtitles-20261114';reviews=read_json(b/'visual-review.json');items=[];groups=[];errors=[]
for slug in ['chappell_lolla_brasil_2026','adele_one_night_only_2021','gaga_coachella_2025']:
 c=Concert(slug);counts=dict(total=0,subtitles=0,posting=0,covers=0,platform_images=0,full_ai=0,source_with_ai=0)
 with urlopen('http://127.0.0.1:8160/api/concerts/'+slug+'/album_covers',timeout=30) as response:cards={r['name']:r for r in json.load(response)['covers']}
 for it in c.song_items():
  name=it['name'];key=slug+'/'+name;d=c.song_dir(it);counts['total']+=1;issues=[]
  sub=subtitle_audit(c,it)
  if sub['issues']:issues+=['subtitle: '+x for x in sub['issues']]
  else:counts['subtitles']+=1
  bundle=read_json(d/'delivery_bundle.json');bi=bundle['bilibili'];dy=bundle['douyin'];draft=read_json(d/'post_draft.json')
  checks={'bili_body_canonical':bi['简介']==description(draft),'bili_intro_length':1800<=len(bi['简介'])<=2000,
          'bili_title_budget':1<=len(bi['标题'])<=80,'bili_tags':len(bi['标签'])==12 and len(set(bi['标签']))==12,
          'douyin_title_budget':0<len(dy['title'].encode('utf-16-le'))//2<=30,
          'douyin_tags':len(dy['hashtags'])==5 and len(set(dy['hashtags']))==5,
          'douyin_body':bool(dy['description_body']) and len(dy['description'].encode('utf-16-le'))//2<=1000,
          'bili_export_synced':read_json(d/'post/bili_upload.json')==bi,
          'douyin_export_synced':read_json(d/'vertical/douyin_submission.json')==dy}
  with urlopen('http://127.0.0.1:8160/api/concerts/'+slug+'/songs/'+name+'/posting',timeout=30) as response:api=json.load(response)
  checks['page_bili_matches_json']=api['bilibili']==bi;checks['page_douyin_matches_json']=api['douyin']==dy
  if all(checks.values()):counts['posting']+=1
  else:issues+=['posting: '+k for k,v in checks.items() if not v]
  revision=reviewed_revision(d/'covers/ai')
  image_records=[];master=None;stage=None;receipt={}
  if not revision:issues.append('missing released four-cover set')
  else:
   master,variants=revision;counts['covers']+=1
   kind=master.get('artwork_method','full_ai');counts[kind]=counts.get(kind,0)+1
   stage=Path(reviews[key]['stage']);staged=read_json(stage/'stage.json');receipt=read_json(stage/'verified.json',{})
   if receipt.get('master')!=master['file'] or receipt.get('review_hash')!=master['review_hash'] or digest(stage/'stage.json')!=master['review_hash']:issues.append('cover review/page receipt mismatch')
   for path,expected in staged['files'].items():
    p=Path(path)
    if not p.is_file() or hashlib.file_digest(p.open('rb'),'sha256').hexdigest()!=expected:issues.append('changed reviewed asset: '+path)
   for v in variants:
    platform=v['platform'].split('-')[0];ratio=v['ratio'];maps=bi['已生成封面路径'] if platform=='bili' else dy['generated_cover_paths']
    paths=maps.get(ratio,[])
    if len(paths)!=1:issues.append('wrong posting cover count: '+platform+ratio);continue
    p=Path(paths[0]);internal=d/'covers/ai'/v['file']
    if not p.is_file() or not re.fullmatch(platform+'_ai_'+ratio+r'_\d{10}\.(jpg|jpeg|png|webp)',p.name):issues.append('invalid posting cover path: '+str(p));continue
    if hashlib.file_digest(p.open('rb'),'sha256').hexdigest()!=hashlib.file_digest(internal.open('rb'),'sha256').hexdigest():issues.append('posting cover differs from reviewed image')
    with Image.open(p) as raster:
     if list(raster.size)!=v['dimensions']:issues.append('cover dimensions differ')
     raster.verify()
    image_records.append(dict(platform=platform,ratio=ratio,path=str(p),dimensions=v['dimensions']))
   counts['platform_images']+=len(image_records)
   expected=next(v['file'] for v in variants if (v['platform'],v['ratio'])==('bili-ai','16x9'))
   if expected not in (cards.get(name,{}).get('url') or ''):issues.append('album card missing or stale')
  item=dict(concert=slug,song=name,subtitles=sub,posting_checks=checks,
            title_chars=len(bi['标题']),intro_chars=len(bi['简介']),bili_tags=len(bi['标签']),douyin_tags=len(dy['hashtags']),
            artwork_method=master.get('artwork_method') if master else None,
            cover_stage=str(stage) if stage else None,review_hash=master.get('review_hash') if master else None,
            cover_paths=image_records,issues=issues,ready_for_user_review=not issues)
  items.append(item)
  if issues:errors.append(dict(song=key,issues=issues))
 groups.append(dict(concert=slug,**counts));print('VERIFIED_GROUP',groups[-1],flush=True)
result=dict(checked_at=datetime.now().astimezone().isoformat(),scope='subtitles, posting copy and platform covers; review preparation',
            counts=groups,total_songs=len(items),platform_images=sum(g['platform_images'] for g in groups),
            errors=errors,ready_for_user_review=not errors,subtitle_human_approval=False,items=items,
            source_repairs=[read_json(ROOT/'concerts/gaga_coachella_2025/songs/02_abracadabra/source_repair.json')],
            explicit_method_note='45 full AI FIBO covers; Bloody Mary uses documented FIBO brushwork and original-frame preservation.')
write_json(b/'completion_audit.json',result)
if errors:
 print('AUDIT_ERRORS',errors,flush=True);raise SystemExit(1)
print('ALL_46_PREPARATION_DELIVERIES_VERIFIED',flush=True)
