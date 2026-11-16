"""Scoped, resumable preparation for three authorized concerts; no final exports."""
import fcntl,json,os,subprocess,sys,time,traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
ROOT=Path('/Users/gold/repos/adele');os.chdir(ROOT)
sys.path[:0]=[str(ROOT),str(ROOT/'workflow'),str(ROOT/'work/coachella-lolla-previews')]
import common
from workflow.live.paths import read_json,write_json,Concert,VENV_PY
from workflow.subtitle_metadata_batch import ensure_audio,subtitle_audit,prepare_metadata
from workflow.live.package import post_title
from workflow.preview_batch import enable_browser
from workflow.delivery_bundle import write_bundle
import make_meta
from remote_audio import ensure_audio
from llm import chat_json
BASE=Path(__file__).resolve().parent
GPU=Lock();STATE=Lock()
SLUGS=['chappell_lolla_brasil_2026','adele_one_night_only_2021','gaga_coachella_2025']

def checkpoint():
 if (BASE/'PAUSED').exists():raise RuntimeError('This batch is paused')
common.base.checkpoint=checkpoint

def status(slug,name,**fields):
 with STATE:
  p=BASE/'status.json';s=read_json(p,{})
  key=slug+'/'+name;s[key]={**s.get(key,{}),**fields,'updated_at':datetime.now().astimezone().isoformat()};write_json(p,s)

def metadata(c,it,job):
 from workflow.live.package import draft_meta
 info=read_json(c.song_dir(it)/'song.json')
 start,end=info['slice']
 draft_meta(c,it,{'start':start,'end':end},SimpleNamespace(force=False))
 return prepare_metadata(c,it)


def one(job):
 slug=job['slug'];c=Concert(slug);folder=common.BASE/slug
 try:
  with (folder/'preparation.lock').open('a') as lock:
   fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   info=c.load('info');job={**job,'source':info['source_file']}
   checkpoint();status(slug,'_concert',stage='locating',status='running')
   spans=read_json(folder/'locations.json')
   if spans is None:
    # ASR runs on source audio; no interpolation or 4K export is started.
    for attempt in range(3):
     try:
      rows=common.base.transcript(job,info['duration'],folder);break
     except RuntimeError:
      if attempt==2:raise
      time.sleep(5)
    spans=common.base.locate(job,rows,folder)
   hits={r['idx']:r for r in spans}
   segments=read_json(c.segments,{'items':[],'gaps':[]});known={r['name'] for r in segments['items']}
   for it in c.song_items():
    hit=hits.get(it['idx'])
    if hit and it['name'] not in known:
     segments['items'].append({**it,'start':hit['start'],'end':hit['end'],'flags':['首尾定位待人工审核'],'review':'pending'})
   write_json(c.segments,segments)
   for it in c.song_items():
    checkpoint();name=it['name'];d=c.song_dir(it);hit=hits.get(it['idx'])
    try:
     if not hit:raise ValueError('No supported performance boundary found; needs location review')
     info_song=read_json(d/'song.json',{})
     info_song.setdefault('slice',[hit['start'],hit['end']])
     info_song.update(source_file=info['source_file'],lang=info_song.get('lang') or 'en',artist=it.get('artist') or info['artist'],title=it['title'])
     write_json(d/'song.json',info_song)
     status(slug,name,status='running',stage='reference')
     common.reference(job,it,c)
     if (d/'lyrics_source').exists() and (d/'lyrics_source').read_text().startswith('source-asr'):
      raise ValueError('Reference lyrics unavailable; ASR not silently substituted')
     if subtitle_audit(c,it)['status']=='missing':
      status(slug,name,status='running',stage='audio')
      # GPU memory is shared across concert threads; only one separator runs.
      with GPU:ensure_audio(c,it)
      status(slug,name,status='running',stage='alignment_translation')
      with (BASE/(slug+'--'+name+'.log')).open('a') as log:
       subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',slug,name],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
     status(slug,name,status='running',stage='posting')
     meta=metadata(c,it,job);sub=subtitle_audit(c,it)
     enable_browser(c,it);write_bundle(c,it)
     # Generated material is visible for review, never automatically approved.
     with STATE:
      sl=read_json(c.setlist)
      for row in sl['items']:
       if row['name']==name:row['review_hidden']=False
      write_json(c.setlist,sl)
     status(slug,name,status='needs_review',stage='done',subtitles=sub,metadata=meta)
     print('READY_FOR_REVIEW',slug,name,flush=True)
    except Exception as exc:
     status(slug,name,status='failed',error=str(exc));traceback.print_exc()
   status(slug,'_concert',status='processed_with_review_pending',stage='done')
 except Exception as exc:
  status(slug,'_concert',status='failed',error=str(exc));traceback.print_exc()

if __name__=='__main__':
 with (BASE/'run.lock').open('a') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  (BASE/'pid').write_text(str(os.getpid()))
  common.REFS.update(common.reusable_refs())
  jobs={j['slug']:j for j in read_json(common.BASE/'jobs.json')}
  with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(one,[jobs[s] for s in SLUGS]))
