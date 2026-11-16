from pathlib import Path
import json,time,datetime,subprocess,fcntl
R=Path('/Users/gold/repos/adele');B=Path(__file__).parent;d=R/'posts/eminem_love_way_lie_radio1';P=R/'.venv/bin/python'
lock=(B/'bbc_retry.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
f=B/'bbc_retry_status.json';s=json.loads(f.read_text()) if f.exists() else {'attempts':0}
if (d/'post/publish.json').exists():raise SystemExit('Receipt already exists; skipped')
assert s['attempts']<3,'Retry limit reached'
s.update(attempts=s['attempts']+1,status='uploading',reason='Previous attempt failed locally in show() before contacting submission endpoint');f.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
p=d/'post/bili_upload.json';o=json.loads(p.read_text());o['定时发布']=datetime.datetime.fromtimestamp(time.time()+15000).strftime('%Y-%m-%d %H:%M');p.write_text(json.dumps(o,ensure_ascii=False,indent=2)+'\n')
with (B/'bbc_retry.log').open('a') as log:r=subprocess.run([P,'post_bili/upload.py',d,'--submit','--line','bda2'],cwd=R,stdout=log,stderr=subprocess.STDOUT)
receipt=d/'post/publish.json'
s.update(status='submitted' if receipt.exists() else 'needs_platform_check',exit_code=r.returncode)
if receipt.exists():s['bvid']=json.loads(receipt.read_text()).get('bvid')
f.write_text(json.dumps(s,ensure_ascii=False,indent=2)+'\n')
