import json,shutil,traceback
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from workflow.live.paths import *
from workflow.browser_library import prepare_browser,probe
from workflow.vertical_cover import header_labels
from workflow.vertical_post import posting_inputs,submission
base=ROOT/'work/shakira-2160';backup=base/'before';backup.mkdir(exist_ok=True)
c=Concert('shakira_madrid_2026');new=Path('/Volumes/harddisk_5T/thunder_downloads/Shakira Live From Madrid (2026) [2160p].mkv/Shakira Live From Madrid (2026) [2160p].mkv')
data=read_json(base/'verified-alignment.json');assert len(data)==25
for key in ['concert.json','segments.json','vertical_source.json','browser_previews.json']:
 p=c.dir/key
 if p.exists() and not (backup/key).exists():shutil.copy2(p,backup/key)
for it in c.song_items():
 d=c.song_dir(it);b=backup/it['name'];b.mkdir(exist_ok=True)
 if not (b/'song.json').exists():shutil.copy2(d/'song.json',b/'song.json')
 if not (b/'subs').exists():shutil.copytree(d/'subs',b/'subs')
 assert min(a['local_score'] for a in data[it['name']]['anchors'])>.8

def process(it):
 name=it['name'];d=c.song_dir(it);status=base/(name+'.json')
 if read_json(status,{}).get('status')=='ready':return
 try:
  info=read_json(backup/name/'song.json');info['slice']=[round(t-89.45,3) for t in info['slice']];info['source_file']=str(new)
  write_json(d/'song.json',info)
  # Publish the browser source policy only after the complete clip is ready.
  write_json(status,{'status':'running'})
  out=prepare_browser(c,it)
  post,event,zh=posting_inputs(c,it,read_json(d/'post_draft.json'));f=d/'vertical';f.mkdir(exist_ok=True);write_json(f/'douyin_submission.json',submission(post,event,zh))
  write_json(status,{'status':'ready','file':str(out),'slice':info['slice'],'subtitle_alignment':'same song-relative timings; source offset -89.45s','header':header_labels(c,it)})
  print('READY',name,flush=True)
 except Exception:
  write_json(status,{'status':'failed','error':traceback.format_exc()});print(traceback.format_exc(),flush=True)
with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(process,c.song_items()))
assert all(read_json(base/(it['name']+'.json'))['status']=='ready' for it in c.song_items())
info=read_json(backup/'concert.json');info.update(source_file=str(new),duration=7290.744,fps=60.0,fps_str='60/1',width=3840,height=2160,video_codec='av1',audio_codec='opus',audio_rate=48000);info.pop('title_box',None);write_json(c.info,info)
seg=read_json(backup/'segments.json')
for r in seg['items']:
 for k in ['start','end','lyric_start','lyric_end']:
  if isinstance(r.get(k),(float,int)):r[k]=round(r[k]-89.45,3)
write_json(c.segments,seg)
if not (base/'pool-reset.done').exists():
 p=c.dir/'cover_pool'
 if p.exists():shutil.move(str(p),str(backup/'cover_pool'))
 p.mkdir();write_json(p/'quality.json',{'version':'centered-color-front-v1','stage':'extracting','frames':{}})
 for it in c.song_items():
  d=c.song_dir(it);b=backup/it['name']/'old-frames';b.mkdir(exist_ok=True)
  for frame in (d/'covers').glob('frame_*.jpg'):shutil.move(str(frame),str(b/frame.name))
  write_json(d/'vertical/candidates.json',[])
 (base/'pool-reset.done').touch()
from workflow.cover_pool_quality import upgrade
count=upgrade(c,target=100);write_json(base/'complete.json',{'songs':25,'approved_candidates':count,'source':str(new)});print('SHAKIRA_COMPLETE',count,flush=True)
