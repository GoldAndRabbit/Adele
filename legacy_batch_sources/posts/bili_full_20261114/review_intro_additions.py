import sys,re,json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from workflow.live.paths import read_json,write_json
from workflow.make_meta import lyrics_material
from post_bili.repair_intros import safe_analysis_sentence,extend_interpretation
from post_bili.metadata_quality import fingerprint
from post_bili.upload import from_page
from post_bili.edit_description import sync
from post_bili.receipt import current_receipt
root=ROOT/'posts/bili_full_20261114';out=root/'intro-repair'
review_name='intro-dedup-review.json' if '--dedupe' in sys.argv else 'intro-analysis-review.json'
backup_name='before-analysis-dedup-review.json' if '--dedupe' in sys.argv else 'before-analysis-review.json'
plan=read_json(root/'resume-plan.json');songs={Path(s['path']).name:s for b in plan['batches'] for s in b['songs']}

def review(applied):
 folder=applied.parent;g=read_json(folder/'generated.json');before=read_json(folder/'before.json')
 old=next((o['intro'] for p,o in before.items() if not p.endswith(('bili_upload.json','metadata_policy.json')) and isinstance(o.get('intro'),dict)),None)
 if not old:return {'id':folder.name,'status':'missing_source'}
 intro=g['intro'];original=old['lyrics'];expected='\n\n'.join(intro.values())
 if not intro['lyrics'].startswith(original):return {'id':folder.name,'status':'changed_source'}
 tail=intro['lyrics'][len(original):]
 sentences=[s for s in re.split(r'(?<=[。！？])',tail) if s.strip()]
 seen={re.sub(r'\s+','',part) for part in re.split(r'(?<=[。！？])',original)}
 bad=[];kept=[]
 for sentence in sentences:
  norm=re.sub(r'\s+','',sentence)
  if not safe_analysis_sentence(sentence) or (len(norm)>12 and norm in seen):bad.append(sentence)
  else:kept.append(sentence);seen.add(norm)
 if not bad:return {'id':folder.name,'status':'passed'}
 name=read_json(applied)['song'];song=songs[name];d=Path(song['path']);pagepath=d/'post/bili_upload.json';page=read_json(pagepath)
 if page['简介']!=expected:return {'id':folder.name,'status':'concurrent_edit'}
 cleaned={**old,'lyrics':original+''.join(kept)}
 if len('\n\n'.join(cleaned.values()))<1800:
  material={'已有三部分介绍':cleaned,'歌名与歌手':read_json(d/'post_draft.json',{}).get('song'),
            '歌词材料':lyrics_material(d/'lyrics.txt',d/'zh_cache.json')}
  if not material['歌词材料']:
   t=read_json(d/'subs/translation/result.json',{})
   material['字幕材料']=[{'原文':u.get('orig'),'释义':u.get('v2_final')} for u in t.get('units',[]) if u.get('type')!='讲话'][:65]
  cleaned=extend_interpretation(material,'核对解析 '+name)
 body='\n\n'.join(cleaned.values());assert 1800<=len(body)<=2000
 fresh=read_json(pagepath)
 if fresh['简介']!=expected:return {'id':folder.name,'status':'concurrent_edit'}
 write_json(folder/backup_name,{'page':fresh,'generated':g})
 for p in (d/'post_draft.json',d/'post'/f'{d.name}.json'):
  obj=read_json(p)
  if obj:obj.update(intro=cleaned,intro_text=body);write_json(p,obj)
 fresh.update({'简介':body,'简介字符数':len(body)})
 policy=read_json(d/'metadata_policy.json')
 if policy and policy.get('title_format')=='reviewed_current':
  f=from_page(fresh);policy['reviewed_fingerprint']=fingerprint(f['title'],body,f['tag']);write_json(d/'metadata_policy.json',policy)
 write_json(pagepath,fresh)
 bundle=read_json(d/'delivery_bundle.json')
 if bundle and isinstance(bundle.get('bilibili'),dict):bundle['bilibili'].update({'简介':body,'简介字符数':len(body)});write_json(d/'delivery_bundle.json',bundle)
 g.update(intro=cleaned,analysis_review='去除新增解析中的演出顺序推断和长句歌词引用');write_json(folder/'generated.json',g)
 a=read_json(applied);a.update(new_chars=len(body),analysis_review='passed');write_json(applied,a)
 print('REVIEWED',name,len(bad),len(body),flush=True)
 return {'id':folder.name,'song':name,'path':str(d),'status':'corrected','removed_sentences':len(bad),'new_chars':len(body),'needs_online_sync':True}

def work(p):
 try:return review(p)
 except Exception as e:print('FAILED',p.parent.name,type(e).__name__,str(e)[:120],flush=True);return {'id':p.parent.name,'status':'error','error':type(e).__name__}

files=list(out.glob('*/applied.json'));print('待复核',len(files),flush=True)
with ThreadPoolExecutor(2) as pool:records=list(pool.map(work,files))
write_json(root/review_name,{'at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'records':records})
for record in records:
 if record.get('needs_online_sync') and current_receipt(Path(record['path'])):
  try:
   record['online_synced']=sync(record['path'],root/'description-before-review')
   print('ONLINE_SYNC',record['song'],record['online_synced'],flush=True)
  except Exception as e:record['online_sync_error']=type(e).__name__;print('ONLINE_PENDING',record['song'],type(e).__name__,flush=True)
  write_json(root/review_name,{'at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'records':records})
print('解析复核完成',len(records),flush=True)
