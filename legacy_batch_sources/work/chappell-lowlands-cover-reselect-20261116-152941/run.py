from pathlib import Path
import sys,time
from workflow.fibo_dual_queue import run
from workflow.live.paths import read_json,write_json
base=Path(__file__).parent
for attempt in range(1,4):
 if (base/'PAUSED').exists(): break
 print('RESELECT_PASS',attempt,flush=True)
 run(base/'queue.json',Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4'),base/'remote-fibo.json',auto_review=True,reselect_rejected=True,replace_existing=True)
 status=read_json(base/'dual-cover-status.json',{})
 pending=[row for row in read_json(base/'queue.json') if status.get(row['slug']+'/'+row['name'],{}).get('status')!='released_verified']
 if not pending: break
 print('REMAINING',pending,flush=True)
write_json(base/'result.json',{'status':'completed' if not pending else 'needs_repair','remaining':pending,'attempts':attempt,'records':status})
