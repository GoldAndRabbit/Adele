import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict,Counter
sys.path.insert(0,'/Users/gold/repos/adele')
from workflow.live.paths import read_json,write_json
root=Path('/Users/gold/repos/adele/posts/bili_full_20261114');jobs=read_json(root/'description-restoration-plan.json');missing={r['bvid'] for r in jobs if not r.get('body')}
paths={r['path'] for r in read_json(root/'all-published-title-audit-jobs.json')}
paths.update(s['path'] for b in read_json(root/'plan.json')['batches'] for s in b['songs'])
for name in ('medley-title-corrections.json','title-boundary-corrections.json'):
 paths.update(r['path'] for r in read_json(root/name,[]) if r.get('path'))
original_pages={}
for f in (root/'intro-repair').glob('*/before.json'):
 for p,o in read_json(f).items():
  if p.endswith('bili_upload.json'):original_pages[str(Path(p).parent.parent.resolve())]=o.get('简介','')
def scan(raw):
 d=Path(raw);found=[]
 for p in [d/'post/publish.json',*list((d/'post/publish-history').glob('*.json'))]:
  if not p.exists():continue
  r=read_json(p);v=r.get('bvid')
  if v not in missing or r.get('recovered_from_platform'):continue
  body=r.get('desc')
  if body:
   if len(body)<=250:found.append({'bvid':v,'status':'original_short_description','receipt_path':str(p)});continue
   source='submitted_receipt'
  else:
   body=original_pages.get(str(d.resolve())) or read_json(d/'post/bili_upload.json',{}).get('简介')
   source='corresponding_reviewed_page'
  if body and 250<len(body)<=2000:found.append({'bvid':v,'body':body,'receipt':r,'path':str(d),'receipt_path':str(p),'source':source})
 return found
found=defaultdict(list)
with ThreadPoolExecutor(6) as pool:
 for rows in pool.map(scan,paths):
  for row in rows:found[row['bvid']].append(row)
for row in jobs:
 if row.get('body'):continue
 candidates=found.get(row['bvid'],[]);usable=[r for r in candidates if r.get('body')];real=[r for r in usable if r.get('source')=='submitted_receipt']
 preferred=real or usable
 if len({r['body'] for r in preferred})==1:row.update(preferred[0]);row.pop('status',None)
 elif candidates and all(r.get('status')=='original_short_description' for r in candidates):row.update(candidates[0])
write_json(root/'description-restoration-plan.json',jobs)
print('完整简介来源',Counter(r.get('source') or r.get('status') for r in jobs),flush=True)
