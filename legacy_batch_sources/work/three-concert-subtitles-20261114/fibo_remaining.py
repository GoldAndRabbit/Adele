"""Resume the established FIBO workflow, one GPU job per Mac, preserving approved art."""
import sys,fcntl,shutil,json,traceback
from pathlib import Path
sys.path.insert(0,'/Users/gold/repos/adele')
from workflow.live.paths import ROOT,Concert,read_json,write_json
from workflow.fibo_concert import generate_one
from workflow.ai_cover import reviewed_revision
base=ROOT/'work/three-concert-subtitles-20261114'
MODEL=Path('/Volumes/harddisk_5T/adele-workflow/work/flux3/models/fibo2-edit-turbo-bf16')
rows=read_json(base/'ai-covers/queue.json')
with (base/'fibo-remaining.lock').open('a') as run_lock:
 fcntl.flock(run_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 status=read_json(base/'fibo-status.json',{})
 for row in rows:
  if (base/'PAUSED').exists():break
  c=Concert(row['slug']);it=c.item(row['name']);d=c.song_dir(it);key=c.slug+'/'+it['name']
  try:
   existing = sorted((ROOT/'work/fibo-batch'/c.slug/it['name']).glob('*/attempt-*/cover-review/stage.json'))
   ready = [p for p in existing if (p.parent/'art.png').exists()]
   if ready:
    status[key] = {'status':'awaiting_visual_review','stage':str(ready[-1].parent),'reused_staged':True}
    write_json(base/'fibo-status.json',status)
    continue
   if reviewed_revision(d/'covers/ai'):
    status[key]={'status':'reused_existing_reviewed'};write_json(base/'fibo-status.json',status);continue
   if read_json(base/'cover_followup.json',{}).get('stop_generation'):break
   policy=read_json(c.dir/'vertical_source.json',{}).get('songs',{}).get(it['name'])
   if not policy:raise ValueError('Song reference interval still pending')
   ai=d/'covers/ai';refs=ai/'references';refs.mkdir(parents=True,exist_ok=True)
   filename=f'fibo-source-{row["source_time"]:.3f}.jpg';reference=refs/filename
   if not reference.exists():shutil.copy2(row['frame'],reference)
   spec={'reference':'references/'+filename,'original_reference':'references/'+filename,
         'source':policy['source'],'source_range':policy['slice'],'source_time':row['source_time'],
         'scene_note':row['selection']['scene_note'],'review_framing':{'focus':[.5,.34],'zoom':1,'brand_scale':.7}}
   # Reviewed broadcast marks are confined to the top corners, away from the lead.
   if c.slug=='chappell_lolla_brasil_2026':spec['logo_boxes']=[[0,.015,.14,.23],[.69,.015,1,.15]]
   plan=read_json(c.dir/'fibo-cover-plan.json',{});plan[it['name']]=spec;write_json(c.dir/'fibo-cover-plan.json',plan)
   status[key]={'status':'generating','engine':'FIBO 2 Edit Turbo','source_time':row['source_time']};write_json(base/'fibo-status.json',status)
   result=generate_one(c,it,spec,ROOT/'work/fibo-batch'/c.slug,MODEL)
   status[key]=result;write_json(base/'fibo-status.json',status);print('FIBO_RESULT',key,result['status'],flush=True)
  except Exception as exc:
   status[key]={'status':'needs_review','error':str(exc)};write_json(base/'fibo-status.json',status);traceback.print_exc()
