"""Drain the two explicitly allowed jobs and stop their queue controllers."""
from pathlib import Path
import json,os,signal,subprocess,time,sys,fcntl
R=Path(__file__).resolve().parents[2];B=Path(__file__).resolve().parent;D=R/'posts/source_restore_20261104'
sys.path.insert(0,str(R))
from workflow.storage import archive_root
def write(path,value):
 t=path.with_suffix('.drain-tmp');t.write_text(json.dumps(value,ensure_ascii=False,indent=2));t.replace(path)
def cmd(pid):return subprocess.run(['ps','-p',str(pid),'-o','command='],text=True,capture_output=True).stdout.strip()
def kids(pid):
 return [x for x in subprocess.run(['ps','-P',str(pid),'-o','stat='],text=True,capture_output=True).stdout.split() if not x.startswith('Z')]
def stop_controller(pid,match):
 if match not in cmd(pid):return
 os.kill(pid,signal.SIGSTOP)
 if kids(pid):raise RuntimeError('controller still has active children')
 os.kill(pid,signal.SIGTERM);os.kill(pid,signal.SIGCONT)
def main():
 lock=(B/'drain_current.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 h=json.loads((B/'drain_request.json').read_text());pid=h['production_pid'];dp=h['download_pid'];name=h['download'];group='others'
 if 'source_restore_20261104/restore.py others' in cmd(dp):os.kill(dp,signal.SIGSTOP)
 while True:
  if not h.get('production_stopped'):
   st=json.loads((B/'status.json').read_text());r=next(v for v in st['items'] if v['spec']==h['spec'])
   if r['status'] in ('submitted','awaiting_platform_check','failed','retry_limit','waiting_for_metadata','waiting_for_review_files') and not kids(pid):
    stop_controller(pid,'finalize_46_20261104/run.py');h['production_stopped']=True;h['production_result']=r['status'];write(B/'drain_request.json',h)
  if not h.get('download_stopped') and not kids(dp):
   stop_controller(dp,'source_restore_20261104/restore.py others')
   job=next(j for j in json.loads((D/'others.json').read_text()) if j['dir']==name);target=archive_root()/'sources'/name/'source.mp4';src=R/name/'source.mp4'
   try:
    result=json.loads(subprocess.check_output(['ffprobe','-v','quiet','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(target)],timeout=60));du=float(result['format']['duration'])
    assert {'audio','video'}<={s['codec_type'] for s in result['streams']} and du>0 and (not job.get('duration') or abs(du-job['duration'])<=2)
    if not src.exists() and not src.is_symlink():src.symlink_to(target)
    assert src.samefile(target)
    record={'stage':'restored','probe':result,'external':str(target)}
   except Exception as e:record={'stage':'needs_retry','detail':'本次下载结束后尚无已校验成品：'+type(e).__name__}
   f=D/'others_state.json';v=json.loads(f.read_text());v[name]=record;write(f,v)
   h['download_stopped']=True;h['download_result']=record['stage'];write(B/'drain_request.json',h)
  if h.get('download_stopped') and h.get('production_stopped'):return
  time.sleep(0.5)
if __name__=='__main__':main()
