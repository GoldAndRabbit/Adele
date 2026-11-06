"""Local review bundle only: never selects an AI cover or submits a post."""
from workflow.live.paths import read_json,write_json
from workflow.vertical_post import submission,posting_inputs
from workflow.bili_title import for_post

def write_bundle(concert,item):
 d=concert.song_dir(item);draft=read_json(d/'post_draft.json',{});products=read_json(d/'products/products.json',{})
 title=for_post(d,draft)
 ai=d/'covers/ai';masters=read_json(ai/'masters.json',[]);active={m['file'] for m in masters}
 variants=[r for r in read_json(ai/'variants.json',[]) if r['master'] in active]
 failures=[]
 for p in ai.glob('runs/*/candidate-*.json'):
  row=read_json(p,{})
  if row.get('status')=='failed':failures.append({'record':str(p.resolve()),'label':row.get('label'),'reason':row.get('provider_error_code') or row.get('error_type')})
 result={'concert':concert.slug,'song':item['name'],'status':products.get('status'),'videos':[{**r,'path':str((d/'products'/r['file']).resolve())} for r in products.get('items',[])],
  'bilibili':{'title':title,'title_full':for_post(d,draft,limit=None),'title_characters':len(title),'title_limit':80,'needs_title_shortening':len(title)>80},
  'douyin':submission(*posting_inputs(concert,item,draft)),
  'ai_masters':masters,'ai_variants':[{**r,'path':str((ai/r['file']).resolve())} for r in variants],
  'ai_failures':failures,'ai_adoption':'awaiting user selection; existing selected covers unchanged','published':False}
 target=d/'delivery_bundle.json';write_json(target,result);return result
