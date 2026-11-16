from workflow.live.paths import *
from workflow.live.refine import cut_audio
from workflow.live.package import draft_meta
from types import SimpleNamespace
import subprocess,traceback
c=Concert('lorde_lolla_chile2026');segs={x['name']:x for x in c.load('segments')['items']}
for it in c.song_items():
 d=c.song_dir(it)
 if (d/'subs/lyrics_poetic.ass').is_file():continue
 try:
  print('REFINING',it['name'],flush=True);cut_audio(c,it,segs[it['name']])
  with (ROOT/'work/browser-library'/(it['name']+'-refine.log')).open('w') as log:
   subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,it['name']],stdout=log,stderr=subprocess.STDOUT,check=True)
  draft_meta(c,it,segs[it['name']],SimpleNamespace(force=False))
  print('REFINED',it['name'],flush=True)
 except Exception:print('REFINE_FAIL',it['name'],traceback.format_exc(),flush=True)
