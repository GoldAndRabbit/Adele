"""Finish this scoped batch after its current worker; reuse successful subtitles."""
import os,sys,fcntl,subprocess,traceback
from pathlib import Path
from datetime import datetime
ROOT=Path('/Users/gold/repos/adele');os.chdir(ROOT);sys.path[:0]=[str(ROOT),str(ROOT/'workflow')]
from workflow.live.paths import Concert,read_json,write_json,VENV_PY
from workflow.subtitle_metadata_batch import ensure_audio,subtitle_audit,prepare_metadata
from workflow.preview_batch import enable_browser
from workflow.browser_library import probe
BASE=ROOT/'work/grammys-2025-2026';STATE=BASE/'status'
def save(c,it,**kw):
 p=STATE/f'{c.slug}--{it["name"]}.json';r=read_json(p,{})
 r.update(concert=c.slug,song=it['name'],title=it['title'],updated=datetime.now().isoformat(),human_approved=False,link=f'http://127.0.0.1:8160/#/{c.slug}/{it["name"]}',**kw);write_json(p,r)
def paused():return (BASE/'PAUSED').exists() or (ROOT/'work/subtitle-metadata-library/PAUSED').exists()
write_json(BASE/'finish-status.json',dict(status='waiting_for_current_worker',pid=os.getpid(),updated=datetime.now().isoformat()))
with (BASE/'run.lock').open('a') as lock:
 fcntl.flock(lock,fcntl.LOCK_EX)
 if paused():sys.exit(0)
 write_json(BASE/'finish-status.json',dict(status='running',pid=os.getpid(),updated=datetime.now().isoformat()))
 report=[]
 for year in (2025,2026):
  c=Concert(f'grammys_{year}')
  for it in c.song_items():
   if paused():sys.exit(0)
   d=c.song_dir(it)
   try:
    seg=next(s for s in c.load('segments')['items'] if s['name']==it['name'])
    assert 0<=seg['start']<seg['end']<=c.load('info')['duration']
    audit=subtitle_audit(c,it)
    if audit['status']=='missing':
     save(c,it,status='running',stage='supplement_audio_and_subtitles')
     ensure_audio(c,it)
     with (BASE/f'{c.slug}--{it["name"]}.log').open('a') as log:
      subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,it['name']],stdout=log,stderr=subprocess.STDOUT,check=True)
    elif audit['issues']:
     raise ValueError('Existing subtitles need targeted repair; preserving them: '+str(audit['issues']))
    enable_browser(c,it)
    audit=subtitle_audit(c,it);meta=prepare_metadata(c,it)
    clip=d/'vertical/original-selected.mp4';m=probe(clip);expected=seg['end']-seg['start']
    if abs(float(m['format']['duration'])-expected)>.3:raise ValueError('Preview clip duration differs from checked boundaries')
    issues=audit['issues']+meta['issues']
    if audit['status']!='structurally_valid':issues.append('Subtitle structure invalid')
    status='needs_targeted_repair' if issues else 'pending_human_review'
    save(c,it,status=status,stage='done',subtitles=audit,metadata=meta,error=None,issues=issues,boundary_review='pending',preview_file=str(clip.resolve()))
    data=c.load('setlist')
    for row in data['items']:
     if row['name']==it['name']:row.update(review_hidden=False,ingest_status=status)
    write_json(c.setlist,data)
    report.append(dict(concert=c.slug,song=it['name'],status=status,issues=issues,unresolved_rows=audit['unresolved_alignment_rows']))
    print(status,c.slug,it['name'],issues,flush=True)
   except Exception as e:
    save(c,it,status='failed',stage='finish',error=str(e));report.append(dict(concert=c.slug,song=it['name'],status='failed',error=str(e)));traceback.print_exc()
   write_json(BASE/'completion-audit.json',dict(updated=datetime.now().isoformat(),total=34,checked=len(report),items=report,human_approved=False))
 ready=sum(r['status']=='pending_human_review' for r in report)
 write_json(BASE/'finish-status.json',dict(status='completed_for_review' if ready==34 else 'needs_targeted_repair',total=34,ready_for_review=ready,remaining=34-ready,updated=datetime.now().isoformat(),human_approved=False))
 print('FINAL',ready,'/ 34 prepared; manual review remains',flush=True)
