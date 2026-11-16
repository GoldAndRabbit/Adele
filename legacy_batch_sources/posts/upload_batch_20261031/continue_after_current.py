from pathlib import Path
import os,time,fcntl,subprocess,json
B=Path(__file__).parent
lock=(B/'continuation.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
state={'pid':os.getpid(),'status':'waiting_for_existing_runner','waiting_pid':23811,'order':['Send My Love','Rolling in the Deep'],'deja_vu':'excluded_retry_limit'}
def save(): (B/'continuation_status.json').write_text(json.dumps(state,indent=2)+'\n')
save()
while True:
    try: os.kill(23811,0)
    except ProcessLookupError: break
    time.sleep(15)
state['status']='running';save()
p=subprocess.Popen(['/Users/gold/repos/adele/.venv/bin/python','-u',str(B/'run.py')])
(B/'pid').write_text(str(p.pid)+'\n')
state['runner_pid']=p.pid;save()
state['exit_code']=p.wait();state['status']='finished';save()
