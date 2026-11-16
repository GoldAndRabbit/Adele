import sys,os,signal,time,subprocess
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
sys.path.insert(0,'/Users/gold/repos/adele')
from workflow.live.paths import read_json,write_json
root=Path('/Users/gold/repos/adele');out=root/'posts/bili_full_20261114';old=int((out/'runner.pid').read_text())
os.kill(old,signal.SIGSTOP)
write_json(out/'restart-on-upload-boundary.json',{'old_pid':old,'status':'current_upload_continues_parent_waiting','requested_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()})
while True:
 rows=subprocess.check_output(['ps','-axo','pid=,pgid='],text=True).splitlines()
 children=[int(line.split()[0]) for line in rows if len(line.split())==2 and int(line.split()[1])==old and int(line.split()[0])!=old]
 if not children:break
 time.sleep(2)
try:os.kill(old,signal.SIGKILL)
except ProcessLookupError:pass
with (out/'current-run.log').open('a') as fh:
 fh.write('\n当前上传已结束，接续加载回执去重修复；不打断在传文件。\n');fh.flush()
 p=subprocess.Popen([sys.executable,'-u',str(root/'post_bili/full_library.py'),str(out/'resume-plan.json')],cwd=root,stdout=fh,stderr=subprocess.STDOUT,start_new_session=True)
(out/'runner.pid').write_text(str(p.pid))
s=read_json(out/'version-corrected-resume.json',{});s.update(pid=p.pid,resumed_at=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat());write_json(out/'version-corrected-resume.json',s)
write_json(out/'restart-on-upload-boundary.json',{'old_pid':old,'pid':p.pid,'status':'resumed','resumed_at':datetime.now(ZoneInfo('Asia/Shanghai')).isoformat()})
print('边界接续完成',p.pid,flush=True)
