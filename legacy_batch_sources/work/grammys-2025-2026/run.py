import sys,os,subprocess,fcntl,traceback
from pathlib import Path
from datetime import datetime
ROOT=Path('/Users/gold/repos/adele');os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'workflow')]
from workflow.live.paths import Concert,read_json,write_json,VENV_PY
from workflow.subtitle_metadata_batch import ensure_audio,subtitle_audit,prepare_metadata
BASE=ROOT/'work/grammys-2025-2026';STATE=BASE/'status';STATE.mkdir(exist_ok=True)
def save(c,it,**kw):
 p=STATE/f'{c.slug}--{it["name"]}.json';r=read_json(p,{})
 r.update(concert=c.slug,song=it['name'],title=it['title'],updated=datetime.now().isoformat(),human_approved=False,link=f'http://127.0.0.1:8160/#/{c.slug}/{it["name"]}',**kw);write_json(p,r)
with (BASE/'run.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 for year in (2025,2026):
  c=Concert(f'grammys_{year}');segments={s['name']:s for s in c.load('segments')['items']}
  for it in c.song_items():
   if it['name'] not in segments:save(c,it,status='needs_boundary_mapping');continue
   save(c,it,status='queued')
 for year in (2025,2026):
  c=Concert(f'grammys_{year}');segments={s['name']:s for s in c.load('segments')['items']}
  for it in c.song_items():
   if (BASE/'PAUSED').exists() or (ROOT/'work/subtitle-metadata-library/PAUSED').exists():sys.exit(0)
   if it['name'] not in segments:continue
   d=c.song_dir(it)
   try:
    save(c,it,status='running',stage='browser_clip_and_audio')
    ensure_audio(c,it)
    save(c,it,status='running',stage='asr_alignment_translation')
    with (BASE/f'{c.slug}--{it["name"]}.log').open('a') as log:
     subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,it['name']],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True)
    audit=subtitle_audit(c,it);meta=prepare_metadata(c,it)
    if audit['status']=='structurally_valid':
     data=c.load('setlist')
     for row in data['items']:
      if row['name']==it['name']:row['review_hidden']=False;row['ingest_status']='pending_human_review'
     write_json(c.setlist,data)
    save(c,it,status='pending_human_review',stage='done',subtitles=audit,metadata=meta,boundary_review='pending')
    print('READY_FOR_REVIEW',year,it['name'],flush=True)
   except Exception as e:
    save(c,it,status='failed',error=str(e));traceback.print_exc()
