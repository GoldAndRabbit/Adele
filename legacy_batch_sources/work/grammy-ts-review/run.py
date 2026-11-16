import time,subprocess as sp,sys,json
from pathlib import Path
from extract import bounds,D
from migrate import migrate
from workflow.live.paths import Concert
from workflow.vertical_preview import render
from workflow.portrait_validation import preview_problem
c=Concert('grammys_2014')
for name in bounds:
 while not (D/name/'source.mp4').is_file():time.sleep(5)
 migrate(name)
 item=c.item(name)
 render(c,item,True,True)
 f=c.song_dir(item)/'vertical/full.mp4'
 v=json.loads(sp.check_output(['ffprobe','-v','error','-show_streams','-of','json',f]))['streams']
 video=next(s for s in v if s['codec_type']=='video')
 assert video['avg_frame_rate']=='50/1' and (video['width'],video['height'])==(1080,1920)
 assert abs(float(video['duration'])-(bounds[name][1]-bounds[name][0]))<.1
 assert not preview_problem(c,item,f)
 print('READY',name,flush=True)
