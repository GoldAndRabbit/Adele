from pathlib import Path
import subprocess,json,os,sys,fcntl,hashlib,time
R=Path(__file__).resolve().parents[2];sys.path.insert(0,str(R))
from workflow.storage import archive_root
from workflow.youtube_download import cli_args
B=Path(__file__).resolve().parent
queue=sys.argv[1] if len(sys.argv)>1 else 'jobs'
lk=(B/(queue+'.lock' if queue!='jobs' else 'worker.lock')).open('a');fcntl.flock(lk,fcntl.LOCK_EX|fcntl.LOCK_NB)
E=archive_root();jobs=json.loads((B/(queue+'.json')).read_text());status={}
def save():
 name='state' if queue=='jobs' else queue+'_state';p=B/(name+'.tmp');p.write_text(json.dumps(status,ensure_ascii=False,indent=2));p.replace(B/(name+'.json'))
def probe(path,expected):
 data=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration:stream=codec_type,width,height','-of','json',str(path)],timeout=75))
 duration=float(data['format']['duration'])
 assert {'video','audio'}<={v['codec_type'] for v in data['streams']} and duration>0
 if expected and abs(duration-expected)>2:raise ValueError('duration mismatch: '+str((expected,duration)))
 return data
def attach(src,target):
 if src.is_symlink() and src.resolve()==target.resolve():return
 if src.exists():raise ValueError('existing source preserved')
 temp=src.with_name('.restore-source-'+str(os.getpid()));temp.symlink_to(target);temp.replace(src)
for j in jobs:
 key=j['dir'];status[key]={'stage':'checking'};save()
 try:
  assert archive_root()==E;src=R/key/'source.mp4';src.parent.mkdir(exist_ok=True,parents=True)
  dest=E/'sources'/key;dest.mkdir(exist_ok=True,parents=True);target=dest/'source.mp4';expected=j.get('duration')
  if src.is_file() and src.stat().st_size>0:
   status[key]=dict(stage='present',probe=probe(src,expected));save();continue
  if not target.is_file():
   status[key]={'stage':'downloading','url':j['url']};save()
   cmd=[str(R/'.venv/bin/yt-dlp'),'--no-playlist',*cli_args(j['url'],proxy='http://127.0.0.1:7890',browser='chrome'),'--no-progress','--socket-timeout','20','--retries','2','--fragment-retries','3','-f','bv*[height<=2160][dynamic_range=SDR]+ba[format_note*=original]/bv*[height<=2160][dynamic_range=SDR]+ba[language^=en]/bv*[height<=2160]+ba/b','--merge-output-format','mp4','--remux-video','mp4','--no-write-subs','-o',str(dest/'source.%(ext)s'),j['url']]
   with (B/(src.parent.name+'.log')).open('ab') as f:
    fast=cmd[:-1]+['--downloader','aria2c','--downloader-args','aria2c:-x 8 -s 8 -k 1M','--concurrent-fragments','4',cmd[-1]]
    try:subprocess.run(fast,stdout=f,stderr=subprocess.STDOUT,timeout=5400,check=True)
    except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
     subprocess.run(cmd,stdout=f,stderr=subprocess.STDOUT,timeout=9000,check=True)
  result=probe(target,expected);assert archive_root()==E;attach(src,target)
  status[key]=dict(stage='restored',probe=result,external=str(target))
 except Exception as e:status[key]=dict(stage='needs_retry',error=type(e).__name__,detail=str(e)[:180] if not isinstance(e,subprocess.CalledProcessError) else 'download/probe exited '+str(e.returncode))
 save()
