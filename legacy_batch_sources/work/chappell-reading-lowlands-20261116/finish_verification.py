"""After preparation/repair drain, reconcile actual covers with page receipts."""
import fcntl,sys,time
from pathlib import Path
from datetime import datetime
import psutil
ROOT=Path('/Users/gold/repos/adele');sys.path.insert(0,str(ROOT))
from workflow.live.paths import Concert,read_json,write_json
from workflow.ai_cover import reviewed_revision
from workflow.reviewed_cover import verify_release
from workflow.delivery_bundle import write_bundle
from workflow.fibo_dual_queue import run
from workflow.subtitle_metadata_batch import subtitle_audit
from server.app import platform_covers_ready
BASE=Path(__file__).resolve().parent
SLUGS=('chappell_reading_2025','chappell_lowlands_2025')


def active(pid):
 try:
  p=psutil.Process(pid)
  return p.status()!=psutil.STATUS_ZOMBIE and ('chappell-reading-lowlands-20261116' in ' '.join(p.cmdline()))
 except psutil.NoSuchProcess:return False


with (BASE/'finish-verification.lock').open('a') as own:
 fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
 (BASE/'finish-verification.pid').write_text(str(__import__('os').getpid()))
 for pid in map(int,sys.argv[1:]):
  while active(pid):time.sleep(5)
 if (BASE/'PAUSED').exists():raise SystemExit(0)
 # One bounded final repair pass, still through the standard two-Mac workflow.
 missing=[{'slug':slug,'name':item['name']} for slug in SLUGS for item in Concert(slug).song_items()
          if not reviewed_revision(Concert(slug).song_dir(item)/'covers/ai')]
 if missing:
  folder=BASE/'final-cover-repairs';folder.mkdir(exist_ok=True)
  write_json(folder/'queue.json',missing)
  reviews=read_json(BASE/'visual-review.json',{})|read_json(BASE/'cover-repairs/visual-review.json',{})
  write_json(folder/'visual-review.json',reviews)
  run(folder/'queue.json',Path('/Users/gold/Library/Caches/adele/fibo2-edit-turbo-q4'),
      BASE/'remote-fibo.json',auto_review=True,reselect_rejected=True)
 reviews={}
 for path in (BASE/'visual-review.json',BASE/'cover-repairs/visual-review.json',BASE/'final-cover-repairs/visual-review.json'):
  for key,row in read_json(path,{}).items():reviews.setdefault(key,[]).append(row)
 results=read_json(BASE/'page-verification.json',{});state=read_json(BASE/'status.json',{})
 for slug in SLUGS:
  c=Concert(slug)
  for item in c.song_items():
   key=slug+'/'+item['name'];directory=c.song_dir(item);released=reviewed_revision(directory/'covers/ai')
   if not released:continue
   record=next((row for row in reversed(reviews.get(key,[])) if row.get('status') in ('approved','synced_verified')
                and row.get('review_hash')==released[0].get('review_hash')),None)
   if not record:continue
   try:
    verify_release(Path(record['stage']),slug,'http://127.0.0.1:8160');write_bundle(c,item)
    results[key]={'status':'verified','stage':record['stage'],'review_hash':record['review_hash']}
    if key in state:
     state[key].update(cover_status='released_verified',cover_error=None,error=None)
   except Exception as error:results[key]={'status':'pending','error':str(error)}
   write_json(BASE/'page-verification.json',results)
 write_json(BASE/'status.json',state)
 counts={}
 for slug in SLUGS:
  c=Concert(slug);items=c.song_items();row={'total':len(items),'subtitles':0,'preview':0,'posting_copy':0,'covers':0}
  for item in items:
   d=c.song_dir(item);sub=subtitle_audit(c,item);post=read_json(d/'post/bili_upload.json',{})
   row['subtitles']+=sub['status']!='missing' and not sub.get('issues')
   row['preview']+=(d/'vertical/original-selected.mp4').is_file()
   row['posting_copy']+=bool(1800<=len(post.get('简介','').strip())<=2000 and post.get('标题') and post.get('标签'))
   row['covers']+=platform_covers_ready(d)
  counts[slug]=row
 write_json(BASE/'preparation-audit.json',{'checked_at':datetime.now().astimezone().isoformat(),
   'counts':counts,'human_approved':False,'description_research':'pending review; generated copy not equated with fact-check approval',
   'scope':'review preparation only','page_verification':results})
 print('PREPARATION_COUNTS',counts,flush=True)
