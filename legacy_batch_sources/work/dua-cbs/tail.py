import sys,subprocess,traceback
from types import SimpleNamespace
from workflow.live.paths import *
from workflow.browser_library import prepare_browser
sys.path.insert(0,str(ROOT/'workflow'))
from workflow.live.package import draft_meta
from workflow.vertical_post import posting_inputs,submission
c=Concert('an_evening_with_dua_lipa_cbs_2024');base=ROOT/'work/dua-cbs'
for key in ['11','10']:
 it=c.item(key);name=it['name'];d=c.song_dir(it);status=base/(name+'.json')
 if read_json(status,{}).get('status')=='ready':continue
 try:
  write_json(status,{'status':'preparing','worker':'tail'});print('PREPARING',name,flush=True);clip=prepare_browser(c,it)
  def run(cmd):subprocess.run([str(x) for x in cmd],check=True)
  if not (d/'audio.flac').exists():run(['/opt/homebrew/bin/ffmpeg','-nostdin','-v','error','-i',clip,'-vn','-ac','2','-ar','48000','-c:a','flac',d/'audio.flac'])
  if not (d/'vocals.wav').exists():run([SEP_PY,ROOT/'workflow/separate_roformer.py',d/'audio.flac','-o',d/'vocals.wav'])
  write_json(status,{'status':'refining','worker':'tail'})
  if not (d/'subs/lyrics_poetic.ass').exists():
   with (d/'logs/cbs-refine.log').open('w') as log:subprocess.run([str(VENV_PY),'-u','-m','workflow.song.run','song',c.slug,name],stdout=log,stderr=subprocess.STDOUT,check=True)
  seg=next(r for r in c.load('segments')['items'] if r['name']==name);draft_meta(c,it,seg,SimpleNamespace(force=False));draft,event,zh=posting_inputs(c,it,read_json(d/'post_draft.json'));write_json(d/'vertical/douyin_submission.json',submission(draft,event,zh));write_json(d/'vertical/candidates.json',read_json(d/'vertical/candidates.json',[]) if (d/'vertical/selected.json').exists() else []);write_json(status,{'status':'ready','file':str(clip)});print('READY',name,flush=True)
 except Exception:write_json(status,{'status':'failed','error':traceback.format_exc()});print(traceback.format_exc(),flush=True)
