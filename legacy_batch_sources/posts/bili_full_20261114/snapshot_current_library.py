import sys
from pathlib import Path
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,'/Users/gold/repos/adele')
from workflow.live.paths import read_json,write_json,Concert
from post_bili.receipt import current_receipt
root=Path('/Users/gold/repos/adele/posts/bili_full_20261114');p=read_json(root/'plan.json');c=Concert('an_audience_with_adele_2021')
pairs=[(b['slug'],s['name'],Path(s['path'])) for b in p['batches'] for s in b['songs']]+[('an_audience_with_adele_2021',s['name'],c.song_dir(s)) for s in c.song_items() if (c.song_dir(s)/'post/bili_upload.json').exists()]
def f(row):
 slug,name,path=row
 try:
  r=current_receipt(path)
  return {'slug':slug,'song':name,'current':bool(r),'bvid':(r or {}).get('bvid'),'submitted_at':(r or {}).get('submitted_at')}
 except Exception as e:return {'slug':slug,'song':name,'current':False,'error':str(e)}
with ThreadPoolExecutor(6) as pool:rows=list(pool.map(f,pairs))
groups=defaultdict(list)
for r in rows:
 if r['current']:groups[r['bvid']].append(r['song'])
status={'checked_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),'total':len(rows),'submitted':len(groups),'remaining':len(rows)-len(groups),'collections':len(read_json(root/'collections_verified.json')),'super_bowl':len({r['bvid'] for r in rows if r['current'] and r['slug']=='super_bowl_halftime'}),'duplicates':{v:rs for v,rs in groups.items() if len(rs)>1},'rows':rows}
write_json(root/'latest-version-status.json',status)
print({k:v for k,v in status.items() if k!='rows'},flush=True)
print('ERRORS',[r for r in rows if r.get('error')],flush=True)
