"""Finish the one missing preview via the established subtitle and posting path."""
from pathlib import Path
import importlib.util,sys,fcntl,subprocess
ROOT=Path('/Users/gold/repos/adele');base=ROOT/'work/three-concert-subtitles-20261114';sys.path[:0]=[str(base),str(ROOT)]
spec=importlib.util.spec_from_file_location('threeprep',base/'run.py');prep=importlib.util.module_from_spec(spec);spec.loader.exec_module(prep)
from workflow.live.paths import Concert,read_json,write_json,VENV_PY
c=Concert('gaga_coachella_2025');it=c.item('12_killah');d=c.song_dir(it)
with (base/'killah-recovery.lock').open('a') as own:
 fcntl.flock(own,fcntl.LOCK_EX|fcntl.LOCK_NB)
 # All sung ASR blocks, including the short final 'Killah' refrain, are kept.
 # These are preview-only boundaries and remain visibly pending human review.
 hit=dict(idx=12,start=3198.0,end=3443.0,artist_zh='嘎嘎小姐',evidence='参考歌词多个锚点及3200–3420原片ASR；包含短副歌及尾奏；预览首尾待人工复核')
 p=prep.common.BASE/c.slug/'locations.json';spans=read_json(p,[])
 if not any(r['idx']==12 for r in spans):spans.append(hit);write_json(p,sorted(spans,key=lambda r:r['start']))
 info=read_json(d/'song.json',{});info.update(slice=[hit['start'],hit['end']],source_file=c.load('info')['source_file'],lang='en',artist='Lady Gaga',title='Killah');write_json(d/'song.json',info)
 seg=read_json(c.segments,{'items':[],'gaps':[]})
 if not any(r['name']==it['name'] for r in seg['items']):seg['items'].append({**it,'start':hit['start'],'end':hit['end'],'flags':['首尾定位待人工审核'],'review':'pending'});write_json(c.segments,seg)
 prep.status(c.slug,it['name'],status='running',stage='remote_audio',error=None)
 prep.ensure_audio(c,it)
 prep.status(c.slug,it['name'],status='running',stage='alignment_translation')
 # Serialize every local model used by the subtitle pipeline with FIBO.
 with (Path.home()/'Library/Caches/adele/separator.lock').open('a') as gpu:
  fcntl.flock(gpu,fcntl.LOCK_EX)
  subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,it['name']],cwd=ROOT,check=True)
 job=next(j for j in read_json(prep.common.BASE/'jobs.json') if j['slug']==c.slug)
 meta=prep.metadata(c,it,job);prep.enable_browser(c,it);prep.write_bundle(c,it)
 with (c.dir/'.review-visibility.lock').open('a') as visibility:
  fcntl.flock(visibility,fcntl.LOCK_EX);catalog=c.load('setlist')
  for row in catalog['items']:
   if row['name']==it['name']:row['review_hidden']=False
  write_json(c.setlist,catalog)
 prep.status(c.slug,it['name'],status='needs_review',stage='done',subtitles=prep.subtitle_audit(c,it),metadata=meta,error=None)
 from workflow.fibo_library import sample
 sample(c,it)
 print('KILLAH_PREVIEW_AND_POSTING_READY',flush=True)
