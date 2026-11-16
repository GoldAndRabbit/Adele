"""Replace an ASR-located dance reprise with the actual first-act performance."""
from pathlib import Path
from datetime import datetime
from types import SimpleNamespace
import sys,fcntl,subprocess,shutil,importlib.util
ROOT=Path('/Users/gold/repos/adele');base=ROOT/'work/three-concert-subtitles-20261114';sys.path[:0]=[str(base),str(ROOT)]
spec=importlib.util.spec_from_file_location('threeprep',base/'run.py');prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
from workflow.live.paths import Concert,read_json,write_json,VENV_PY
from workflow.live.package import draft_meta
from workflow.fibo_library import sample
c=Concert('gaga_coachella_2025');it=c.item('02_abracadabra');d=c.song_dir(it);name=it['name']
with (d/'covers/ai/.generation.lock').open('a') as own:
 fcntl.flock(own,fcntl.LOCK_EX)
 backup=d/'source-repair-before-20261115';backup.mkdir(exist_ok=True)
 if not (backup/'prepared.json').exists():
  for n in ['audio.flac','vocals.wav','subs','reports','stage_notes.json','watermark.json','content_box.json']:
   p=d/n
   if p.exists():shutil.move(str(p),str(backup/n))
  for n in ['song.json','post_draft.json','delivery_bundle.json']:
   if (d/n).exists():shutil.copy2(d/n,backup/n)
  write_json(backup/'prepared.json',{'before':[1580,1720],'after':[320,538],'reason':'旧范围为后段舞蹈返场；320至538秒有实际Abracadabra主歌及副歌，538秒后转入Judas','at':datetime.now().astimezone().isoformat()})
 p=c.dir/'vertical_source.json';policy=read_json(p);policy['songs'][name]['slice']=[320.0,538.0];write_json(p,policy)
 info=read_json(d/'song.json',{});info.update(slice=[320.,538.],source_file=c.load('info')['source_file'],lang='en',artist='Lady Gaga',title='Abracadabra');write_json(d/'song.json',info)
 spans=read_json(prep.common.BASE/c.slug/'locations.json')
 for r in spans:
  if r['idx']==2:r.update(start=320.,end=538.,evidence='源ASR 320分类引语、340主歌、460与520副歌；538后Judas，纠正舞蹈返场误定位')
 write_json(prep.common.BASE/c.slug/'locations.json',spans)
 seg=read_json(c.segments)
 for r in seg['items']:
  if r['name']==name:r.update(start=320.,end=538.,review='pending',flags=['已纠正返场误定位，预览首尾待人工审核'])
 write_json(c.segments,seg)
 with (c.dir/'.reference-plan.lock').open('a') as plan_lock:
  fcntl.flock(plan_lock,fcntl.LOCK_EX);p=c.dir/'fibo-cover-plan.json';plans=read_json(p);plans.pop(name,None);write_json(p,plans)
 prep.status(c.slug,name,status='running',stage='correct_performance_audio',error=None)
 prep.ensure_audio(c,it)
 prep.status(c.slug,name,status='running',stage='correct_performance_subtitles')
 with (Path.home()/'Library/Caches/adele/separator.lock').open('a') as gpu:
  fcntl.flock(gpu,fcntl.LOCK_EX)
  subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,name],cwd=ROOT,check=True)
 draft_meta(c,it,{'start':320.,'end':538.},SimpleNamespace(force=True))
 meta=prep.prepare_metadata(c,it);prep.enable_browser(c,it);prep.write_bundle(c,it);sample(c,it)
 prep.status(c.slug,name,status='needs_review',stage='done',subtitles=prep.subtitle_audit(c,it),metadata=meta,error=None)
 write_json(d/'source_repair.json',{'range':[320,538],'old_range':[1580,1720],'reason':'实际主歌副歌取代舞蹈返场','preview_rebuilt':True,'human_approved':False})
 print('ABRACADABRA_CORRECT_PREVIEW_READY',flush=True)
