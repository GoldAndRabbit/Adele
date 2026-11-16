from pathlib import Path
import sys,json,os,time,fcntl
R=Path('/Users/gold/repos/adele');sys.path.insert(0,str(R));os.chdir(R)
from estimate_space import estimate
B=Path(__file__).parent
lock=(B/'sample.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
rows=json.loads((B/'status.json').read_text())['items'];rows.sort(key=lambda r:0 if ':grammys_2014:' in r['spec'] else 1)
for row in rows:
 if row['status'] in ['rendering','submitted','needs_content_repair']:continue
 state={'pid':os.getpid(),'spec':row['spec'],'stage':'sampling','time':time.time()};(B/'sample_status.json').write_text(json.dumps(state))
 try:state.update(stage='sampled',required=estimate(row['spec']))
 except Exception as e:state.update(stage='failed',reason=str(e))
 (B/'sample_status.json').write_text(json.dumps(state));print(state,flush=True)
